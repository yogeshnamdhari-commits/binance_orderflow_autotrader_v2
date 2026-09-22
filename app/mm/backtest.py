from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence
import json
import math
import numpy as np
from pathlib import Path

from .config import V20Config
from .fill_sim import simulate_fill, compute_realized_pnl
from .book import OrderBook, L2Snapshot, L2Update
from .latency import LatencyModel, check_quote_staleness
from .adverse_selection import compute_post_fill_adverse_selection, compute_inventory_cost
from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from .regime_validator import validate_per_regime


@dataclass
class QuoteState:
    """Current quote state."""
    timestamp_ns: int
    bid_price: float
    ask_price: float
    bid_qty: float
    ask_qty: float
    side_preference: str


@dataclass
class FillEvent:
    """A fill that occurred."""
    timestamp_ns: int
    side: str
    fill_price: float
    fill_qty: float
    quoted_price: float
    adverse_selection_bps: float
    realized_pnl_bps: float
    reason: str


@dataclass
class MMBacktestResult:
    """Results from one backtest run."""
    pnl_bps: float
    fills: int
    cancels: int
    total_fills: int
    inventory_max: float
    inventory_final: float
    avg_adverse_selection_bps: float
    avg_realized_pnl_per_fill_bps: float
    gate_pass: bool
    gate_reasons: list[str]
    regime_results: dict = field(default_factory=dict)
    fills_per_regime: dict = field(default_factory=dict)
    win_rate: float = 0.0
    winning_fills: int = 0
    losing_fills: int = 0
    gross_profit_bps: float = 0.0
    gross_loss_bps: float = 0.0
    profit_factor: float = 0.0
    avg_win_bps: float = 0.0
    avg_loss_bps: float = 0.0
    max_win_bps: float = 0.0
    max_loss_bps: float = 0.0
    pnl_notional_usd: float = 0.0
    inventory_mtm_bps: float = 0.0
    as_by_horizon: dict[int, float] = field(default_factory=dict)
    gross_spread_capture_usd: float = 0.0
    fees_usd: float = 0.0
    adverse_selection_usd_total: float = 0.0
    execution_effects_usd: float = 0.0
    buy_fills: int = 0
    sell_fills: int = 0
    buy_filled_qty: float = 0.0
    sell_filled_qty: float = 0.0
    quote_crossings: int = 0


def compute_volatility_regime(
    spread_bps: float,
    spread_history: list[float],
    window: int = 100,
) -> int:
    """Classify volatility regime: 0=low, 1=medium, 2=high."""
    if len(spread_history) < 20:
        return 1

    recent = spread_history[-window:] if len(spread_history) >= window else spread_history
    arr = np.array(recent, dtype=float)

    p20 = np.percentile(arr, 20)
    p80 = np.percentile(arr, 80)

    if spread_bps <= p20:
        return 0
    elif spread_bps >= p80:
        return 2
    else:
        return 1


def _enforce_passive_geometry(
    bid_price: float,
    ask_price: float,
    best_bid: float,
    best_ask: float,
    tick_size: float = 0.1,
) -> tuple[float, float, bool, bool, bool]:
    """Detect crossing and return suppression flags.

    Returns (bid_price, ask_price, crossed, suppress_bid, suppress_ask).
    The caller should set qty=0 on suppressed sides.
    """
    crossed = bool(bid_price > best_bid or ask_price < best_ask)
    suppress_bid = bool(bid_price > best_bid)
    suppress_ask = bool(ask_price < best_ask)
    bid_price = min(bid_price, best_bid)
    ask_price = max(ask_price, best_ask)
    bid_price = math.floor(bid_price / tick_size) * tick_size
    ask_price = math.ceil(ask_price / tick_size) * tick_size
    bid_price = min(bid_price, best_bid)
    ask_price = max(ask_price, best_ask)
    return bid_price, ask_price, crossed, suppress_bid, suppress_ask


def generate_quotes(
    mid_price: float,
    spread_bps: float,
    inventory: float,
    config: V20Config,
) -> tuple[float, float, float, float]:
    """Generate bid/ask quotes around mid-price."""

    half_spread = config.base_half_spread_bps / 10_000.0

    volatility_buffer = (spread_bps - config.base_half_spread_bps) * 0.1
    if volatility_buffer > 0:
        half_spread += volatility_buffer / 10_000.0

    half_spread = min(half_spread, config.max_half_spread_bps / 10_000.0)

    # Normalize inventory by maximum notional and skew quotes against the
    # current position.  The old implementation used raw asset quantity and
    # moved both quotes in the wrong direction for inventory control.
    max_notional = max(abs(config.max_position_notional_usd), 1e-9)
    inventory_drift = inventory - config.inventory_target
    inventory_fraction = (inventory_drift * mid_price) / max_notional
    inventory_fraction = max(-1.0, min(1.0, inventory_fraction))
    skew_bps = -inventory_fraction * config.inventory_penalty_bps
    skew_fraction = skew_bps / 10_000.0

    bid_price = mid_price * (1.0 - half_spread + skew_fraction)
    ask_price = mid_price * (1.0 + half_spread + skew_fraction)

    bid_qty = config.quote_size_usd / bid_price if bid_price > 0 else 0
    ask_qty = config.quote_size_usd / ask_price if ask_price > 0 else 0

    return bid_price, ask_price, bid_qty, ask_qty


def _compute_empirical_adverse_selection(
    fill_price: float,
    side: str,
    event_idx: int,
    all_mid_prices: list[float],
    mid_at_fill_time: float,
    lookahead_ticks: int = 10,
) -> float:
    """
    Signed adverse selection: mid-price drift AFTER fill relative to mid at fill time.
    Positive = adverse (mid moved against position), negative = favorable.
    Baseline is mid at fill time, NOT fill_price (which already embeds spread).
    For BUY: mid drop is adverse. For SELL: mid rise is adverse.
    """
    if mid_at_fill_time <= 0 or event_idx + 1 >= len(all_mid_prices):
        return 0.0

    future_start = event_idx + 1
    future_end = min(event_idx + 1 + lookahead_ticks, len(all_mid_prices))
    future_mids = [p for p in all_mid_prices[future_start:future_end] if p > 0]

    if not future_mids:
        return 0.0

    future_mid = float(np.mean(future_mids))
    drift_bps = (future_mid - mid_at_fill_time) * 10_000.0 / mid_at_fill_time
    # BUY is adverse when mid drops (negative drift => positive AS)
    # SELL is adverse when mid rises (positive drift => positive AS)
    return -drift_bps if side == "BUY" else drift_bps


def run_mm_backtest(
    snapshot: L2Snapshot,
    depth_events: Sequence[L2Update],
    features_list: Sequence[dict],
    config: V20Config,
) -> MMBacktestResult:
    """Run realistic market-making backtest with all 8 production fixes."""

    order_book = OrderBook.from_snapshot(snapshot)

    position = 0.0
    position_notional = 0.0
    total_pnl_bps = 0.0
    total_pnl_notional_usd = 0.0
    fills_list: list[FillEvent] = []
    cancels = 0
    quote_crossings = 0
    gross_spread_capture_usd = 0.0
    total_fees_usd = 0.0
    total_adverse_selection_usd = 0.0
    total_execution_effects_usd = 0.0
    buy_fills = 0
    sell_fills = 0
    buy_filled_qty = 0.0
    sell_filled_qty = 0.0
    inventory_history = [0.0]
    spread_history: list[float] = []
    mid_price_history: list[float] = []

    latency_model = LatencyModel(mean_latency_ms=100.0, std_latency_ms=30.0)
    circuit_breaker = CircuitBreaker(
        CircuitBreakerConfig(
            max_spread_bps=5.0,
            min_total_depth_qty=1.0,
            max_price_gap_bps=10.0,
            max_position_notional=config.max_position_notional_usd,
            max_inventory_units=0.5,
        )
    )

    regime_pnl = {0: 0.0, 1: 0.0, 2: 0.0}
    regime_fills = {0: 0, 1: 0, 2: 0}
    regime_cancels = {0: 0, 1: 0, 2: 0}

    as_horizons = [1, 5, 10, 25, 50, 100]
    as_by_horizon: dict[int, list[float]] = {h: [] for h in as_horizons}

    temp_book = OrderBook.from_snapshot(snapshot)
    all_mid_prices: list[float] = []
    for depth_event in depth_events:
        try:
            temp_book.apply_update(depth_event)
            all_mid_prices.append(temp_book.get_mid_price())
        except (ValueError, IndexError):
            all_mid_prices.append(0.0)

    # Precompute cumulative sums from the right for O(1) window-mean AS.
    n_mid = len(all_mid_prices)
    as_window_mean: dict[int, list[float]] = {}
    for horizon in as_horizons:
        suffix = [0.0] * (n_mid + 1)
        for i in range(n_mid - 1, -1, -1):
            suffix[i] = suffix[i + 1] + all_mid_prices[i]
        means = []
        for i in range(n_mid):
            end = i + 1 + horizon
            if end > n_mid:
                end = n_mid
            cnt = end - (i + 1)
            if cnt > 0 and all_mid_prices[i] > 0:
                means.append((suffix[i + 1] - suffix[end]) / cnt)
            else:
                means.append(0.0)
        as_window_mean[horizon] = means

    for event_idx, (depth_event, features) in enumerate(zip(depth_events, features_list)):
        try:
            order_book.apply_update(depth_event)
        except (ValueError, IndexError):
            cancels += 1
            continue

        mid_price = order_book.get_mid_price()
        spread_bps = order_book.get_spread_bps()

        if mid_price <= 0 or spread_bps <= 0:
            continue

        mid_price_history.append(mid_price)
        spread_history.append(spread_bps)

        volatility_regime = compute_volatility_regime(spread_bps, spread_history)

        bid_depth = order_book.get_depth("bid", levels=10)
        ask_depth = order_book.get_depth("ask", levels=10)
        total_depth_qty = order_book.get_total_depth_qty("bid", 10) + order_book.get_total_depth_qty("ask", 10)

        should_quote, cb_reason = circuit_breaker.should_quote(
            mid_price=mid_price,
            spread_bps=spread_bps,
            total_depth_qty=total_depth_qty,
            position=position,
            current_price=mid_price,
        )

        if not should_quote:
            cancels += 1
            continue

        bid_price, ask_price, bid_qty, ask_qty = generate_quotes(
            mid_price=mid_price,
            spread_bps=spread_bps,
            inventory=position,
            config=config,
        )

        best_bid = max(order_book.bids.keys()) if order_book.bids else 0.0
        best_ask = min(order_book.asks.keys()) if order_book.asks else float("inf")
        crossed = False
        if best_bid < best_ask:
            raw_bid, raw_ask = bid_price, ask_price
            bid_price, ask_price, crossed, suppress_bid, suppress_ask = _enforce_passive_geometry(
                bid_price, ask_price, best_bid, best_ask
            )
            if crossed:
                quote_crossings += 1
            if suppress_bid:
                bid_qty = 0.0
            if suppress_ask:
                ask_qty = 0.0

        bid_stale = check_quote_staleness(
            quote_price=bid_price,
            mid_price_at_fill_time=mid_price,
            current_spread_bps=spread_bps,
            max_drift_std_devs=100.0,
        )
        ask_stale = check_quote_staleness(
            quote_price=ask_price,
            mid_price_at_fill_time=mid_price,
            current_spread_bps=spread_bps,
            max_drift_std_devs=100.0,
        )

        if bid_stale or ask_stale:
            cancels += 1
            continue

        buy_fill_result = (
            simulate_fill(
                quote_price=bid_price,
                quote_qty=bid_qty,
                side="BUY",
                available_depth=bid_depth,
                mid_price_at_fill_time=mid_price,
                volatility_regime=volatility_regime,
                latency_ms=latency_model.sample_latency(),
            )
            if bid_qty > 0
            else FillResult(filled=False, fill_price=0.0, fill_qty=0.0, adverse_selection_bps=0.0, reason="suppressed")
        )

        sell_fill_result = (
            simulate_fill(
                quote_price=ask_price,
                quote_qty=ask_qty,
                side="SELL",
                available_depth=ask_depth,
                mid_price_at_fill_time=mid_price,
                volatility_regime=volatility_regime,
                latency_ms=latency_model.sample_latency(),
            )
            if ask_qty > 0
            else FillResult(filled=False, fill_price=0.0, fill_qty=0.0, adverse_selection_bps=0.0, reason="suppressed")
        )

        fills_this_event = []

        if buy_fill_result.filled:
            fills_this_event.append(("BUY", buy_fill_result))
        if sell_fill_result.filled:
            fills_this_event.append(("SELL", sell_fill_result))

        if len(fills_this_event) == 2:
            if position > 0:
                fills_this_event = [f for f in fills_this_event if f[0] == "SELL"]
            elif position < 0:
                fills_this_event = [f for f in fills_this_event if f[0] == "BUY"]

        for side, fill_result in fills_this_event:
            _mid_at_fill = mid_price
            _is_buy = side == "BUY"

            def _as_for(lookahead: int) -> float:
                future_start = event_idx + 1
                if future_start >= n_mid:
                    return 0.0
                future_end = min(future_start + lookahead, n_mid)
                window = as_window_mean[lookahead][future_start:future_end]
                future_mids = [p for p in window if p > 0]
                if not future_mids:
                    return 0.0
                future_mid = float(np.mean(future_mids))
                drift_bps = (future_mid - _mid_at_fill) * 10_000.0 / _mid_at_fill
                return -drift_bps if _is_buy else drift_bps

            adverse_selection_bps = _as_for(10)

            for horizon in as_horizons:
                as_h = _as_for(horizon)
                as_by_horizon[horizon].append(as_h)

            realized_pnl_bps = compute_realized_pnl(
                fill_price=fill_result.fill_price,
                fill_qty=fill_result.fill_qty,
                mid_price=mid_price,
                side=side,
                maker_fee_bps=config.maker_fee_bps,
                taker_fee_bps=config.taker_fee_bps,
                is_maker=True,
                adverse_selection_bps=adverse_selection_bps,
            )

            if side == "BUY":
                spread_capture_bps = (mid_price - fill_result.fill_price) * 10_000.0 / fill_result.fill_price
                buy_fills += 1
                buy_filled_qty += fill_result.fill_qty
            else:
                spread_capture_bps = (fill_result.fill_price - mid_price) * 10_000.0 / fill_result.fill_price
                sell_fills += 1
                sell_filled_qty += fill_result.fill_qty

            fill_notional = fill_result.fill_price * fill_result.fill_qty
            gross_spread_capture_usd += spread_capture_bps / 10_000.0 * fill_notional
            fee_bps = config.maker_fee_bps
            total_fees_usd += fee_bps / 10_000.0 * fill_notional
            total_adverse_selection_usd += adverse_selection_bps / 10_000.0 * fill_notional
            if crossed:
                total_execution_effects_usd += (config.taker_fee_bps - config.maker_fee_bps) / 10_000.0 * fill_notional

            position_change = fill_result.fill_qty if side == "BUY" else -fill_result.fill_qty
            position += position_change
            position_notional += position_change * fill_result.fill_price

            fill_notional_usd = fill_result.fill_qty * fill_result.fill_price
            total_pnl_notional_usd += fill_notional_usd * realized_pnl_bps / 10_000.0

            fill_event = FillEvent(
                timestamp_ns=depth_event.timestamp_ns,
                side=side,
                fill_price=fill_result.fill_price,
                fill_qty=fill_result.fill_qty,
                quoted_price=bid_price if side == "BUY" else ask_price,
                adverse_selection_bps=adverse_selection_bps,
                realized_pnl_bps=realized_pnl_bps,
                reason=fill_result.reason,
            )
            fills_list.append(fill_event)

            total_pnl_bps += realized_pnl_bps
            regime_pnl[volatility_regime] += realized_pnl_bps
            regime_fills[volatility_regime] += 1

        inventory_history.append(position)

    final_mid = mid_price_history[-1] if mid_price_history else 0.0
    inventory_mtm_bps = 0.0
    if final_mid > 0 and position != 0.0:
        avg_entry = position_notional / position if position != 0 else 0.0
        if avg_entry > 0:
            inventory_mtm_bps = (final_mid - avg_entry) / avg_entry * 10_000.0 * abs(position)
            if position < 0:
                inventory_mtm_bps = -inventory_mtm_bps

    num_fills = len(fills_list)
    avg_adverse_selection = float(np.mean([f.adverse_selection_bps for f in fills_list])) if fills_list else 0.0
    avg_pnl_per_fill = float(total_pnl_bps / num_fills) if num_fills > 0 else 0.0

    inventory_max = float(max(abs(x) for x in inventory_history))
    inventory_final = float(position)

    winning_fills = [f.realized_pnl_bps for f in fills_list if f.realized_pnl_bps > 0]
    losing_fills = [f.realized_pnl_bps for f in fills_list if f.realized_pnl_bps < 0]
    win_rate = float(len(winning_fills) / num_fills * 100.0) if num_fills > 0 else 0.0

    gross_profit_bps = float(sum(winning_fills))
    gross_loss_bps = float(abs(sum(losing_fills)))
    profit_factor = float(gross_profit_bps / gross_loss_bps) if gross_loss_bps > 0 else float("nan")

    avg_win = float(np.mean(winning_fills)) if winning_fills else 0.0
    avg_loss = float(np.mean(losing_fills)) if losing_fills else 0.0

    max_win = float(max(winning_fills)) if winning_fills else 0.0
    max_loss = float(min(losing_fills)) if losing_fills else 0.0

    as_by_horizon_mean = {h: float(np.mean(v)) if v else 0.0 for h, v in as_by_horizon.items()}

    gate_reasons = []
    gate_pass = True

    if total_pnl_bps <= 0:
        gate_reasons.append("total_pnl_non_positive")
        gate_pass = False

    if inventory_max > 0.5:
        gate_reasons.append(f"inventory_breach ({inventory_max:.4f} > 0.5)")
        gate_pass = False

    if num_fills < 10:
        gate_reasons.append(f"insufficient_fills ({num_fills} < 10)")
        gate_pass = False

    regime_results = validate_per_regime(regime_pnl, min_pnl_bps=100.0)
    for rr in regime_results:
        if not rr.gate_pass and rr.pnl_bps > 0:
            gate_reasons.append(f"regime_{rr.regime_id}_unprofitable")

    return MMBacktestResult(
        pnl_bps=float(total_pnl_bps),
        fills=num_fills,
        cancels=cancels,
        total_fills=num_fills + cancels,
        inventory_max=inventory_max,
        inventory_final=inventory_final,
        avg_adverse_selection_bps=avg_adverse_selection,
        avg_realized_pnl_per_fill_bps=avg_pnl_per_fill,
        gate_pass=gate_pass,
        gate_reasons=gate_reasons if not gate_pass else ["pass"],
        regime_results={rr.regime_id: rr for rr in regime_results},
        fills_per_regime=regime_fills,
        win_rate=win_rate,
        winning_fills=len(winning_fills),
        losing_fills=len(losing_fills),
        gross_profit_bps=gross_profit_bps,
        gross_loss_bps=gross_loss_bps,
        profit_factor=profit_factor,
        avg_win_bps=avg_win,
        avg_loss_bps=avg_loss,
        max_win_bps=max_win,
        max_loss_bps=max_loss,
        pnl_notional_usd=float(total_pnl_notional_usd),
        inventory_mtm_bps=float(inventory_mtm_bps),
        as_by_horizon=as_by_horizon_mean,
        gross_spread_capture_usd=float(gross_spread_capture_usd),
        fees_usd=float(total_fees_usd),
        adverse_selection_usd_total=float(total_adverse_selection_usd),
        execution_effects_usd=float(total_execution_effects_usd),
        buy_fills=buy_fills,
        sell_fills=sell_fills,
        buy_filled_qty=buy_filled_qty,
        sell_filled_qty=sell_filled_qty,
        quote_crossings=quote_crossings,
    )


def build_run_provenance(
    config_path: str | None = None,
    seed: int | None = None,
    command: str | None = None,
    fail_on_dirty: bool = True,
) -> dict:
    """Provenance envelope identifying the exact code+config+data for a run.

    Records Git commit, config SHA-256 (single source of truth:
    app/mm/config.json), seed and command so results are reproducible.
    Fails closed when the working tree has uncommitted changes.
    """
    import subprocess

    repo_dir = Path(__file__).resolve().parents[2]
    try:
        git_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_dir,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        git_commit = "unknown"

    try:
        git_status = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=repo_dir,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        git_status = ""

    dirty = bool(git_status)
    if dirty and fail_on_dirty:
        raise RuntimeError(
            f"working tree is dirty — commit changes before running:\n{git_status}"
        )

    config_sha = None
    if config_path:
        try:
            from .config import config_sha256

            config_sha = config_sha256(config_path)
        except Exception:
            config_sha = "unreadable"
    return {
        "git_commit": git_commit,
        "git_dirty": dirty,
        "git_status": git_status[:500] if git_status else "",
        "config_path": config_path,
        "config_sha256": config_sha,
        "seed": seed,
        "command": command,
    }


def _compute_backtest_features(
    depth_events: Sequence[L2Update],
    snapshot: L2Snapshot,
) -> list[dict]:
    """Compute empirical spread-based features for the backtest.

    Because ``run_mm_backtest`` classifies volatility regime internally from
    spread history, this function returns lightweight per-event features
    that capture the spread z-score relative to the rolling spread distribution.
    """
    book = OrderBook.from_snapshot(snapshot)
    spreads: list[float] = []
    mids: list[float] = []
    features: list[dict] = []

    for ev in depth_events:
        try:
            book.apply_update(ev)
        except (ValueError, IndexError):
            features.append({"spread_bps_zscore": 0.0, "volatility_regime": 1})
            continue

        mid = book.get_mid_price()
        spread = book.get_spread_bps()
        if mid <= 0 or spread <= 0:
            mids.append(0.0)
            spreads.append(0.0)
            features.append({"spread_bps_zscore": 0.0, "volatility_regime": 1})
            continue

        mids.append(mid)
        spreads.append(spread)

        if len(spreads) >= 20:
            arr = np.array(spreads[-200:], dtype=float)
            mean = float(np.mean(arr))
            std = float(np.std(arr))
            zscore = (spread - mean) / std if std > 1e-12 else 0.0
            zscore = max(-5.0, min(5.0, zscore))
        else:
            zscore = 0.0

        regime = compute_volatility_regime(spread, spreads, window=100)

        features.append({
            "spread_bps_zscore": float(zscore),
            "volatility_regime": int(regime),
        })

    return features


def run_all_mm_backtests(
    captures_dir: str,
    config: V20Config,
    config_path: str | None = None,
    seed: int | None = None,
    command: str | None = None,
) -> dict:
    """Run MM backtest on all captures.

    Provide ``config_path`` (authoritative config.json), ``seed`` and
    ``command`` so the run prints a provenance chain:
    Git commit / config SHA-256 / capture / seed / command / result.
    If ``seed`` is given, numpy RNG is seeded for reproducibility.
    """
    import subprocess

    if seed is not None:
        np.random.seed(seed)
    if config_path is None:
        from .config import CONFIG_JSON_DEFAULT

        config_path = CONFIG_JSON_DEFAULT
    provenance = build_run_provenance(config_path=config_path, seed=seed, command=command)
    try:
        print(
            f"Provenance: git={provenance['git_commit'][:12]} "
            f"config={config_path} sha256={provenance['config_sha256']} "
            f"seed={seed} command={command}"
        )
    except Exception:
        pass

    results = {}
    captures_path = Path(captures_dir)

    for capture_dir in sorted(captures_path.iterdir()):
        if not capture_dir.is_dir():
            continue

        snapshot_file = capture_dir / "snapshot.json"
        events_file = capture_dir / "events.jsonl"

        if not snapshot_file.exists() or not events_file.exists():
            continue

        print(f"Processing {capture_dir.name}...", flush=True)

        with open(snapshot_file) as f:
            snap_data = json.load(f)
            snapshot = L2Snapshot(
                timestamp_ns=int(snap_data["E"]),
                last_update_id=int(snap_data["lastUpdateId"]),
                bids=[(float(p), float(q)) for p, q in snap_data["bids"]],
                asks=[(float(p), float(q)) for p, q in snap_data["asks"]],
            )

        depth_events = []
        with open(events_file) as f:
            for line in f:
                event_data = json.loads(line)
                if event_data.get("event_type") != "depthUpdate":
                    continue
                raw = json.loads(event_data["raw_json"])
                data = raw.get("data", raw)
                if data.get("e", "").lower() != "depthupdate":
                    continue
                update = L2Update(
                    timestamp_ns=int(event_data["event_time_ms"]) * 1_000_000,
                    first_update_id=int(data["U"]),
                    final_update_id=int(data["u"]),
                    prev_final_update_id=int(data.get("pu", 0)),
                    bids=[(float(p), float(q)) for p, q in data.get("b", [])],
                    asks=[(float(p), float(q)) for p, q in data.get("a", [])],
                )
                depth_events.append(update)

        features_list = _compute_backtest_features(depth_events, snapshot)

        result = run_mm_backtest(snapshot, depth_events, features_list, config)
        results[capture_dir.name] = result

        print(f"  PnL: {result.pnl_bps:.2f} bps (${result.pnl_notional_usd:.2f})")
        print(f"  Fills: {result.fills}, Cancels: {result.cancels}")
        if result.winning_fills or result.losing_fills:
            print(f"  Win rate: {result.win_rate:.2f}% ({result.winning_fills} wins, {result.losing_fills} losses)")
            print(f"  Profit factor: {result.profit_factor:.2f}")
            print(f"  Avg win: {result.avg_win_bps:.4f} bps, Avg loss: {result.avg_loss_bps:.4f} bps")
            print(f"  Max win: {result.max_win_bps:.4f} bps, Max loss: {result.max_loss_bps:.4f} bps")
        else:
            print("  No fills observed")
        print(f"  Inventory: max={result.inventory_max:.4f}, final={result.inventory_final:.4f}")
        if result.inventory_mtm_bps != 0.0:
            print(f"  Inventory MTM: {result.inventory_mtm_bps:.2f} bps")
        if result.as_by_horizon:
            horizon_str = ", ".join(f"{h}ticks={v:.2f}" for h, v in sorted(result.as_by_horizon.items()))
            print(f"  Adverse selection by horizon: {horizon_str}")
        print(f"  Gate: {'PASS' if result.gate_pass else 'FAIL'}")
        print()

    return results
