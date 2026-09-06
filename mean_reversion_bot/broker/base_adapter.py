"""
Broker adapter interface.

Every broker integration (Angel One today, others later) implements this
interface. Strategy, risk, and execution code should NEVER import a
specific broker SDK directly -- only this interface. That is what turns
"add another broker later" into a new adapter file instead of a rewrite.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
import pandas as pd


@dataclass
class OrderResult:
    order_id: str
    status: str
    raw: dict


class BrokerAdapter(ABC):
    @abstractmethod
    def connect(self) -> None:
        """Authenticate and establish a session."""

    @abstractmethod
    def get_historical_candles(
        self,
        symbol_token: str,
        exchange: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> pd.DataFrame:
        """Return a DataFrame with columns: timestamp, open, high, low, close, volume."""

    @abstractmethod
    def get_ltp(self, exchange: str, tradingsymbol: str, symbol_token: str) -> float:
        """Return the last traded price."""

    @abstractmethod
    def place_order(
        self,
        tradingsymbol: str,
        symbol_token: str,
        exchange: str,
        transaction_type: str,   # "BUY" | "SELL"
        quantity: int,
        order_type: str = "MARKET",
        product_type: str = "INTRADAY",
        price: float = 0.0,
    ) -> OrderResult:
        """Place an order and return the result."""

    @abstractmethod
    def get_order_status(self, order_id: str) -> dict:
        """Poll order status / fill details."""

    @abstractmethod
    def get_positions(self) -> pd.DataFrame:
        """Return current open positions."""

    @abstractmethod
    def disconnect(self) -> None:
        """Cleanly end the session."""
