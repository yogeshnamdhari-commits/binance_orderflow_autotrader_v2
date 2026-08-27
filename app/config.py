from dataclasses import dataclass
import os
from dotenv import load_dotenv
load_dotenv()

# Governance: ORDERFLOW_BASELINE_V5 is locked to NO LIVE TRADING until
# contemporaneous execution cost (Q2) is measured and the economic gate passes.
# This constant is NOT read from env; it is a deliberate code-level governance rule.
V5_BASELINE_NO_LIVE_TRADE = True

@dataclass(frozen=True)
class Config:
    rest:str=os.getenv('BINANCE_REST','https://fapi.binance.com')
    ws:str=os.getenv('BINANCE_WS','wss://fstream.binance.com/stream')
    ws_public:str=os.getenv('BINANCE_WS_PUBLIC','wss://fstream.binance.com/public')
    ws_market:str=os.getenv('BINANCE_WS_MARKET','wss://fstream.binance.com/market')
    api_key:str=os.getenv('BINANCE_API_KEY','')
    api_secret:str=os.getenv('BINANCE_API_SECRET','')
    mode:str=os.getenv('MODE','paper').lower()
    live_trading_enabled:bool=os.getenv('LIVE_TRADING_ENABLED','false').lower()=='true'
    risk_per_trade:float=float(os.getenv('RISK_PER_TRADE','0.0025'))
    max_daily_loss:float=float(os.getenv('MAX_DAILY_LOSS','0.02'))
    max_spread_bps:float=float(os.getenv('MAX_SPREAD_BPS','5'))
    levels:int=50
    def assert_safe(self):
        if self.mode=='live' and not self.live_trading_enabled: raise RuntimeError('LIVE_TRADING_ENABLED=false')
        if not 0 < self.risk_per_trade <= .02: raise ValueError('risk_per_trade out of bounds')
        if not 0 < self.max_daily_loss <= .20: raise ValueError('max_daily_loss out of bounds')
        if not 1 <= self.levels <= 1000: raise ValueError('levels out of bounds')

    def runtime_safe(self):
        """Live execution must remain blocked while the V5 governance lock is set."""
        if self.mode == 'live' and V5_BASELINE_NO_LIVE_TRADE:
            return False, "ORDERFLOW_BASELINE_V5 NO LIVE TRADING"
        return True, ""
