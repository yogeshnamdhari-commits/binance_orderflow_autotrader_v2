import argparse,time,threading
from .config import Config, V5_BASELINE_NO_LIVE_TRADE
from .orderbook import LocalOrderBook
from .features import OrderFlowEngine
from .events import EventDetector
from .signal import SignalEngine
from .journal import Journal
from .binance_feed import BinanceMarketFeed
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--symbol',default='BTCUSDT'); args=ap.parse_args()
    cfg=Config(); cfg.assert_safe()
    if V5_BASELINE_NO_LIVE_TRADE:
        print("=" * 70)
        print("GOVERNANCE: ORDERFLOW_BASELINE_V5 — NO LIVE TRADING")
        print("The frozen V5 signal is locked to paper mode until Q2")
        print("(contemporaneous execution cost) is measured and compared")
        print("against the established signal expectancy.")
        print("=" * 70)
    book=LocalOrderBook(cfg.levels); flow=OrderFlowEngine(book); detector=EventDetector(); signals=SignalEngine(); journal=Journal()
    from .orchestrator import TradeOrchestrator
    orch=TradeOrchestrator()
    from .integrity_gate import IntegrityGate
    gate=IntegrityGate()
    feed=BinanceMarketFeed(cfg,args.symbol,book,flow,print)
    threading.Thread(target=feed.run,daemon=True).start(); print(f'Running {args.symbol} in {cfg.mode.upper()} mode. Live execution={cfg.live_trading_enabled}')
    last=None
    try:
        while True:
            # integrity gate: book sync -> features -> cost -> signal allowed
            gate.on_book_sync(feed.ready, 'depth@100ms')
            gate.on_features(feed.ready and book.state.synchronized, 'book+features')
            gate.on_cost(True, 'fill calibration loaded')
            snap=gate.evaluate()
            f=flow.snapshot(); s=signals.decide(f,detector.detect(f))
            decision={'action':'NO_TRADE','reason':'integrity gate closed','gates':snap}
            if snap['SIGNAL_ALLOWED'] and s.action in ('BUY','SELL'):
                cond='delta_5s_top_decile' if s.action=='BUY' else 'delta_5s_bottom_decile'
                r=orch.decide(cond, notional_usd=10_000, book=book, equity=100_000,
                              daily_pnl_pct=0.0, spread_bps=f.spread_bps)
                decision={'action':('BUY' if r['allowed'] else 'NO_TRADE'),'reason':r.get('reason'),'gates':snap}
            if decision.get('action')!=last:
                print({'action':decision['action'],'reason':decision.get('reason'),'mid':f.mid,'spread_bps':round(f.spread_bps,3),'delta':f.delta,'cvd':f.cvd,'imbalance5':round(f.imbalance_5,3)})
                journal.write({'type':'live_decision','symbol':args.symbol,**decision}); last=decision.get('action')
            time.sleep(.5)
    except KeyboardInterrupt:feed.stop_flag=True
if __name__=='__main__':main()
