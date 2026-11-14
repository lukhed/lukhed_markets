"""Offline tests for the sportsbook layer. A fake client stands in for Polymarket."""
import json

import pytest

from lukhed_markets.polymarket import Polymarket
from lukhed_markets.polymarket_nfl import PolymarketNFL
from lukhed_markets.polymarket_sportsbook import (
    american_to_price, effective_price, odds_to_rows, price_to_american, price_to_decimal, quote,
    split_market_type,
)
from tests.test_polymarket import FakeResponse, FakeSession

TEAMS = [
    {'id': 1, 'name': 'Denver Broncos', 'abbreviation': 'den', 'alias': 'Broncos', 'ordering': 'away'},
    {'id': 2, 'name': 'Carolina Panthers', 'abbreviation': 'car', 'alias': 'Panthers', 'ordering': 'home'},
]
NFL_FEES = {'feesEnabled': True, 'feeSchedule': {'rate': 0.03, 'takerOnly': True}}


def market(market_type, outcomes, tokens, line=None, question='', title=None, bid=None, ask=None, featured=False,
           closed=False, **extra):
    return {
        'id': tokens[0], 'conditionId': 'c' + tokens[0], 'sportsMarketType': market_type, 'question': question,
        'groupItemTitle': title, 'line': line, 'outcomes': json.dumps(outcomes), 'clobTokenIds': json.dumps(tokens),
        'bestBid': bid, 'bestAsk': ask, 'clobRewards': [{'id': 'r'}] if featured else None,
        'acceptingOrders': not closed, 'closed': closed, **NFL_FEES, **extra,
    }


def game_event(markets, slug='nfl-den-car-2026-11-08', game_id=19577, live=False, score=None, week=9):
    return {
        'id': '500', 'slug': slug, 'gameId': game_id, 'title': 'Broncos vs. Panthers', 'eventWeek': week,
        'startTime': '2026-11-08T18:00:00Z', 'teams': TEAMS, 'live': live, 'ended': False, 'closed': False,
        'score': score, 'markets': markets,
    }


class FakePolymarket:
    """Implements the slice of Polymarket the sportsbook uses."""
    def __init__(self, events=(), prices=None, by_slug=None):
        self.events = list(events)
        self.prices = prices or {}
        self.by_slug = by_slug or {}
        self.price_calls = []

    def get_sports(self):
        return [{'sport': 'nfl', 'series': '12185', 'primaryTagId': 450, 'ordering': 'away'}]

    def get_teams(self, league=None):
        return TEAMS + [{'id': 3, 'name': 'Kansas City Chiefs', 'abbreviation': 'kc', 'alias': 'Chiefs'}]

    def get_events(self, series_id=None, tag=None, **kwargs):
        return list(self.events)

    def get_event_by_slug(self, slug):
        return self.by_slug.get(slug) or next((e for e in self.events if e['slug'] == slug), None)

    def get_event_by_id(self, event_id):
        return next((e for e in self.events if e['id'] == event_id), None)

    def get_prices(self, token_ids):
        self.price_calls.append(list(token_ids))
        return {t: self.prices.get(t, {'bid': None, 'ask': None}) for t in token_ids}


###############################
# Odds math
###############################
def test_price_conversions():
    assert price_to_american(0.6) == -150
    assert price_to_american(0.4) == 150
    assert price_to_american(0.5) == -100
    assert price_to_decimal(0.25) == 4
    assert price_to_american(1.0) is None and price_to_decimal(0) is None
    assert american_to_price(-150) == pytest.approx(0.6)
    assert american_to_price(150) == pytest.approx(0.4)


def test_fee_adjusted_quote():
    # fee = rate * p * (1 - p): at 50c with a 3% rate, the all-in cost is 50.75c per $1 payout
    assert effective_price(0.5, 0.03) == pytest.approx(0.5075)
    q = quote(0.5, 0.03)
    assert q['american'] == price_to_american(0.5075)
    assert quote(0.5)['american'] == -100


def test_split_market_type():
    assert split_market_type('first_half_spreads') == ('spreads', '1H')
    assert split_market_type('q3_both_teams_to_score_points') == ('both_teams_to_score_points', '3Q')
    assert split_market_type('team_totals') == ('team_totals', 'game')


###############################
# Prices from the order book
###############################
def test_get_prices_maps_clob_sides_to_bid_and_ask():
    # The CLOB reports BUY = best bid and SELL = best ask
    session = FakeSession([FakeResponse(200, {'t1': {'BUY': '0.41', 'SELL': '0.42'}})])
    session.post = lambda url, params=None, json=None, timeout=None: session.get(url, params)
    prices = Polymarket(api_delay=0, session=session).get_prices(['t1'])
    assert prices == {'t1': {'bid': 0.41, 'ask': 0.42}}


def test_clob_batches_are_chunked():
    sizes = []

    def post(url, params=None, json=None, timeout=None):
        sizes.append(len(json))
        return FakeResponse(200, {})

    session = FakeSession()
    session.post = post
    Polymarket(api_delay=0, session=session).get_prices([str(i) for i in range(600)])  # 1200 entries
    assert sizes == [500, 500, 200]


###############################
# Games
###############################
def test_games_skip_companion_events_and_parse_teams():
    main = game_event([], live=True, score='21-10')
    first_td = dict(game_event([], slug='nfl-den-car-2026-11-08-first-td-scorer'))
    props = dict(game_event([], slug='nfl-den-car-2026-11-08-player-props', game_id=None))
    nfl = PolymarketNFL(client=FakePolymarket([main, first_td, props]))
    games = nfl.get_games()
    assert [g['slug'] for g in games] == ['nfl-den-car-2026-11-08']
    game = games[0]
    assert game['away_team']['abbreviation'] == 'den' and game['home_team']['abbreviation'] == 'car'
    assert game['status'] == 'live'
    assert game['score'] == {'away': 21, 'home': 10, 'raw': '21-10'}
    assert nfl.get_games(team='KC') == []
    assert len(nfl.get_games(team='Panthers', week=9)) == 1
    assert nfl.get_games(week=10) == []
    with pytest.raises(ValueError):
        nfl.get_games(team='not a team')


###############################
# Odds
###############################
def spread_markets():
    return [
        market('moneyline', ['Broncos', 'Panthers'], ['m1', 'm2'], question='Broncos vs. Panthers', featured=True),
        # The featured line, a liquid line closer to even, and a dead 1c/99c line with a 50c midpoint
        market('spreads', ['Broncos', 'Panthers'], ['s1', 's2'], line=-3.5, question='Spread: Broncos (-3.5)',
               featured=True),
        market('spreads', ['Broncos', 'Panthers'], ['s3', 's4'], line=-2.5, question='Spread: Broncos (-2.5)'),
        market('spreads', ['Panthers', 'Broncos'], ['s5', 's6'], line=-10.5, question='Spread: Panthers (-10.5)'),
        market('q1_spreads', ['Broncos', 'Panthers'], ['q1', 'q2'], line=-0.5, question='1Q Spread: Broncos (-0.5)',
               closed=True),
    ]


PRICES = {
    'm1': {'bid': 0.58, 'ask': 0.59}, 'm2': {'bid': 0.41, 'ask': 0.42},
    's1': {'bid': 0.44, 'ask': 0.45}, 's2': {'bid': 0.55, 'ask': 0.56},
    's3': {'bid': 0.50, 'ask': 0.51}, 's4': {'bid': 0.49, 'ask': 0.50},
    's5': {'bid': 0.01, 'ask': 0.99}, 's6': {'bid': 0.01, 'ask': 0.99},
}


def test_odds_pick_featured_liquid_main_line_before_the_game():
    fake = FakePolymarket([game_event(spread_markets())], prices=PRICES)
    odds = PolymarketNFL(client=fake).get_odds('nfl-den-car-2026-11-08')
    keys = [(m['key'], m['line']) for m in odds['markets']]
    assert keys == [('moneyline', None), ('spreads', -3.5)]
    ml = odds['markets'][0]
    assert ml['outcomes'][0]['ask'] == 0.59
    assert ml['outcomes'][0]['odds'] == quote(0.59, 0.03)
    assert ml['hold'] == pytest.approx(effective_price(0.59, 0.03) + effective_price(0.42, 0.03) - 1, abs=1e-4)
    assert len(fake.price_calls) == 1  # one batched price request per call


def test_odds_in_play_ignore_stale_featured_line_and_dead_books():
    fake = FakePolymarket([game_event(spread_markets(), live=True, score='7-0')], prices=PRICES)
    odds = PolymarketNFL(client=fake).get_odds('nfl-den-car-2026-11-08', markets='spreads')
    assert [m['line'] for m in odds['markets']] == [-2.5]  # closest to even among liquid lines, not 1c/99c


def test_alt_lines_and_spread_points_follow_the_named_team():
    fake = FakePolymarket([game_event(spread_markets())], prices=PRICES)
    alts = PolymarketNFL(client=fake).get_odds('nfl-den-car-2026-11-08', markets='spreads', lines='alt')['markets']
    by_line = {m['line']: m for m in alts}
    assert set(by_line) == {-2.5, -10.5}
    panthers_fav = by_line[-10.5]
    assert [(o['name'], o['point']) for o in panthers_fav['outcomes']] == [('Panthers', -10.5), ('Broncos', 10.5)]
    assert panthers_fav['liquid'] is False and by_line[-2.5]['liquid'] is True


def test_closed_markets_and_periods():
    fake = FakePolymarket([game_event(spread_markets())], prices=PRICES)
    nfl = PolymarketNFL(client=fake)
    assert nfl.get_odds('nfl-den-car-2026-11-08', periods='1Q')['markets'] == []
    closed = nfl.get_odds('nfl-den-car-2026-11-08', periods='1Q', include_closed_markets=True)['markets']
    assert [(m['key'], m['period'], m['accepting_bets']) for m in closed] == [('spreads', '1Q', False)]


def test_cached_prices_invert_for_second_outcome():
    markets = [market('moneyline', ['Broncos', 'Panthers'], ['m1', 'm2'], bid=0.58, ask=0.6)]
    odds = PolymarketNFL(client=FakePolymarket([game_event(markets)])).get_odds('nfl-den-car-2026-11-08', live=False)
    first, second = odds['markets'][0]['outcomes']
    assert (first['bid'], first['ask']) == (0.58, 0.6)
    assert (second['bid'], second['ask']) == pytest.approx((0.4, 0.42))


def test_board_prices_all_games_in_one_batch():
    e1 = game_event(spread_markets())
    e2 = game_event(spread_markets(), slug='nfl-den-car-2026-11-15', game_id=19600, week=10)
    fake = FakePolymarket([e1, e2], prices=PRICES)
    board = PolymarketNFL(client=fake).get_odds_board()
    assert len(board) == 2 and len(fake.price_calls) == 1
    assert len(odds_to_rows(board)) == 8  # 2 games x (moneyline + main spread) x 2 outcomes
    week10 = PolymarketNFL(client=FakePolymarket([e1, e2], prices=PRICES)).get_week_odds(10)
    assert [g['slug'] for g in week10] == ['nfl-den-car-2026-11-15']


###############################
# Props and futures
###############################
def test_props_merge_companion_events_and_filter_players():
    props_event = {'slug': 'nfl-den-car-2026-11-08-player-props', 'markets': [
        market('passing_yards', ['Over', 'Under'], ['p1', 'p2'], line=199.5, title='Bo Nix: Passing Yards O/U 199.5'),
        market('passing_yards', ['Over', 'Under'], ['p3', 'p4'], line=249.5, title='Bo Nix: Passing Yards O/U 249.5'),
        market('receptions', ['Over', 'Under'], ['p5', 'p6'], line=4.5, title='Courtland Sutton: Receptions O/U 4.5'),
    ]}
    first_td = {'slug': 'nfl-den-car-2026-11-08-first-td-scorer', 'markets': [
        market('first_touchdowns', ['Yes', 'No'], ['f1', 'f2'], title='Bo Nix'),
    ]}
    prices = {'p1': {'bid': 0.5, 'ask': 0.51}, 'p2': {'bid': 0.49, 'ask': 0.5},
              'p3': {'bid': 0.2, 'ask': 0.22}, 'p4': {'bid': 0.78, 'ask': 0.8}}
    fake = FakePolymarket([game_event([])], prices=prices,
                          by_slug={props_event['slug']: props_event, first_td['slug']: first_td})
    props = PolymarketNFL(client=fake).get_props('nfl-den-car-2026-11-08', players='bo nix')['props']
    assert [(p['player'], p['key'], p['line']) for p in props] == [
        ('Bo Nix', 'first_touchdowns', None), ('Bo Nix', 'passing_yards', 199.5)]


def test_futures_and_future_odds():
    future = {'id': '900', 'slug': 'pro-football-2027-champion', 'title': 'Pro Football: 2027 Champion',
              'volume': '1000', 'markets': [
                  market('', ['Yes', 'No'], ['y1', 'n1'], title='Kansas City Chiefs'),
                  market('', ['Yes', 'No'], ['y2', 'n2'], title='Carolina Panthers'),
              ]}
    fake = FakePolymarket([future, game_event([])], prices={'y1': {'bid': 0.19, 'ask': 0.2},
                                                             'y2': {'bid': 0.02, 'ask': 0.03}})
    nfl = PolymarketNFL(client=fake)
    assert [f['slug'] for f in nfl.get_futures()] == ['pro-football-2027-champion']
    odds = nfl.get_super_bowl_odds()
    assert [s['name'] for s in odds['selections']] == ['Kansas City Chiefs', 'Carolina Panthers']
    assert odds['selections'][0]['odds']['american'] == price_to_american(effective_price(0.2, 0.03))


###############################
# Player props
###############################
from lukhed_markets.polymarket_sportsbook import _implied_median, _match_names, _name_key, build_prop_ladders  # noqa: E402


def props_fixture():
    game = game_event([])
    props = {'slug': 'nfl-den-car-2026-11-08-player-props', 'markets': [
        market('passing_yards', ['Over', 'Under'], ['y1', 'y1n'], line=174.5, title='Bo Nix: Passing Yards O/U 174.5'),
        market('passing_yards', ['Over', 'Under'], ['y2', 'y2n'], line=199.5, title='Bo Nix: Passing Yards O/U 199.5'),
        market('passing_yards', ['Over', 'Under'], ['y3', 'y3n'], line=224.5, title='Bo Nix: Passing Yards O/U 224.5'),
        market('passing_yards', ['Over', 'Under'], ['y4', 'y4n'], line=249.5, title='Bo Nix: Passing Yards O/U 249.5'),
        market('team_first_touchdowns', ['Yes', 'No'], ['t1', 't1n'], title='Bo Nix: Team First TD (Denver Broncos)'),
        market('receptions', ['Over', 'Under'], ['r1', 'r1n'], line=3.5, title='Tetairoa McMillan: Receptions O/U 3.5'),
        market('team_first_touchdowns', ['Yes', 'No'], ['t2', 't2n'],
               title='Tetairoa McMillan: Team First TD (Carolina Panthers)'),
        market('receptions', ['Over', 'Under'], ['r2', 'r2n'], line=2.5, title='Amon-Ra St. Brown Jr.: Receptions O/U 2.5'),
    ]}
    prices = {
        'y1': {'bid': 0.80, 'ask': 0.82},   # P(over 174.5) ~ 81%
        'y2': {'bid': 0.01, 'ask': 0.99},   # dead book: must not count as 50%
        'y3': {'bid': 0.40, 'ask': 0.42},   # P(over 224.5) ~ 41%
        'y4': {'bid': 0.01, 'ask': 0.30},   # dust bid: thin
        'r1': {'bid': 0.55, 'ask': 0.57},
    }
    return FakePolymarket([game, props], prices=prices)


def test_name_matching():
    names = ['Patrick Mahomes', 'Josh Allen', 'Keenan Allen', 'Amon-Ra St. Brown Jr.']
    assert _name_key('Amon-Ra St. Brown Jr.') == 'amon ra st brown'
    assert _match_names('mahomes', names) == ['Patrick Mahomes']
    assert _match_names('pat mahomes', names) == ['Patrick Mahomes']
    assert _match_names('amon-ra st brown', names) == ['Amon-Ra St. Brown Jr.']
    assert _match_names('Allen', names) == ['Josh Allen', 'Keenan Allen']
    assert _match_names('Josh Allen', names) == ['Josh Allen']


def test_players_listing_with_teams():
    nfl = PolymarketNFL(client=props_fixture())
    players = nfl.get_players()
    by_name = {p['player']: p for p in players}
    assert by_name['Bo Nix']['team'] == 'Broncos' and by_name['Bo Nix']['opponent'] == 'Panthers'
    assert by_name['Tetairoa McMillan']['team'] == 'Panthers'
    assert by_name['Amon-Ra St. Brown Jr.']['team'] is None  # no Team First TD market to read it from
    assert by_name['Bo Nix']['prop_types'] == ['passing_yards', 'team_first_touchdowns']
    assert [p['player'] for p in nfl.get_players(team='CAR')] == ['Tetairoa McMillan']
    assert nfl.get_players(week=10) == []


def test_player_props_ladder_main_line_and_median():
    fake = props_fixture()
    page = PolymarketNFL(client=fake).get_player_props('nix')
    assert (page['player'], page['team'], page['opponent']) == ('Bo Nix', 'Broncos', 'Panthers')
    yards = next(p for p in page['props'] if p['type'] == 'passing_yards')
    assert [r['line'] for r in yards['lines']] == [174.5, 199.5, 224.5, 249.5]
    assert [r['liquid'] for r in yards['lines']] == [True, False, True, False]
    assert yards['lines'][1]['probability'] is None  # 1c/99c book is not a 50% line
    assert yards['main_line'] == 224.5               # liquid line closest to even
    # Interpolate between 174.5 (81%) and 224.5 (41%): 50% at 174.5 + 31/40 * 50
    assert yards['implied_median'] == pytest.approx(213.25)
    # Only Bo Nix's markets were priced, one token per binary market
    assert sorted(fake.price_calls[-1]) == ['t1', 'y1', 'y2', 'y3', 'y4']


def test_player_props_errors_on_unknown_or_ambiguous_names():
    nfl = PolymarketNFL(client=props_fixture())
    with pytest.raises(ValueError, match='No player props'):
        nfl.get_player_props('Mahomes')
    with pytest.raises(ValueError, match='several players'):
        nfl.get_player_props('b')  # Bo Nix and Amon-Ra St. Brown


def test_props_board_filters_and_labels_teams():
    nfl = PolymarketNFL(client=props_fixture())
    board = nfl.get_props_board(prop_types='receptions')
    props = board[0]['props']
    assert [(p['player'], p['team'], p['line']) for p in props] == [
        ('Amon-Ra St. Brown Jr.', None, 2.5), ('Tetairoa McMillan', 'Panthers', 3.5)]
    only = nfl.get_props_board(players='mcmillan')[0]['props']
    assert {p['player'] for p in only} == {'Tetairoa McMillan'}
    assert nfl.get_props_board(team='DEN', prop_types='receptions') == []


def test_implied_median_needs_both_sides_of_fifty():
    rung = lambda line, p: {'line': line, 'probability': p, 'liquid': True}
    assert _implied_median([rung(1.5, 0.7), rung(2.5, 0.3)]) == 2.0
    assert _implied_median([rung(1.5, 0.7), rung(2.5, 0.6)]) is None
    assert _implied_median([rung(1.5, 0.5)]) == 1.5


def test_mirrored_pricing_for_second_outcome():
    fake = props_fixture()
    board = PolymarketNFL(client=fake).get_props_board(players='McMillan', prop_types='receptions')
    over, under = board[0]['props'][0]['outcomes']
    assert (over['bid'], over['ask']) == (0.55, 0.57)
    assert (under['bid'], under['ask']) == pytest.approx((0.43, 0.45))
    assert 'r1n' not in fake.price_calls[-1]
