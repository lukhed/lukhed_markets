from lukhed_markets.kalshi import Kalshi

def kalshi_setup():
    kalshi = Kalshi(kalshi_setup=True)

def test_kalshi():
    kalshi = Kalshi()
    available_markets = kalshi.get_markets()
    balance = kalshi.get_account_balance()
    stop = 1

def get_all_available_kalshi_events():
    kalshi = Kalshi()
    events = kalshi.get_all_available_events()
    stop = 1