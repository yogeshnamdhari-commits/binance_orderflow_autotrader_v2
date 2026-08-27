from dataclasses import dataclass
@dataclass
class Signal: action:str; score:float; reason:str; features:dict
class SignalEngine:
    def decide(self,f,events):
        if not events or f.spread_bps<=0: return Signal('NO_TRADE',0,'insufficient evidence',vars(f))
        buy=sum(e.strength for e in events if e.direction=='BUY'); sell=sum(e.strength for e in events if e.direction=='SELL')
        if buy>sell and buy>=.9: return Signal('BUY',min(1,buy/2),'order-flow alignment',vars(f))
        if sell>buy and sell>=.9: return Signal('SELL',min(1,sell/2),'order-flow alignment',vars(f))
        return Signal('NO_TRADE',0,'conflicting/weak flow',vars(f))
