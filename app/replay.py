import json
from datetime import datetime, timezone
from collections import deque
from pathlib import Path

import pyarrow.parquet as pq

from .models import DepthEvent, TradeEvent


class EventReplay:
    def __init__(self, book, flow, detector, signal_engine, journal):
        self.book = book
        self.flow = flow
        self.detector = detector
        self.signal_engine = signal_engine
        self.journal = journal

    def run_rows(self, rows):
        for r in rows:
            if r['type'] == 'trade':
                self.flow.on_trade(TradeEvent(int(r['ts_ms']), int(r['trade_id']),
                                              float(r['price']), float(r['qty']),
                                              str(r['buyer_is_maker']).lower() == 'true'))
            elif r['type'] == 'depth':
                e = DepthEvent(int(r['ts_ms']), int(r['U']), int(r['u']),
                               [(float(p), float(q)) for p, q in json.loads(r['bids_json'])],
                               [(float(p), float(q)) for p, q in json.loads(r['asks_json'])])
                self.book.apply(e)
                self.flow.on_book_event(e)
            f = self.flow.snapshot()
            s = self.signal_engine.decide(f, self.detector.detect(f))
            self.journal.write({'type': 'decision', 'action': s.action, 'score': s.score,
                                'reason': s.reason, 'features': s.features})

    def run_aggTrades_parquet(self, parquet_path, source_label, sample_every=0):
        """Stream a normalized aggTrades parquet through the order-flow engine.

        Trade-driven features (delta, CVD, buy/sell volume, trade rate) are computed
        from authentic Binance archives. L2-dependent features (imbalance, OFI) are
        recorded as 0/None when no historical book is supplied (never synthesized).
        """
        path = Path(parquet_path)
        if not path.exists():
            raise FileNotFoundError(parquet_path)
        trades_t = 0
        buys = 0
        sells = 0
        t0_ts = None
        last_ms = None
        last_ts = None

        def emit(f, tag):
            now = datetime.now(timezone.utc).isoformat()
            side = 'SELL' if f.buy_volume < f.sell_volume else 'BUY'
            self.journal.write({
                'type': 'trade_flow_bucket', 'source': source_label, 'logged_at': now,
                'dt_utc_start': t0_ts, 'dt_utc_end': last_ts,
                'trades': trades_t, 'agg_delta': round(f.delta, 6),
                'delta_dir': 'up' if f.delta > 0 else ('down' if f.delta < 0 else 'flat'),
                'buy_volume': round(f.buy_volume, 6), 'sell_volume': round(f.sell_volume, 6),
                'cvd': round(f.cvd, 6), 'trade_rate_sec': round(f.trade_rate, 3),
                'side': side, 'tag': tag,
                'l2_features_available': self.book.state.synchronized,
            })

        pf = pq.ParquetFile(path)
        for batch in pf.iter_batches(batch_size=200_000):
            df = batch.to_pandas()
            for row in df.itertuples(index=False):
                ts = int(row.transact_time)
                if t0_ts is None:
                    t0_ts = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat()
                maker = bool(row.is_buyer_maker)
                self.flow.on_trade(TradeEvent(ts, int(row.agg_trade_id),
                                              float(row.price), float(row.quantity), maker))
                trades_t += 1
                last_ms = ts
                last_ts = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat()
                if not maker:
                    buys += 1
                else:
                    sells += 1
            f = self.flow.snapshot(now_ms=last_ms)
            emit(f, 'batch')

        self.journal.write({'type': 'trade_flow_day', 'source': source_label,
                            'trades': trades_t, 'buys': buys, 'sells': sells,
                            'cvd_end': round(self.flow.cvd, 6)})
        return {'trades': trades_t, 'buys': buys, 'sells': sells,
                'cvd_end': round(self.flow.cvd, 6)}