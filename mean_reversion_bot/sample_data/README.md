Synthetic random-walk data for smoke-testing the pipeline only -- NOT
real market data, and NOT a basis for any trading decision. Use it to
confirm the code runs end to end:

    python run_backtest.py sample_data/synthetic_nifty_5min.csv
    python run_backtest_pattern.py sample_data/synthetic_nifty_1min.csv

Replace with real historical data before drawing any conclusions about
the strategies themselves.
