"""
NFL odds from Polymarket, sportsbook style.

Example
-------
from lukhed_markets.polymarket_nfl import PolymarketNFL

nfl = PolymarketNFL()
week = nfl.get_current_week()
board = nfl.get_week_odds(week)                 # moneyline, spread and total for every game this week
chiefs = nfl.get_games(team='KC', week=week)[0]
nfl.get_odds(chiefs, markets='all', periods='all', lines='all')   # every line, every period
nfl.get_props(chiefs, prop_types='passing_yards')
nfl.get_super_bowl_odds()
"""
from .polymarket_sportsbook import PolymarketSportsbook, GAME_LINES

# Prop market types Polymarket lists in NFL player-props events
NFL_PROP_TYPES = (
    'passing_yards', 'passing_touchdowns', 'passing_attempts', 'passing_completions', 'rushing_yards',
    'receiving_yards', 'receptions', 'longest_reception', 'anytime_touchdowns', 'two_plus_touchdowns',
    'team_first_touchdowns', 'first_touchdowns',
)


class PolymarketNFL(PolymarketSportsbook):
    """
    Sportsbook-style NFL odds from Polymarket. Adds weeks, team lookup by abbreviation, and the main
    NFL futures on top of PolymarketSportsbook.

    Parameters
    ----------
    client : Polymarket, optional
        Client to use for requests, by default a new Polymarket client.
    include_fees : bool, optional
        Whether odds include Polymarket's taker fee, by default True.
    """
    PROP_TYPES = NFL_PROP_TYPES

    def __init__(self, client=None, include_fees=True):
        super().__init__('nfl', client=client, include_fees=include_fees)

    def get_games(self, week=None, team=None, status=None, start_after=None, start_before=None,
                  include_closed=False):
        """
        Gets NFL games, sorted by kickoff.

        Parameters
        ----------
        week : int, optional
            Only games in this week of the season
        team : str, optional
            Only games involving this team: abbreviation ('KC'), nickname ('Chiefs') or full name
        status : str or list, optional
            'scheduled', 'live' and/or 'final', by default all
        start_after, start_before : datetime, optional
            Only games kicking off in this window
        include_closed : bool, optional
            Also include games whose markets are all resolved, by default False
        """
        games = super().get_games(team=team, status=status, start_after=start_after, start_before=start_before,
                                  include_closed=include_closed)
        if week is not None:
            games = [g for g in games if g['week'] is not None and int(g['week']) == int(week)]
        return games

    def get_current_week(self):
        """The week of the earliest game that hasn't finished, or None if there are none."""
        upcoming = [g for g in self.get_games(status=('scheduled', 'live')) if g['week'] is not None]
        return min(int(g['week']) for g in upcoming) if upcoming else None

    def get_week_odds(self, week=None, markets=GAME_LINES, periods=('game',), lines='main', live=True):
        """
        Odds board for a week: every game's main lines (by default moneyline, spread and total).

        Parameters
        ----------
        week : int, optional
            The week, by default the current week
        markets, periods, lines, live :
            As in get_odds()
        """
        week = self.get_current_week() if week is None else week
        if week is None:
            return []
        events = [e for e in self.get_game_events()
                  if e.get('eventWeek') is not None and int(e['eventWeek']) == int(week)]
        return self.get_odds_board(events, markets=markets, periods=periods, lines=lines, live=live)

    def get_super_bowl_odds(self, live=True):
        """Odds for each team to win the championship (Polymarket's 'Pro Football: <year> Champion')."""
        return self._future_by_title(('champion',), live)

    def get_mvp_odds(self, live=True):
        """Odds for each player to win MVP."""
        return self._future_by_title(('mvp',), live)

    def _future_by_title(self, keywords, live):
        futures = [f for f in self.get_futures() if all(k in f['title'].lower() for k in keywords)]
        if not futures:
            raise ValueError(f"No open NFL future matching {keywords}")
        return self.get_future_odds(futures[0], live=live)   # get_futures() sorts by volume
