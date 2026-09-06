import os
import sqlite3
import threading
from typing import Dict, List, Optional
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trades.db")
_db_lock = threading.Lock()

def init_db():
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy TEXT NOT NULL,
                instrument TEXT NOT NULL,
                direction TEXT NOT NULL,
                mode TEXT NOT NULL,
                entry REAL NOT NULL,
                stop REAL,
                target REAL,
                exit REAL,
                qty INTEGER NOT NULL,
                pnl REAL,
                status TEXT NOT NULL,
                open_time TEXT NOT NULL,
                close_time TEXT,
                order_id TEXT
            )
        """)
        conn.commit()
        conn.close()

def log_trade(
    strategy: str,
    instrument: str,
    direction: str,
    mode: str,
    entry: float,
    qty: int,
    stop: Optional[float] = None,
    target: Optional[float] = None,
    order_id: Optional[str] = None
) -> int:
    """Insert a new open trade and return its database ID."""
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        open_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("""
            INSERT INTO trades (
                strategy, instrument, direction, mode, entry, stop, target, qty, status, open_time, order_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (strategy, instrument, direction, mode, entry, stop, target, qty, "OPEN", open_time, order_id))
        
        trade_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return trade_id

def close_trade(trade_id: int, exit_price: float):
    """Close a trade by calculating its PnL based on direction and marking status as CLOSED."""
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Get trade details to calculate PnL
        cursor.execute("SELECT entry, qty, direction FROM trades WHERE id = ?", (trade_id,))
        row = cursor.fetchone()
        
        if row:
            entry, qty, direction = row
            if direction in ("LONG", "CE"):
                pnl = (exit_price - entry) * qty
            else:
                pnl = (entry - exit_price) * qty
                
            close_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            cursor.execute("""
                UPDATE trades 
                SET exit = ?, pnl = ?, status = 'CLOSED', close_time = ?
                WHERE id = ?
            """, (round(exit_price, 2), round(pnl, 2), close_time, trade_id))
            conn.commit()
            
        conn.close()

def get_all_trades() -> Dict[str, List[dict]]:
    """Retrieve all trades grouped by OPEN and CLOSED status."""
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM trades ORDER BY open_time DESC")
        rows = cursor.fetchall()
        
        open_trades = []
        closed_trades = []
        
        for row in rows:
            trade = dict(row)
            if trade["status"] == "OPEN":
                open_trades.append(trade)
            else:
                closed_trades.append(trade)
                
        conn.close()
        
    return {
        "open": open_trades,
        "closed": closed_trades
    }

def get_journal_entries() -> List[dict]:
    """Retrieve all trades for the unified journal view."""
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM trades ORDER BY open_time DESC")
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(r) for r in rows]

# Initialize DB when imported
init_db()
