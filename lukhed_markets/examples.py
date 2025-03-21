from lukhed_markets.kalshi import Kalshi

def kalshi_setup():
    kalshi = Kalshi(kalshi_setup=True)

def test_kalshi():
    kalshi = Kalshi()
    available_markets = kalshi.get_markets()
    balance = kalshi.get_account_balance()
    stop = 1