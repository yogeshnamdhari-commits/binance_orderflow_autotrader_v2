import json, time, threading, requests, websocket
from .models import DepthEvent, TradeEvent


class BinanceMarketFeed:
    """USDⓈ-M Futures market data feed (depth + trade + bookTicker).

    Synchronization follows Binance futures @depth@100ms semantics:
      - REST snapshot -> lastUpdateId
      - drop buffered depth events with u <= lastUpdateId (already covered)
      - first kept event must satisfy  U <= lastUpdateId+1 <= u
      - replay kept events, then stream live updates.

    Reconnect uses exponential backoff. bookTicker (top-of-book) is recorded for
    diagnostics and used as a spread/mid fallback only when the L2 book is not yet
    synchronized (never as a substitute for L2 reconstruction).
    """

    def __init__(self, cfg, symbol, book, flow, status_cb=print):
        self.cfg = cfg
        self.symbol = symbol.lower()
        self.book = book
        self.flow = flow
        self.status_cb = status_cb
        self.stop_flag = False
        self.buffer = []
        self.ready = False
        self.lock = threading.RLock()
        self.last_book_ticker = None
        self._backoff = 1.0
        self._max_backoff = 30.0

    def snapshot(self):
        r = requests.get(self.cfg.rest + '/fapi/v1/depth',
                         params={'symbol': self.symbol.upper(), 'limit': 1000}, timeout=5)
        r.raise_for_status()
        return r.json()

    def synchronize(self):
        snap = self.snapshot()
        sid = int(snap['lastUpdateId'])
        with self.lock:
            # Drop events already covered by the snapshot (u <= sid), keep the rest.
            pending = [x for x in self.buffer if x.final_update_id > sid]
            if not pending:
                return False
            first = pending[0]
            if not (first.first_update_id <= sid + 1 <= first.final_update_id):
                return False
            self.book.load_snapshot(snap['bids'], snap['asks'], sid)
            for e in pending:
                if self.book.apply(e) == 'GAP':
                    self.book.state.synchronized = False
                    return False
            self.buffer = []  # consumed
            self.ready = self.book.state.synchronized
            return self.ready

    # -- WebSocket callbacks exposed as methods for observability/testability --
    def on_open(self, ws):
        self._backoff = 1.0
        self.status_cb({'status': 'CONNECTED'})

        def worker():
            while not self.stop_flag:
                if not self.ready:
                    try:
                        if self.synchronize():
                            self.status_cb({'status': 'BOOK_READY'})
                    except Exception as e:
                        self.status_cb({'status': 'SNAPSHOT_ERROR', 'error': repr(e)})
                time.sleep(.05)
        threading.Thread(target=worker, daemon=True).start()

    def on_message(self, ws, raw):
        try:
            m = json.loads(raw).get('data', {})
            ev = m.get('e')
            if ev == 'depthUpdate':
                e = DepthEvent(int(m['E']), int(m['U']), int(m['u']),
                               [(float(p), float(q)) for p, q in m['b']],
                               [(float(p), float(q)) for p, q in m['a']])
                with self.lock:
                    if not self.ready:
                        self.buffer.append(e)
                    else:
                        if self.book.apply(e) == 'GAP':
                            self.ready = False
                            self.status_cb({'status': 'BOOK_GAP'})
                if self.ready:
                    self.flow.on_book_event(e)
            elif ev in ('aggTrade', 'trade'):
                self.flow.on_trade(TradeEvent(
                    int(m['T']), int(m.get('a', m.get('t', 0))),
                    float(m['p']), float(m['q']), bool(m['m'])))
            elif ev == 'bookTicker':
                self.last_book_ticker = {
                    'b': float(m['b']), 'B': float(m['B']),
                    'a': float(m['a']), 'A': float(m['A']), 'E': int(m.get('E', 0))}
        except Exception as e:
            self.status_cb({'status': 'PARSE_ERROR', 'error': repr(e)})

    def on_error(self, ws, err):
        self.status_cb({'status': 'WS_ERROR', 'error': repr(err)})

    def on_close(self, ws, *args):
        self.ready = False
        self.status_cb({'status': 'CLOSED'})

    def run(self):
        streams = f'{self.symbol}@depth@100ms/{self.symbol}@trade/{self.symbol}@bookTicker'
        url = self.cfg.ws + '?streams=' + streams
        while not self.stop_flag:
            try:
                app = websocket.WebSocketApp(url, on_open=self.on_open,
                                             on_message=self.on_message,
                                             on_error=self.on_error,
                                             on_close=self.on_close)
                app.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                self.status_cb({'status': 'RUN_ERROR', 'error': repr(e)})
            if self.stop_flag:
                break
            # Exponential backoff before reconnect.
            time.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, self._max_backoff)
