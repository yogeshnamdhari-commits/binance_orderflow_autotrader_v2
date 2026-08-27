from dataclasses import dataclass
@dataclass
class MicroEvent:
    name:str; direction:str; strength:float; evidence:dict
class EventDetector:
    def detect(self,f):
        out=[]
        if f.delta>0 and f.imbalance_5>.20: out.append(MicroEvent('BUY_FLOW','BUY',min(1,.5+f.imbalance_5),{'delta':f.delta}))
        if f.delta<0 and f.imbalance_5<-.20: out.append(MicroEvent('SELL_FLOW','SELL',min(1,.5+abs(f.imbalance_5)),{'delta':f.delta}))
        if f.imbalance_20>.35 and f.delta<0: out.append(MicroEvent('POTENTIAL_ABSORPTION','BUY',.6,{'imbalance20':f.imbalance_20}))
        if f.imbalance_20<-.35 and f.delta>0: out.append(MicroEvent('POTENTIAL_ABSORPTION','SELL',.6,{'imbalance20':f.imbalance_20}))
        return out
