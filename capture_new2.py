import sys
sys.path.insert(0, '/Users/targetmobile/Downloads/binance_orderflow_autotrader_v2')

from app.v12.capture import capture_session
from pathlib import Path
import uuid

capture_id = uuid.uuid4().hex
output_dir = Path("data/captures") / capture_id
output_dir.mkdir(parents=True, exist_ok=True)

print(f"Starting 60-minute capture: {capture_id}")
print(f"Output: {output_dir}")
print(f"Symbol: BTCUSDT, Duration: 3600s")
sys.stdout.flush()

result = capture_session(
    symbol="BTCUSDT",
    output_dir=output_dir,
    duration_seconds=3600,
)

print(f"Capture complete: valid={result.valid}")
print(f"  Events: {result.event_counts}")
print(f"  Reconnects: {result.reconnects}, Gaps: {result.gaps}")
print(f"  Session dir: {result.session_dir}")
if result.valid:
    print(f"  Bootstrap: BRIDGED")
else:
    print(f"  Invalid: {result.invalid_reason}")
