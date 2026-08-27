"""Componentized Binance USDT-M Futures execution-cost model.

Every component is a variable (bps) and summed to a round-trip cost:

  round_trip = 2 * (fee_per_side + slippage_per_side) + spread_total + impact_total + funding_total

Components:
- fee_per_side: maker vs taker base fee per side, scaled by VIP tier / BNB discount.
- spread_total: cost of crossing the bid/ask spread over the round trip
  (0 if both legs rest in the book; ~half-spread each side for market orders).
- slippage_per_side: realized adverse fill distance beyond the quote.
- impact_total: market impact for the traded notional.
- funding_total: per-holding funding carry (negligible for <=60s holds; usually 0).

Fees below are the current default assumption (2 bps taker / 1 bps maker per side,
VIP0, no discount) — parameterized, NOT a permanent truth.
"""

FEE_BPS = {"maker": 1.0, "taker": 2.0}   # per side, VIP0 assumption


def round_trip_bps(fee_per_side=None, spread_total=0.0, slippage_per_side=0.0,
                   impact_total=0.0, funding_total=0.0):
    fee_per_side = FEE_BPS["taker"] if fee_per_side is None else fee_per_side
    return 2 * (fee_per_side + slippage_per_side) + spread_total + impact_total + funding_total


def fee_scaled(base_per_side, vip_discount_pct=0.0, bnb_discount_pct=0.0):
    """Fee per side after VIP-tier and BNB discount (percent off)."""
    d = 1.0 - (vip_discount_pct + bnb_discount_pct) / 100.0
    return base_per_side * max(d, 0.0)


# Reference scenarios (round-trip bps under conservative assumptions).
SCENARIOS = {
    "maker_passive": round_trip_bps(fee_per_side=FEE_BPS["maker"], spread_total=0.0,
                                    slippage_per_side=0.1, impact_total=0.1, funding_total=0.0),
    "maker_bnb_vip": round_trip_bps(fee_per_side=fee_scaled(FEE_BPS["maker"], 10, 10),
                                    spread_total=0.0, slippage_per_side=0.1,
                                    impact_total=0.1, funding_total=0.0),
    "taker_full": round_trip_bps(fee_per_side=FEE_BPS["taker"], spread_total=1.0,
                                 slippage_per_side=0.5, impact_total=0.5, funding_total=0.0),
    "taker_discounted": round_trip_bps(fee_per_side=fee_scaled(FEE_BPS["taker"], 10, 10),
                                       spread_total=1.0, slippage_per_side=0.5,
                                       impact_total=0.5, funding_total=0.0),
}


def describe():
    return {
        "fee_per_side_bps": FEE_BPS,
        "scenarios_round_trip_bps": {k: round(float(v), 2) for k, v in SCENARIOS.items()},
    }