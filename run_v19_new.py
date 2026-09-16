import sys
sys.path.insert(0, '/Users/targetmobile/Downloads/binance_orderflow_autotrader_v2')

from pathlib import Path
from app.v19.config import load_v19_config
from app.v19.replay import run_historical_replay
from app.v19.pipeline import write_evidence

config = load_v19_config(Path('/Users/targetmobile/Downloads/binance_orderflow_autotrader_v2/app/v19/config.json'))
events_path = Path('/Users/targetmobile/Downloads/binance_orderflow_autotrader_v2/data/captures/e4153485b12e4ac2b80b4ff81bc08870/events.jsonl')
output_path = Path('/Users/targetmobile/Downloads/binance_orderflow_autotrader_v2/data/captures/e4153485b12e4ac2b80b4ff81bc08870/v19_evidence.json')

print("Starting V19 pipeline on new capture...")
print(f"Events: {events_path}")
print(f"Output: {output_path}")
sys.stdout.flush()

result = run_historical_replay(events_path, config)
write_evidence(result, output_path)

print(f"V19 gate={'PASS' if result['gate_pass'] else 'FAIL'} net_ev_bps={result['net_ev_bps']:.6f}")
print(f"  n_folds={result['n_folds']} n_test_events={result['n_test_events']}")
print(f"  ci=[{result['ci_low_bps']:.4f}, {result['ci_high_bps']:.4f}]")
print(f"  cost_stress={result['cost_stress']}")
