"""
Angel One SmartAPI adapter.

Wraps the official `smartapi-python` SDK behind the BrokerAdapter interface.
Install with: pip install smartapi-python pyotp logzero

Method names below were checked against the official SDK source
(github.com/angel-one/smartapi-python) as of Sept 2026. SDKs change --
if a call here 404s or throws AttributeError, check that repo's
README/test file before assuming the strategy logic is broken.

One-time setup before this will work against a real account:
  1. Create an app at https://smartapi.angelone.in and note the API key.
  2. Enable TOTP-based login and save the base32 secret shown during the
     QR setup -- that value goes in config.ANGEL_TOTP_SECRET. Do NOT save
     the 6-digit code itself, it expires in seconds; pyotp regenerates it
     from the secret on every call.
  3. Register your static IP (or VPS IP) in the SmartAPI developer
     console. This is mandatory under SEBI's 2026 retail algo framework,
     not optional -- API calls from non-whitelisted IPs get blocked.
  4. The instrument/scrip master below resolves tradingsymbol -> token.
     The URL is the commonly documented one at time of writing; if it
     404s, search "Angel One OpenAPIScripMaster" for the current link.
"""

import pyotp
import pandas as pd
import requests

from broker.base_adapter import BrokerAdapter, OrderResult

try:
    from SmartApi import SmartConnect
except ImportError as e:
    raise ImportError(
        "smartapi-python is not installed. Run: pip install smartapi-python pyotp logzero"
    ) from e


SCRIP_MASTER_URL = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"


class AngelOneAdapter(BrokerAdapter):
    def __init__(self, api_key: str, client_code: str, password_or_pin: str, totp_secret: str):
        self.api_key = api_key
        self.client_code = client_code
        self.password_or_pin = password_or_pin
        self.totp_secret = totp_secret
        self.session = None
        self.feed_token = None
        self._scrip_master_cache = None

    def connect(self) -> None:
        self.session = SmartConnect(api_key=self.api_key)
        totp = pyotp.TOTP(self.totp_secret).now()
        data = self.session.generateSession(self.client_code, self.password_or_pin, totp)
        if not data.get("status", False):
            raise RuntimeError(f"Angel One login failed: {data}")
        self.feed_token = self.session.getfeedToken()

    def load_scrip_master(self) -> pd.DataFrame:
        """Download and cache the instrument master (symbol -> token lookup)."""
        if self._scrip_master_cache is None:
            resp = requests.get(SCRIP_MASTER_URL, timeout=30)
            resp.raise_for_status()
            self._scrip_master_cache = pd.DataFrame(resp.json())
        return self._scrip_master_cache

    def resolve_option_token(
        self, underlying: str, expiry: str, strike: float, option_type: str, exchange: str = "NFO"
    ) -> dict:
        """
        Find the symboltoken + exact tradingsymbol for an option contract.
        `expiry` must match the scrip master's own date format -- print
        a few rows of load_scrip_master() the first time you run this,
        the format has drifted across feed versions before.
        """
        df = self.load_scrip_master()
        matches = df[
            (df["name"] == underlying)
            & (df["exch_seg"] == exchange)
            & (df["strike"].astype(float) == float(strike) * 100)  # Angel stores strike * 100
            & (df["symbol"].str.endswith("CE" if option_type == "CE" else "PE"))
            & (df["expiry"] == expiry)
        ]
        if matches.empty:
            raise ValueError(f"No contract found for {underlying} {expiry} {strike}{option_type}")
        row = matches.iloc[0]
        return {"tradingsymbol": row["symbol"], "symboltoken": row["token"]}

    def get_historical_candles(
        self, symbol_token: str, exchange: str, interval: str, from_date: str, to_date: str
    ) -> pd.DataFrame:
        params = {
            "exchange": exchange,
            "symboltoken": symbol_token,
            "interval": interval,
            "fromdate": from_date,
            "todate": to_date,
        }
        result = self.session.getCandleData(params)
        if not result.get("status", False):
            raise RuntimeError(f"Historical data fetch failed: {result}")
        df = pd.DataFrame(result["data"], columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df

    def get_ltp(self, exchange: str, tradingsymbol: str, symbol_token: str) -> float:
        result = self.session.ltpData(exchange, tradingsymbol, symbol_token)
        return float(result["data"]["ltp"])

    def place_order(
        self,
        tradingsymbol: str,
        symbol_token: str,
        exchange: str,
        transaction_type: str,
        quantity: int,
        order_type: str = "MARKET",
        product_type: str = "INTRADAY",
        price: float = 0.0,
    ) -> OrderResult:
        order_params = {
            "variety": "NORMAL",
            "tradingsymbol": tradingsymbol,
            "symboltoken": symbol_token,
            "transactiontype": transaction_type,
            "exchange": exchange,
            "ordertype": order_type,
            "producttype": product_type,
            "duration": "DAY",
            "price": str(price) if order_type == "LIMIT" else "0",
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(quantity),
        }
        result = self.session.placeOrderFullResponse(order_params)
        order_id = result.get("data", {}).get("orderid", "")
        status = result.get("status", False)
        return OrderResult(order_id=order_id, status="PLACED" if status else "FAILED", raw=result)

    def get_order_status(self, order_id: str) -> dict:
        return self.session.individual_order_details(order_id)

    def get_positions(self) -> pd.DataFrame:
        result = self.session.position()
        data = result.get("data") or []
        return pd.DataFrame(data)

    def disconnect(self) -> None:
        if self.session:
            self.session.terminateSession(self.client_code)
