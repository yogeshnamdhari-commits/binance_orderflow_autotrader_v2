import sys
sys.path.insert(0, "/Users/targetmobile/Downloads/binance_orderflow_autotrader_v2")
from app.v12.capture import capture_session

r = capture_session("BTCUSDT", "data/v14/forward", 360)
print("V14_FORWARD_CAPTURE_DONE", r.valid, r.event_counts, "session=" + r.session_dir.name, flush=True)
