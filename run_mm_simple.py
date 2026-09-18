import sys
sys.path.insert(0, '/Users/targetmobile/Downloads/binance_orderflow_autotrader_v2')

import json
from pathlib import Path
from app.v19.features import L2Event, compute_orderflow_features
from app.mm.backtest import MarketMakingBacktest, MMResult, MMTrade
from app.mm.gate import evaluate_mm_gate
from app.v19.config import load_v19_config

mm_config = json.loads(Path("app/mm/config.json").read_text())
config = load_v19_config(Path("app/v19/config.json"))

events_path = Path("data/captures/e4153485b12e4ac2b80b4ff81bc08870/events.jsonl")
output_path = Path("data/captures/e4153485b12e4ac2b80b4ff81bc08870/mm_results.json")
snapshot_path = events_path.parent / "snapshot.json"

# Load snapshot
with snapshot_path.open("r") as f:
    snap = json.load(f)
bids = {float(p): float(q) for p, q in snap.get("bids", []) if float(q) > 0}
asks = {float(p): float(q) for p, q in snap.get("asks", []) if float(q) > 0}

# Read first 5000 depth update rows
print("Reading events...")
rows = []
with events_path.open("r") as f:
    for line in f:
        row = json.loads(line.strip())
        raw_json = row.get("raw_json")
        if raw_json:
            payload = json.loads(raw_json)
            data = payload.get("data", payload)
            if str(data.get("e", "")).lower() == "depthupdate":
                rows.append(row)
        if len(rows) >= 5000:
            break
print(f"Loaded {len(rows)} depth update rows")

# Build L2 events from depth updates
events = []
for row in rows:
    ts_ms = int(row.get("event_time_ms", 0))
    raw_json = row.get("raw_json")
    payload = json.loads(raw_json)
    data = payload.get("data", payload)
    b = [(float(p), float(q)) for p, q in data.get("b", [])]
    a = [(float(p), float(q)) for p, q in data.get("a", [])]
    bid_levels = tuple(sorted(bids.items(), key=lambda x: x[0], reverse=True))
    ask_levels = tuple(sorted(asks.items(), key=lambda x: x[0]))
    if bid_levels and ask_levels:
        bid_px, bid_qty = bid_levels[0]
        ask_px, ask_qty = ask_levels[0]
        if ask_px >= bid_px:
            events.append(L2Event(
                ts_ms * 1_000_000, bid_px, bid_qty, ask_px, ask_qty,
                bid_levels=bid_levels, ask_levels=ask_levels,
            ))
print(f"Created {len(events)} L2 events")

if len(events) < 10:
    print("Not enough events")
    sys.exit(1)

# Pre-compute features
print("Pre-computing features...")
features_by_idx = {}
for i, event in enumerate(events):
    try:
        feats = compute_orderflow_features(events[:i + 1], event.timestamp_ns)
        features_by_idx[i] = feats
    except Exception:
        features_by_idx[i] = None

current_price = (events[-1].bid_px + events[-1].ask_px) / 2.0
print(f"Current price: {current_price}")

# Run MM backtest
print("Running market-making backtest...")
backtest = MarketMakingBacktest(
    base_half_spread_bps=mm_config["base_half_spread_bps"],
    max_half_spread_bps=mm_config["max_half_spread_bps"],
    inventory_penalty_bps=mm_config["inventory_penalty_bps"],
    inventory_target=mm_config["inventory_target"],
    max_position_notional_usd=mm_config["max_position_notional_usd"],
    adverse_selection_threshold_bps=mm_config["adverse_selection_threshold_bps"],
    cancel_on_adverse_selection=mm_config["cancel_on_adverse_selection"],
    maker_fee_bps=mm_config["maker_fee_bps"],
    taker_fee_bps=mm_config["taker_fee_bps"],
)

trades_list = []
cancels = 0
total_pnl = 0.0
realized_spread = 0.0
adverse_selection_total = 0.0
maker_fees_total = 0.0
max_inventory = 0.0
position = 0.0
regime_pnl = {}

for i, event in enumerate(events):
    features = features_by_idx.get(i)
    if features is None:
        continue

    now_ns = event.timestamp_ns
    inventory_state = backtest.inventory_manager.update(
        position, current_price, "", 0.0
    )
    max_inventory = max(max_inventory, abs(inventory_state.position))

    quote_state = backtest.quote_engine.generate_quotes(
        events[:i + 1], now_ns, current_price, inventory_state.position, mm_config.get("max_position_notional_usd", 5000.0),
        features=features,
    )

    adverse_selection = features["spread_bps_zscore"] * 0.5
    should_cancel, cancel_reason = backtest.quote_engine.should_cancel(quote_state, features, adverse_selection)
    if should_cancel:
        cancels += 1
        continue

    mid_price = (event.bid_px + event.ask_px) / 2.0

    buy_fill = backtest._simulate_fill(
        quote_side="BUY",
        quote_price=quote_state.bid_price,
        quote_qty=quote_state.bid_qty,
        mid_price=mid_price,
        trade_qty=0.001,
    )

    sell_fill = backtest._simulate_fill(
        quote_side="SELL",
        quote_price=quote_state.ask_price,
        quote_qty=quote_state.ask_qty,
        mid_price=mid_price,
        trade_qty=0.001,
    )

    fill_result = buy_fill if buy_fill.realized_pnl_bps > sell_fill.realized_pnl_bps else sell_fill

    if fill_result.filled:
        trade = MMTrade(
            side=fill_result.side,
            price=fill_result.price,
            qty=fill_result.qty,
            timestamp_ns=now_ns,
            realized_pnl_bps=fill_result.realized_pnl_bps,
            adverse_selection_bps=fill_result.adverse_selection_bps,
            queue_position=fill_result.queue_position,
        )
        trades_list.append(trade)
        total_pnl += fill_result.realized_pnl_bps
        realized_spread += fill_result.realized_pnl_bps + fill_result.adverse_selection_bps
        adverse_selection_total += fill_result.adverse_selection_bps
        maker_fees_total += backtest.fill_sim.maker_fee_bps

        if fill_result.side == "BUY":
            position += fill_result.qty
        else:
            position -= fill_result.qty

        inventory_state = backtest.inventory_manager.update(
            position, current_price, fill_result.side, fill_result.qty
        )
        max_inventory = max(max_inventory, abs(inventory_state.position))

        regime = int(features["volatility_regime"])
        regime_pnl[regime] = regime_pnl.get(regime, 0.0) + fill_result.realized_pnl_bps

mm_result = MMResult(
    total_pnl_bps=float(total_pnl),
    realized_spread_bps=float(realized_spread),
    adverse_selection_bps=float(adverse_selection_total),
    maker_fees_bps=float(maker_fees_total),
    fill_count=len(trades_list),
    cancel_count=cancels,
    inventory_max=float(max_inventory),
    inventory_final=float(position),
    regime_profitability={int(k): float(v) for k, v in regime_pnl.items()},
    trades=tuple(trades_list),
)

gate_result = evaluate_mm_gate(mm_result, config)

output = {
    "mm_total_pnl_bps": mm_result.total_pnl_bps,
    "mm_realized_spread_bps": mm_result.realized_spread_bps,
    "mm_adverse_selection_bps": mm_result.adverse_selection_bps,
    "mm_fill_count": mm_result.fill_count,
    "mm_cancel_count": mm_result.cancel_count,
    "mm_inventory_max": mm_result.inventory_max,
    "mm_inventory_final": mm_result.inventory_final,
    "mm_regime_profitability": mm_result.regime_profitability,
    "gate_pass": gate_result.passed,
    "gate_reasons": list(gate_result.reasons),
    "gate_cost_stress": gate_result.cost_stress,
}

output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"MM gate={'PASS' if gate_result.passed else 'FAIL'} total_pnl_bps={mm_result.total_pnl_bps:.4f}")
print(f"  realized_spread={mm_result.realized_spread_bps:.4f} fills={mm_result.fill_count} cancels={mm_result.cancel_count}")
print(f"  inventory_max={mm_result.inventory_max:.4f} inventory_final={mm_result.inventory_final:.4f}")
print(f"  regime_profitability={mm_result.regime_profitability}")
