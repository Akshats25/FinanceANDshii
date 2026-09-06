"""
Minimal Black-Scholes pricer, no external dependency beyond stdlib math.

This is a FALLBACK for exercising the pipeline before you have real
historical option-chain premiums. It assumes flat implied vol, no skew,
and European-style cash settlement (a reasonable simplification for
intraday NIFTY/BANKNIFTY index options). Real historical premiums will
differ -- sometimes a lot, especially around events or in the closing
hour. Treat backtest results built on this pricer as a check on your
SIGNAL LOGIC (does the entry/exit rule behave sensibly?), not as a
forecast of real tradeable P&L. Replace with actual chain data as soon
as you can; see the README's "Point-in-time data" / "Data quality" notes.
"""
import math


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    vol: float,
    rate: float,
    option_type: str,
) -> float:
    """option_type: 'CE' for call, 'PE' for put."""
    if time_to_expiry_years <= 0 or vol <= 0:
        if option_type == "CE":
            return max(spot - strike, 0.0)
        return max(strike - spot, 0.0)

    sqrt_t = math.sqrt(time_to_expiry_years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol ** 2) * time_to_expiry_years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t

    if option_type == "CE":
        price = spot * _norm_cdf(d1) - strike * math.exp(-rate * time_to_expiry_years) * _norm_cdf(d2)
    else:
        price = strike * math.exp(-rate * time_to_expiry_years) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)

    return max(price, 0.0)
