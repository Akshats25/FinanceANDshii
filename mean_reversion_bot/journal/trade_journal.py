"""
Append-only trade/signal journal. This is the minimal substitute for a
full event-sourcing system: every signal and fill gets written here,
timestamped, so you can reconstruct exactly what happened and why --
this is what you'll use every day during paper trading to compare
actual behaviour against backtest expectation.
"""
import csv
import os
from dataclasses import dataclass, asdict


JOURNAL_PATH = "trade_journal.csv"


@dataclass
class JournalEntry:
    timestamp: str
    event_type: str          # "signal" | "entry" | "exit" | "error" | "kill_switch"
    direction: str
    strike: float
    premium: float
    quantity: int
    reason: str
    mode: str                # "backtest" | "paper" | "live"


def log_event(entry: JournalEntry, path: str = JOURNAL_PATH) -> None:
    file_exists = os.path.isfile(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(entry).keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(asdict(entry))
