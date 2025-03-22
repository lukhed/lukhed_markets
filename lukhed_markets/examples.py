from lukhed_markets.kalshi import Kalshi

def kalshi_setup():
    kalshi = Kalshi(kalshi_setup=True)

def test_kalshi():
    kalshi = Kalshi()
    available_markets = kalshi.get_markets()
    balance = kalshi.get_account_balance()
    stop = 1

def march_madness_get_team_odds(round=64, status='open', tourney_year=25):
    """
    Get the odds for all teams in a given round of the March Madness tournament.

    Parameters
    ----------
    round : int, optional
        Rounds are described by kalshi has how many teams are left. Round of 64 is first round games, by default 64.
    status : str, optional
        Status of the market (unopened, open, closed, settled), by default 'open'
    tourney_year : int, optional
        Year of the tourney, by default 25 (2025)

    Returns
    -------
    list
        List of dictionaries with the team, probability, volume, volume_24h, and open_interest.
    """
    kalshi = Kalshi()
    all_events = kalshi.get_all_available_events(series_ticker='KXMARMAD', 
                                                 with_nested_markets=True,
                                                 status=status)
    
    filtered_events = [x for x in all_events if f'-{tourney_year}R{str(round)}G' in x['event_ticker']]
    
    game_odds = []
    for event in filtered_events:
        markets = event['markets']
        for market in markets:
            if market['status'] != 'settled':
                team = market['yes_sub_title']
                probability = market['last_price']
                game_odds.append({'team': team, 
                                'probability': probability,
                                'volume': market['volume'],
                                'volume_24h': market['volume_24h'], 
                                'open_interest': market['open_interest']}
                                )
    return game_odds