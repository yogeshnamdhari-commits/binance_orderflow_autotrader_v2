from dataclasses import dataclass,field
@dataclass
class TradeEvent:
    ts_ms:int; trade_id:int; price:float; qty:float; buyer_is_maker:bool
    @property
    def aggressor_side(self): return 'SELL' if self.buyer_is_maker else 'BUY'
@dataclass
class DepthEvent:
    ts_ms:int; first_update_id:int; final_update_id:int
    bids:list[tuple[float,float]]; asks:list[tuple[float,float]]
@dataclass
class BookState:
    last_update_id:int|None=None; bids:dict=field(default_factory=dict); asks:dict=field(default_factory=dict)
    synchronized:bool=False; last_event_ms:int=0
    def best_bid(self): return max(self.bids) if self.bids else None
    def best_ask(self): return min(self.asks) if self.asks else None
    def best_bid_qty(self):
        b=self.best_bid(); return self.bids.get(b) if b is not None else None
    def best_ask_qty(self):
        a=self.best_ask(); return self.asks.get(a) if a is not None else None
    def mid(self):
        b,a=self.best_bid(),self.best_ask(); return (b+a)/2 if b is not None and a is not None else None
    def spread_bps(self):
        b,a,m=self.best_bid(),self.best_ask(),self.mid(); return (a-b)/m*10000 if m and b is not None and a is not None else None
    def microprice(self):
        """Volume-weighted mid: where resting qty suggests the true touch.

        microprice = (bid*qty_ask + ask*qty_bid) / (qty_bid + qty_ask)
        Reverts toward the side with thinner resting depth; a standard
        order-flow fair-value proxy (Cont-Kukanov-Stoikov)."""
        b,a=self.best_bid(),self.best_ask()
        if b is None or a is None: return None
        qb,qa=self.bids.get(b,0.0),self.asks.get(a,0.0)
        tot=qb+qa
        return (b*qa+a*qb)/tot if tot>0 else None
    def top_bids(self,n): return sorted(self.bids.items(),reverse=True)[:n]
    def top_asks(self,n): return sorted(self.asks.items())[:n]
    def depth_weighted_pressure(self,n=5):
        """Depth-weighted pressure: resting size weighted by proximity to mid.

        Positive = more resting bid size near touch (buy pressure). Uses 1/dist
        weights so nearer levels dominate, matching queue-value intuition."""
        bids=self.top_bids(n); asks=self.top_asks(n)
        mb=bids[0][0] if bids else None; ma=asks[0][0] if asks else None
        mid=(mb+ma)/2 if mb is not None and ma is not None else None
        if mid is None or mid==0: return 0.0
        wbid=sum(q/(abs(p-mid)+1e-9) for p,q in bids)
        wask=sum(q/(abs(p-mid)+1e-9) for p,q in asks)
        tot=wbid+wask
        return (wbid-wask)/tot if tot>0 else 0.0
    def imbalance(self,n=1):
        bids=self.top_bids(n); asks=self.top_asks(n)
        bs=sum(q for _,q in bids); ass=sum(q for _,q in asks)
        den=bs+ass
        return (bs-ass)/den if den else 0.0
    def depth_sum(self,n=5):
        bids=self.top_bids(n); asks=self.top_asks(n)
        return sum(q for _,q in bids), sum(q for _,q in asks)
    def stale(self,now_ms,threshold_ms):
        """True if no book update has arrived within threshold_ms (stale-data guard)."""
        return self.last_event_ms>0 and (now_ms-self.last_event_ms)>threshold_ms
    def integrity_state(self):
        """Map internal sync flag onto the canonical L2 integrity enum value."""
        return "BOOK_VALID" if self.synchronized else "BOOK_INVALID"
