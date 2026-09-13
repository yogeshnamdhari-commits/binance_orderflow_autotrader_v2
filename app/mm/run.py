from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.mm.backtest import MarketMakingBacktest
from app.mm.gate import evaluate_mm_gate
from app.v19.config import load_v19_config
from app.v19.replay import run_historical_replay


def main() -> None:
    parser = argparse.ArgumentParser(description="Market-making replay evaluation")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    config = load_v19_config(args.config)

    mm_config = json.loads(Path("app/mm/config.json").read_text())

    result = run_historical_replay(args.events, config)

    from app.v19.features import L2Event, compute_orderflow_features
    from app.mm.backtest import MarketMakingBacktest

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

    from app.v19.replay import _load_rows, _reconstruct_depth, _trade_rows, _attach_trades

    rows = _load_rows(args.events)
    snapshot_path = args.events.parent / "snapshot.json"
    books = _reconstruct_depth(rows, snapshot_path=snapshot_path)
    trades = _trade_rows(rows)
    observed_events = _attach_trades(books, trades)

    mm_result = backtest.run(observed_events, mm_config)
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
        "v19_net_ev_bps": result["net_ev_bps"],
        "v19_gate_pass": result["gate_pass"],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"MM gate={'PASS' if gate_result.passed else 'FAIL'} total_pnl_bps={mm_result.total_pnl_bps:.4f}")
    print(f"  realized_spread={mm_result.realized_spread_bps:.4f} fills={mm_result.fill_count} cancels={mm_result.cancel_count}")


if __name__ == "__main__":
    main()
