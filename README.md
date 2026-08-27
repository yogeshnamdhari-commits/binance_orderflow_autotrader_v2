# Binance Order-Flow AutoTrader V2

Production-oriented research/live foundation for Binance USDⓈ-M Futures.

Locked scope: authentic Binance depth + trade data; local L2 book; OFI/MLOFI; Delta/CVD; liquidity behavior; microstructure events; BUY/SELL/NO TRADE; risk; replay/backtest interfaces; trade journal; paper mode by default.

Historical L2 is a separate Binance facility and is not reconstructed from candles.

## Governance: ORDERFLOW_BASELINE_V5 — NO LIVE TRADING

The frozen V5 signal has been validated (Tier-A) and found to have no deployable
economic edge at the current measured cost gate (4.6658 bps). Live trading is
**hard-locked off** at the code level (`app/orchestrator.py`, `app/main.py`)
until Q2 (contemporaneous execution cost) is measured and compared against the
established signal expectancy. This is not an environment toggle; it is a
deliberate code-level governance rule.

## Quick start
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.main --symbol BTCUSDT

Live execution is intentionally OFF until execution/reconciliation and statistical gates pass.

## Q2: Contemporaneous execution cost measurement

Run the Q2 pipeline to measure live execution cost and compare it against the
historical V5 gate:

    python -m app.v5_q2_execution_cost --minutes 30 --symbol btcusdt

Outputs:
- `data/research/v5/Q2/v5_q2_report.json`
- `data/research/v5/Q2/v5_q2_report.md`
- `data/live/cost_calibration.json`
- `data/live/cost_calibration.md`
