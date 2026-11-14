"""
Sportsbook-style access to Polymarket sports markets.

Polymarket lists each game as an event holding hundreds of binary markets (moneyline, every alternate
spread and total, half/quarter lines, team totals...), with player props in a companion
"<game-slug>-player-props" event. PolymarketSportsbook turns that into what a sportsbook API returns:

- games with home/away teams, start time, status and live score
- markets grouped by type and period, with the main line marked and alternate lines available
- every outcome priced as American and decimal odds from the live order book, including Polymarket's
  taker fee, plus the market's hold (vig)

Prices: the odds for an outcome come from its best ask, the price you would pay to back it right now.
Gamma's market data is cached for up to 5 minutes, so by default prices are refreshed from the order book.

This module is league-agnostic. See polymarket_nfl.PolymarketNFL for NFL-specific helpers.
"""
import json
import logging
import re
import unicodedata
from datetime import datetime, timezone

from .polymarket import Polymarket

logger = logging.getLogger(__name__)

GAME_LINES = ('moneyline', 'spreads', 'totals')
PERIOD_PREFIXES = (('first_half_', '1H'), ('second_half_', '2H'), ('q1_', '1Q'), ('q2_', '2Q'), ('q3_', '3Q'),
                   ('q4_', '4Q'))
PERIOD_ORDER = ('game', '1H', '2H', '1Q', '2Q', '3Q', '4Q')
LINE_FILTERS = ('main', 'alt', 'all')
# Companion events Polymarket creates next to each game event, holding player markets
COMPANION_SUFFIXES = ('-player-props', '-first-td-scorer')

_SPREAD_QUESTION = re.compile(r'Spread:\s*(.+?)\s*\(([-+]?\d+(?:\.\d+)?)\)')


###############################
# Odds math
###############################
def price_to_decimal(price):
    """Polymarket price (0-1, cost of a $1 payout) -> decimal odds. None if the price can't pay out."""
    if price is None or not 0 < price < 1:
        return None
    return round(1 / price, 4)


def price_to_american(price):
    """Polymarket price (0-1) -> American odds, e.g. 0.6 -> -150, 0.4 -> +150. None outside (0, 1)."""
    if price is None or not 0 < price < 1:
        return None
    if price >= 0.5:
        return -round(100 * price / (1 - price))
    return round(100 * (1 - price) / price)


def american_to_price(american):
    """American odds -> implied probability / Polymarket price, e.g. -150 -> 0.6."""
    american = float(american)
    if american < 0:
        return -american / (-american + 100)
    return 100 / (american + 100)


def taker_fee_per_share(price, fee_rate):
    """Polymarket taker fee in dollars per share: fee_rate * p * (1 - p)."""
    if price is None or not fee_rate:
        return 0.0
    return fee_rate * price * (1 - price)


def effective_price(price, fee_rate=0.0):
    """All-in cost per $1 of payout when buying at price as a taker (price plus taker fee)."""
    if price is None:
        return None
    return price + taker_fee_per_share(price, fee_rate)


def quote(price, fee_rate=0.0):
    """Odds for backing an outcome at price, all-in with the taker fee."""
    cost = effective_price(price, fee_rate)
    return {
        'price': price,
        'effective_price': None if cost is None else round(cost, 6),
        'american': price_to_american(cost),
        'decimal': price_to_decimal(cost),
    }


###############################
# Parsing helpers
###############################
def _json_list(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return []
    return list(value or [])


def _float(value):
    try:
        return None if value is None or value == '' else float(value)
    except (TypeError, ValueError):
        return None


def _parse_time(value):
    if not value:
        return None
    text = str(value).strip().replace(' ', 'T', 1)
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    elif re.search(r'[+-]\d\d$', text):
        text += ':00'
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def split_market_type(sports_market_type):
    """'first_half_spreads' -> ('spreads', '1H'); 'moneyline' -> ('moneyline', 'game')."""
    market_type = sports_market_type or 'other'
    for prefix, period in PERIOD_PREFIXES:
        if market_type.startswith(prefix):
            return market_type[len(prefix):], period
    return market_type, 'game'


def _as_tuple(value, all_value=None):
    if value is None or value == 'all':
        return all_value
    if isinstance(value, str):
        return (value,)
    return tuple(value)


class PolymarketSportsbook:
    """
    Sportsbook-style interface to one Polymarket sports league.

    Parameters
    ----------
    league : str
        Polymarket sport code, e.g. 'nfl', 'nba', 'mlb', 'nhl', 'cfb' (see Polymarket().get_sports()).
    client : Polymarket, optional
        Client to use for requests, by default a new Polymarket client.
    include_fees : bool, optional
        Whether odds include Polymarket's taker fee (what you actually pay), by default True.
    """
    def __init__(self, league, client=None, include_fees=True):
        self.league = league.lower()
        self.pm = client or Polymarket()
        self.include_fees = include_fees
        self._league_info = None
        self._teams = None

    ###############################
    # League metadata
    ###############################
    @property
    def league_info(self):
        """The league's Gamma sports metadata (series ids, tags, image...)."""
        if self._league_info is None:
            match = next((s for s in self.pm.get_sports() if str(s.get('sport', '')).lower() == self.league), None)
            if match is None:
                raise ValueError(f"Polymarket has no league '{self.league}' (see Polymarket().get_sports())")
            self._league_info = match
        return self._league_info

    @property
    def series_ids(self):
        return [s.strip() for s in str(self.league_info.get('series') or '').split(',') if s.strip()]

    @property
    def primary_tag_id(self):
        return self.league_info.get('primaryTagId')

    def get_teams(self):
        """The league's teams (name, abbreviation, alias, record, logo)."""
        if self._teams is None:
            self._teams = self.pm.get_teams(league=self.league)
        return self._teams

    def find_team(self, query):
        """Find a team by abbreviation ('kc'), alias ('Chiefs') or full name. Returns the team dict or None."""
        if isinstance(query, dict):
            return query
        text = str(query).strip().lower()
        teams = self.get_teams()
        for field in ('abbreviation', 'alias', 'name'):
            for team in teams:
                if str(team.get(field) or '').lower() == text:
                    return team
        matches = [t for t in teams if text in str(t.get('name') or '').lower()]
        return matches[0] if len(matches) == 1 else None

    ###############################
    # Games
    ###############################
    def get_game_events(self, include_closed=False):
        """
        Raw Gamma events for the league's games (with their markets), one per game. Excludes companion
        player-market events (see get_props) and futures.
        """
        return _games_from(self._series_events(include_closed))

    def _series_events(self, include_closed=False):
        """Every raw event in the league's series: games and their companion events."""
        events = []
        for series_id in self.series_ids:
            events.extend(self.pm.get_events(series_id=series_id, include_closed=include_closed, active_only=False))
        return events

    def get_games(self, team=None, status=None, start_after=None, start_before=None, include_closed=False):
        """
        Gets the league's games, sorted by start time.

        Parameters
        ----------
        team : str, optional
            Only games involving this team (abbreviation, alias or name)
        status : str or list, optional
            'scheduled', 'live' and/or 'final', by default all
        start_after, start_before : datetime, optional
            Only games starting in this window (timezone-aware, or naive meaning UTC)
        include_closed : bool, optional
            Also include games whose markets are all resolved, by default False

        Returns
        -------
        list
            Game dicts: id, slug, game_id, title, start_time, status, away_team, home_team, score,
            period, elapsed, volume, url.
        """
        statuses = _as_tuple(status)
        team_info = self.find_team(team) if team is not None else None
        if team is not None and team_info is None:
            raise ValueError(f"Unknown {self.league.upper()} team: {team}")
        after = _aware(start_after)
        before = _aware(start_before)

        games = []
        for event in self.get_game_events(include_closed=include_closed):
            game = self.summarize_game(event)
            if statuses and game['status'] not in statuses:
                continue
            if team_info and team_info.get('id') not in {(game['away_team'] or {}).get('id'),
                                                         (game['home_team'] or {}).get('id')}:
                continue
            if after and (game['start_time'] is None or game['start_time'] < after):
                continue
            if before and (game['start_time'] is None or game['start_time'] >= before):
                continue
            games.append(game)
        far_future = datetime.max.replace(tzinfo=timezone.utc)
        return sorted(games, key=lambda g: g['start_time'] or far_future)

    def summarize_game(self, event):
        """Normalizes a Gamma game event into a game dict (no markets)."""
        teams = event.get('teams') or []
        away = next((t for t in teams if t.get('ordering') == 'away'), None)
        home = next((t for t in teams if t.get('ordering') == 'home'), None)
        if (away is None or home is None) and len(teams) == 2:
            # Fall back to the title order, which follows the league's ordering (away first by default)
            away, home = teams if self.league_info.get('ordering', 'away') == 'away' else teams[::-1]

        if event.get('ended') or event.get('closed'):
            status = 'final'
        elif event.get('live'):
            status = 'live'
        else:
            status = 'scheduled'

        return {
            'id': event.get('id'),
            'slug': event.get('slug'),
            'game_id': event.get('gameId'),
            'league': self.league,
            'title': event.get('title'),
            'week': event.get('eventWeek'),
            'start_time': _parse_time(event.get('startTime') or event.get('gameStartTime') or event.get('startDate')),
            'status': status,
            'away_team': _team_summary(away),
            'home_team': _team_summary(home),
            'score': _parse_score(event.get('score')),
            'period': event.get('period'),
            'elapsed': event.get('elapsed'),
            'volume': _float(event.get('volume')),
            'url': f"https://polymarket.com/event/{event.get('slug')}",
        }

    def _game_event(self, game):
        """Accepts a game dict, a raw event (with markets), a slug or an event id; returns the raw event."""
        if isinstance(game, dict) and isinstance(game.get('markets'), list):
            return game
        if isinstance(game, dict):
            game = game.get('slug') or game.get('id')
        text = str(game)
        event = self.pm.get_event_by_id(text) if text.isdigit() else self.pm.get_event_by_slug(text)
        if event is None:
            raise ValueError(f"Game not found: {game}")
        return event

    ###############################
    # Odds
    ###############################
    def get_odds(self, game, markets=GAME_LINES, periods=('game',), lines='main', live=True,
                 include_closed_markets=False):
        """
        Gets sportsbook-style odds for one game.

        Parameters
        ----------
        game : dict or str
            A game from get_games(), an event slug or an event id
        markets : str or list, optional
            Market types, e.g. 'moneyline', 'spreads', 'totals', 'team_totals', 'exact_margin', or 'all'.
            By default the main game lines (moneyline, spreads, totals).
        periods : str or list, optional
            'game', '1H', '2H', '1Q'-'4Q', or 'all', by default 'game'
        lines : str, optional
            'main' (the featured line per market), 'alt' (alternate lines only) or 'all', by default 'main'
        live : bool, optional
            Refresh prices from the order book, by default True. If False, uses Gamma's cached prices.
        include_closed_markets : bool, optional
            Include markets that no longer accept bets (e.g. finished quarters), by default False

        Returns
        -------
        dict
            The game dict plus 'markets': a list of markets, each with key, period, line, is_main,
            description, accepting_bets, liquid (two-sided book within 10c; illiquid lines show odds no
            one is really offering), fee_rate, hold, and 'outcomes' with name, point, bid, ask, mid and
            odds (american, decimal, price, effective_price).
        """
        event = self._game_event(game)
        game_info = self.summarize_game(event)
        game_info['markets'] = self._build_markets(event.get('markets', []), markets, periods, lines, live,
                                                   include_closed_markets, teams=event.get('teams') or [],
                                                   in_play=game_info['status'] == 'live')
        return game_info

    def get_odds_board(self, games=None, markets=GAME_LINES, periods=('game',), lines='main', live=True,
                       status=('scheduled', 'live')):
        """
        Gets odds for many games at once, like a sportsbook's main board. Prices for every game are fetched
        in a few batched order book requests.

        Parameters
        ----------
        games : list, optional
            Games from get_games() (or raw events). By default all scheduled and live games.
        markets, periods, lines, live :
            As in get_odds()
        status : str or list, optional
            Game statuses to include when games isn't given, by default scheduled and live

        Returns
        -------
        list
            One get_odds()-style dict per game
        """
        events = self._events_for(games, status)
        board, selected = [], []
        for event in events:
            game_info = self.summarize_game(event)
            game_info['markets'] = self._build_markets(event.get('markets', []), markets, periods, lines,
                                                       live=False, include_closed_markets=False,
                                                       teams=event.get('teams') or [], price=False)
            board.append(game_info)
            selected.extend(game_info['markets'])
        self._price_markets(selected, live)
        for game_info in board:
            self._finalize(game_info['markets'], lines, in_play=game_info['status'] == 'live')
        return board

    def get_props(self, game, players=None, prop_types=None, lines='main', live=True,
                  include_closed_markets=False):
        """
        Gets player props for a game, from its companion player-props and first-TD-scorer events.

        Note: Polymarket settles a prop on an inactive player as Under/No rather than voiding it.

        Parameters
        ----------
        game : dict or str
            A game from get_games(), an event slug or an event id
        players : str or list, optional
            Only these players. Names match loosely: case, accents, punctuation and suffixes like 'Jr.' are
            ignored, and a last name or partial name ('mahomes', 'pat mahomes') matches. By default all.
        prop_types : str or list, optional
            e.g. 'passing_yards', 'receiving_yards', 'anytime_touchdowns', by default all
        lines : str, optional
            'main', 'alt' or 'all', by default 'main'
        live : bool, optional
            Refresh prices from the order book, by default True

        Returns
        -------
        dict
            The game dict plus 'props': markets as in get_odds(), each with 'player' and 'team'. An empty
            list if the game has no props.
        """
        event = self._game_event(game)
        fetched = (self.pm.get_event_by_slug(str(event.get('slug')) + suffix) for suffix in COMPANION_SUFFIXES)
        companions = {event.get('slug'): [c for c in fetched if c]}
        board = self._props_for([event], companions, players=players, prop_types=prop_types, lines=lines,
                                live=live, include_closed_markets=include_closed_markets)
        return board[0]

    ###############################
    # Player props
    ###############################
    def get_props_board(self, games=None, prop_types=None, players=None, teams=None, lines='main', live=True,
                        status=('scheduled', 'live'), game_filter=None, include_closed_markets=False):
        """
        Player props across many games at once, e.g. every main passing-yards line this week. All games are
        priced in a few batched order book requests.

        Parameters
        ----------
        games : list, optional
            Games from get_games() (or slugs). By default every game matching status and game_filter.
        prop_types : str or list, optional
            e.g. 'passing_yards', 'anytime_touchdowns', by default all
        players : str or list, optional
            Only these players (loose name matching, see get_props), by default all
        teams : str or list, optional
            Only players on these teams (abbreviation, nickname or name), by default all
        lines : str, optional
            'main', 'alt' or 'all', by default 'main'
        live : bool, optional
            Refresh prices from the order book, by default True
        status : str or list, optional
            Game statuses to include when games isn't given, by default scheduled and live
        game_filter : callable, optional
            Extra filter on game dicts from get_games(), e.g. lambda g: g['week'] == 9

        Returns
        -------
        list
            One dict per game (as get_props()), including only games that have matching props.
        """
        events, companions = self._props_events(games, status, game_filter)
        board = self._props_for(events, companions, players=players, prop_types=prop_types, teams=teams,
                                lines=lines, live=live, include_closed_markets=include_closed_markets)
        return [game for game in board if game['props']]

    def get_players(self, games=None, teams=None, status=('scheduled', 'live'), game_filter=None):
        """
        Lists players with props, without fetching prices.

        Returns
        -------
        list
            Dicts with player, team, opponent, game (title), slug, start_time and prop_types, sorted by
            kickoff, team and name.
        """
        events, companions = self._props_events(games, status, game_filter)
        board = self._props_for(events, companions, teams=teams, lines='all', price=False)
        players = {}
        for game in board:
            for prop in game['props']:
                entry = players.setdefault((game['slug'], prop['player']), {
                    'player': prop['player'],
                    'team': prop['team'],
                    'opponent': _opponent(prop['team'], game),
                    'game': game['title'],
                    'slug': game['slug'],
                    'start_time': game['start_time'],
                    'prop_types': set(),
                })
                entry['prop_types'].add(prop['type'])
        far_future = datetime.max.replace(tzinfo=timezone.utc)
        result = sorted(players.values(),
                        key=lambda p: (p['start_time'] or far_future, p['team'] or '', p['player'] or ''))
        for entry in result:
            entry['prop_types'] = sorted(entry['prop_types'])
        return result

    def get_player_props(self, player, games=None, prop_types=None, live=True, status=('scheduled', 'live'),
                         game_filter=None, include_closed_markets=False):
        """
        Every prop for one player, organized like a sportsbook player page: for each stat, the ladder of
        lines with Over/Under (or Yes/No) odds, the main line, and the market-implied median.

        Parameters
        ----------
        player : str
            Player name. Loose matching: 'Mahomes', 'pat mahomes' and 'Patrick Mahomes' all work. Raises
            ValueError if the name is unknown or ambiguous (the message lists the candidates).
        games : list, optional
            Games to search, by default every scheduled or live game
        prop_types : str or list, optional
            Only these prop types, by default all
        live : bool, optional
            Refresh prices from the order book, by default True

        Returns
        -------
        dict
            player, team, opponent, game (the game dict) and 'props': one entry per prop type with type,
            key, main_line, implied_median and 'lines' (line, is_main, liquid, probability, hold, outcomes).
            probability is the order book midpoint for Over/Yes, a vig-free estimate (None when the line
            is illiquid). implied_median is where the ladder crosses 50%: the market's projection.
        """
        events, companions = self._props_events(games, status, game_filter)
        board = self._props_for(events, companions, prop_types=prop_types, lines='all', price=False,
                                include_closed_markets=include_closed_markets)
        names = sorted({prop['player'] for game in board for prop in game['props'] if prop['player']})
        name = _match_player(player, names)

        game = next(g for g in board if any(p['player'] == name for p in g['props']))
        props = [p for p in game['props'] if p['player'] == name]
        self._price_markets(props, live)
        self._finalize(props, 'all', in_play=game['status'] == 'live')

        team = props[0]['team'] if props else None
        game = {k: v for k, v in game.items() if k != 'props'}
        return {
            'player': name,
            'team': team,
            'opponent': _opponent(team, game),
            'game': game,
            'props': build_prop_ladders(props),
        }

    def _props_events(self, games, status, game_filter):
        """Game events to search for props, plus their companion events keyed by game slug."""
        events = self._series_events()
        companions = {}
        for event in events:
            base = _companion_base(event)
            if base:
                companions.setdefault(base, []).append(event)

        if games is None:
            statuses = set(_as_tuple(status, ()))
            selected = []
            for event in _games_from(events):
                summary = self.summarize_game(event)
                if statuses and summary['status'] not in statuses:
                    continue
                if game_filter and not game_filter(summary):
                    continue
                selected.append(event)
            return selected, companions

        selected = self._events_for(games, status)
        for event in selected:
            slug = event.get('slug')
            if slug not in companions:
                fetched = (self.pm.get_event_by_slug(str(slug) + suffix) for suffix in COMPANION_SUFFIXES)
                companions[slug] = [c for c in fetched if c]
        return selected, companions

    def _props_for(self, events, companions, players=None, prop_types=None, teams=None, lines='main', live=True,
                   include_closed_markets=False, price=True):
        """Builds props for several games, pricing them together in one batch."""
        team_filter = None
        if teams is not None:
            wanted = [self.find_team(t) for t in _as_tuple(teams, ())]
            if None in wanted:
                raise ValueError(f"Unknown team in {teams}")
            team_filter = {t.get('alias') or t.get('name') for t in wanted}

        board = []
        for event in events:
            game = self.summarize_game(event)
            raw = [m for c in companions.get(event.get('slug'), []) for m in c.get('markets', [])]
            teams_in_game = event.get('teams') or []
            props = self._build_markets(raw, _as_tuple(prop_types), ('game',), lines, live=False,
                                        include_closed_markets=include_closed_markets, teams=teams_in_game,
                                        props=True, price=False)
            # Team First TD markets name each player's team; read them from every market, so the labels
            # work even when prop_types leaves those markets out
            player_teams = _player_teams(raw, teams_in_game)
            for prop in props:
                prop['player'] = prop['subject']
                prop['team'] = player_teams.get(_name_key(prop['player']))
            if team_filter is not None:
                props = [p for p in props if p['team'] in team_filter]
            game['props'] = props
            board.append(game)

        if players is not None:
            names = sorted({p['player'] for g in board for p in g['props'] if p['player']})
            matched = set()
            for query in _as_tuple(players, ()):
                matched.update(_match_names(query, names))
            for game in board:
                game['props'] = [p for p in game['props'] if p['player'] in matched]

        if price:
            self._price_markets([p for g in board for p in g['props']], live)
            for game in board:
                self._finalize(game['props'], lines, in_play=game['status'] == 'live')
        return board

    ###############################
    # Futures
    ###############################
    def get_futures(self, search=None, include_closed=False):
        """
        Lists the league's futures (championship, MVP, awards, season win totals...).

        Parameters
        ----------
        search : str, optional
            Only futures whose title contains this text (case-insensitive)

        Returns
        -------
        list
            Futures event summaries: id, slug, title, end_date, volume, markets (count), url
        """
        events = self.pm.get_events(tag=self.primary_tag_id, include_closed=include_closed, active_only=False)
        futures = []
        for event in events:
            if event.get('gameId') or _is_companion(event):
                continue
            if search and search.lower() not in str(event.get('title', '')).lower():
                continue
            futures.append({
                'id': event.get('id'),
                'slug': event.get('slug'),
                'title': event.get('title'),
                'end_date': _parse_time(event.get('endDate')),
                'volume': _float(event.get('volume')),
                'markets': len(event.get('markets') or []),
                'url': f"https://polymarket.com/event/{event.get('slug')}",
            })
        return sorted(futures, key=lambda f: f['volume'] or 0, reverse=True)

    def get_future_odds(self, future, live=True, include_closed_markets=False):
        """
        Gets odds for every selection in a futures market (e.g. each team to win the championship).

        Parameters
        ----------
        future : dict or str
            A future from get_futures(), an event slug or an event id

        Returns
        -------
        dict
            id, slug, title, url and 'selections': name, bid, ask, mid and odds for 'Yes' on each
            selection, sorted from favorite to longshot, plus 'hold' (sum of prices - 1).
        """
        event = self._game_event(future)
        selections = []
        for market in event.get('markets', []):
            if market.get('closed') and not include_closed_markets:
                continue
            tokens = _json_list(market.get('clobTokenIds'))
            outcomes = _json_list(market.get('outcomes'))
            if not tokens:
                continue
            yes_index = outcomes.index('Yes') if 'Yes' in outcomes else 0
            selections.append({
                'name': market.get('groupItemTitle') or market.get('question'),
                'question': market.get('question'),
                'market_id': market.get('id'),
                'condition_id': market.get('conditionId'),
                'token_id': str(tokens[yes_index]),
                'fee_rate': self._fee_rate(market),
                'accepting_bets': bool(market.get('acceptingOrders')) and not market.get('closed'),
                **self._gamma_prices(market, yes_index),
            })
        if live and selections:
            prices = self.pm.get_prices([s['token_id'] for s in selections])
            for s in selections:
                s.update(_mid(prices.get(s['token_id'])))
        for s in selections:
            s['odds'] = quote(s['ask'], s['fee_rate'] if self.include_fees else 0)
        # Favorite first, by the all-in price to back each selection (unpriced selections last)
        selections.sort(key=lambda s: -(s['odds']['effective_price'] or 0))
        priced = [s['odds']['effective_price'] for s in selections if s['odds']['effective_price'] is not None]
        return {
            'id': event.get('id'),
            'slug': event.get('slug'),
            'title': event.get('title'),
            'url': f"https://polymarket.com/event/{event.get('slug')}",
            'selections': selections,
            'hold': round(sum(priced) - 1, 4) if priced and len(priced) == len(selections) else None,
        }

    ###############################
    # Order book depth
    ###############################
    def get_depth(self, outcome, levels=5):
        """
        Order book depth for an outcome from get_odds()/get_props(): the asks you would buy from (backing
        the outcome) and the bids you could sell to, as (price, size) best first, with odds per level.
        """
        book = self.pm.get_order_books([outcome['token_id']]).get(str(outcome['token_id']))
        if not book:
            return {'asks': [], 'bids': []}
        fee_rate = outcome.get('fee_rate', 0) if self.include_fees else 0
        return {
            'asks': [{'price': p, 'size': s, 'american': quote(p, fee_rate)['american']} for p, s in book['asks'][:levels]],
            'bids': [{'price': p, 'size': s} for p, s in book['bids'][:levels]],
            'tick_size': book['tick_size'],
            'min_order_size': book['min_order_size'],
        }

    ###############################
    # Internals
    ###############################
    def _events_for(self, games, status):
        if games is None:
            statuses = set(_as_tuple(status, ()))
            return [e for e in self.get_game_events() if not statuses or self.summarize_game(e)['status'] in statuses]
        events = []
        for game in games:
            if isinstance(game, dict) and isinstance(game.get('markets'), list):
                events.append(game)
            else:
                events.append(self._game_event(game))
        return events

    @staticmethod
    def _fee_rate(market):
        if not market.get('feesEnabled'):
            return 0.0
        return _float((market.get('feeSchedule') or {}).get('rate')) or 0.0

    @staticmethod
    def _gamma_prices(market, index):
        """Cached Gamma prices for outcome `index` of a binary market (bestBid/bestAsk are for outcome 0)."""
        bid, ask = _float(market.get('bestBid')), _float(market.get('bestAsk'))
        if index == 1:
            bid, ask = (None if ask is None else round(1 - ask, 6)), (None if bid is None else round(1 - bid, 6))
        return _mid({'bid': bid, 'ask': ask})

    def _build_markets(self, raw_markets, market_types, periods, lines, live, include_closed_markets, teams,
                       props=False, subject_filter=None, price=True, in_play=False):
        if lines not in LINE_FILTERS:
            raise ValueError(f"lines must be one of {LINE_FILTERS}")
        types = _as_tuple(market_types)
        wanted_periods = _as_tuple(periods)

        markets = []
        for raw in raw_markets:
            key, period = split_market_type(raw.get('sportsMarketType'))
            if types and key not in types and raw.get('sportsMarketType') not in types:
                continue
            if wanted_periods and period not in wanted_periods:
                continue
            accepting = bool(raw.get('acceptingOrders')) and not raw.get('closed')
            if not accepting and not include_closed_markets:
                continue
            market = self._normalize_market(raw, key, period, teams, props)
            if subject_filter and not subject_filter(market['subject']):
                continue
            markets.append(market)

        if price:
            self._price_markets(markets, live)
            self._finalize(markets, lines, in_play=in_play)
        return markets

    def _normalize_market(self, raw, key, period, teams, props):
        names = _json_list(raw.get('outcomes'))
        tokens = [str(t) for t in _json_list(raw.get('clobTokenIds'))]
        line = _float(raw.get('line'))
        title = raw.get('groupItemTitle') or raw.get('question') or ''

        points = [None] * len(names)
        if line is not None:
            if key == 'spreads' and len(names) == 2:
                points = [line, -line]
                match = _SPREAD_QUESTION.search(raw.get('question') or '')
                # The line belongs to the team named in the question; make sure it lines up with the outcome.
                if match and _same_team(match.group(1), names[1], teams) and not _same_team(match.group(1), names[0], teams):
                    points = [-line, line]
            elif set(names) <= {'Over', 'Under'}:
                points = [line] * len(names)

        if props:
            # 'Bo Nix: Passing Yards O/U 99.5' -> 'Bo Nix'; first-TD markets are titled with just the player
            subject = title.split(':')[0].strip() if ':' in title else title.strip() or None
        else:
            subject = _team_in(raw.get('question') or title, teams) if 'team' in key else None

        fee_rate = self._fee_rate(raw)
        outcomes = []
        for i, name in enumerate(names):
            outcome = {
                'name': name,
                'point': points[i],
                'token_id': tokens[i] if i < len(tokens) else None,
                'fee_rate': fee_rate,
            }
            outcome.update(self._gamma_prices(raw, i) if len(names) == 2 else {'bid': None, 'ask': None, 'mid': None})
            outcomes.append(outcome)

        return {
            'key': key,
            'period': period,
            'type': raw.get('sportsMarketType'),
            'description': title,
            'subject': subject,
            'line': line,
            'is_main': None,
            'market_id': raw.get('id'),
            'condition_id': raw.get('conditionId'),
            'slug': raw.get('slug'),
            'accepting_bets': bool(raw.get('acceptingOrders')) and not raw.get('closed'),
            'fee_rate': fee_rate,
            'tick_size': _float(raw.get('orderPriceMinTickSize')),
            'min_order_size': _float(raw.get('orderMinSize')),
            'volume': _float(raw.get('volume')),
            'featured': bool(raw.get('clobRewards')),
            'outcomes': outcomes,
            'hold': None,
            'liquid': None,
        }

    def _price_markets(self, markets, live):
        """Fills bid/ask/mid from the live order book (when live) and computes odds and hold."""
        if live:
            # In a binary market the second outcome's book mirrors the first (a bid for one side is an
            # ask for the other), so one token per market is enough. This halves the requests for big boards.
            tokens = []
            for market in markets:
                outcomes = market['outcomes']
                if len(outcomes) == 2 and outcomes[0]['token_id']:
                    tokens.append(outcomes[0]['token_id'])
                else:
                    tokens.extend(o['token_id'] for o in outcomes if o['token_id'])
            prices = self.pm.get_prices(tokens) if tokens else {}
            for market in markets:
                outcomes = market['outcomes']
                if len(outcomes) == 2 and outcomes[0]['token_id'] in prices:
                    first = prices[outcomes[0]['token_id']]
                    outcomes[0].update(_mid(first))
                    outcomes[1].update(_mid(_mirror(first)))
                    continue
                for outcome in outcomes:
                    if outcome['token_id'] in prices:
                        outcome.update(_mid(prices[outcome['token_id']]))
        for market in markets:
            fee_rate = market['fee_rate'] if self.include_fees else 0
            for outcome in market['outcomes']:
                outcome['odds'] = quote(outcome['ask'], fee_rate)
            costs = [o['odds']['effective_price'] for o in market['outcomes']]
            market['hold'] = round(sum(costs) - 1, 4) if costs and None not in costs else None
            market['liquid'] = bool(market['outcomes']) and all(_is_liquid(o) for o in market['outcomes'])

    @staticmethod
    def _finalize(markets, lines, in_play=False):
        """
        Marks the main line in each group of alternate lines, applies the line filter and sorts.

        Before the game, the main line is the one Polymarket features (it carries liquidity rewards), or
        failing that the one closest to even odds. In play, the featured line goes stale as the score
        changes, so the main line is the one closest to even odds.
        """
        groups = {}
        for market in markets:
            groups.setdefault((market['type'], market['subject']), []).append(market)
        for group in groups.values():
            with_line = [m for m in group if m['line'] is not None]
            if not with_line:
                for m in group:
                    m['is_main'] = True if len(group) == 1 else None
                continue
            main = min(with_line, key=lambda m: _main_line_rank(m, in_play))
            for m in with_line:
                m['is_main'] = m is main

        if lines == 'main':
            markets[:] = [m for m in markets if m['is_main'] is not False]
        elif lines == 'alt':
            markets[:] = [m for m in markets if m['is_main'] is False]
        markets.sort(key=lambda m: (PERIOD_ORDER.index(m['period']) if m['period'] in PERIOD_ORDER else 99,
                                    m['key'], m['subject'] or '', m['line'] if m['line'] is not None else 0))


###############################
# Module helpers
###############################
def _aware(value):
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _mid(prices):
    prices = prices or {}
    bid, ask = prices.get('bid'), prices.get('ask')
    mid = round((bid + ask) / 2, 6) if bid is not None and ask is not None else None
    return {'bid': bid, 'ask': ask, 'mid': mid}


MAX_LIQUID_SPREAD = 0.1  # bid-ask width above which a line is treated as illiquid when picking the main line


def _main_line_rank(market, in_play=False):
    """
    Sort key for picking the main line among alternates: liquid lines first, then (before the game) the
    line Polymarket features, then the line closest to even odds.

    Liquidity comes first because an empty book quoted 1c/99c has a 50c midpoint, and the featured flag
    can sit on a dead line. For a liquid line, "closest to even" uses the midpoint. For an illiquid one it
    uses the real ask closest to 50c on either side, i.e. the line someone is actually offering near even
    money.
    """
    outcomes = market['outcomes'] or [{}]
    first = outcomes[0]
    liquid = _is_liquid(first)
    featured = market.get('featured') and not in_play
    if liquid:
        distance = abs(first['mid'] - 0.5)
    else:
        asks = [o.get('ask') for o in outcomes if o.get('ask') is not None]
        distance = min((abs(a - 0.5) for a in asks), default=1.0)
    return (0 if liquid else 1, 0 if featured else 1, distance)


def _is_liquid(outcome):
    """
    A real two-sided book: a bid above 1c, an ask below 99c (1c bids and 99c asks are placeholder dust
    orders), and a bid-ask width of at most MAX_LIQUID_SPREAD.
    """
    bid, ask = outcome.get('bid'), outcome.get('ask')
    return (bid is not None and ask is not None and bid > 0.011 and ask < 0.989
            and ask - bid <= MAX_LIQUID_SPREAD)


def _is_companion(event):
    return str(event.get('slug', '')).endswith(COMPANION_SUFFIXES)


def _companion_base(event):
    """The game slug a companion event belongs to, or None if it isn't a companion."""
    slug = str(event.get('slug', ''))
    for suffix in COMPANION_SUFFIXES:
        if slug.endswith(suffix):
            return slug[:-len(suffix)]
    return None


def _games_from(events):
    """One event per game id, skipping companion and non-game events."""
    games = {}
    for event in events:
        if not event.get('gameId') or _is_companion(event):
            continue
        current = games.get(event['gameId'])
        if current is None or len(str(event.get('slug', ''))) < len(str(current.get('slug', ''))):
            games[event['gameId']] = event
    return list(games.values())


def _mirror(prices):
    """Bid/ask for the other side of a binary market: its bid is 1 - ask and its ask is 1 - bid."""
    bid, ask = (prices or {}).get('bid'), (prices or {}).get('ask')
    return {'bid': None if ask is None else round(1 - ask, 6), 'ask': None if bid is None else round(1 - bid, 6)}


###############################
# Player helpers
###############################
_NAME_SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv', 'v'}
_TEAM_IN_PARENS = re.compile(r'\(([^)]+)\)\s*$')


def _name_key(name):
    """'Amon-Ra St. Brown Jr.' -> 'amon ra st brown': no accents, punctuation, case or suffixes."""
    text = unicodedata.normalize('NFKD', str(name or '')).encode('ascii', 'ignore').decode().lower()
    words = re.sub(r"[^a-z0-9]+", ' ', text).split()
    return ' '.join(w for w in words if w not in _NAME_SUFFIXES)


def _match_names(query, names):
    """Names matching query: an exact (normalized) match, else every query word prefixes a word of the name."""
    key = _name_key(query)
    exact = [n for n in names if _name_key(n) == key]
    if exact:
        return exact
    words = key.split()
    return [n for n in names
            if words and all(any(part.startswith(w) for part in _name_key(n).split()) for w in words)]


def _match_player(query, names):
    matches = _match_names(query, names)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"No player props found for '{query}'")
    raise ValueError(f"'{query}' matches several players: {', '.join(matches)}")


def _player_teams(raw_markets, teams):
    """Player name key -> team alias, from raw 'Player: Team First TD (Full Team Name)' markets."""
    mapping = {}
    for raw in raw_markets:
        title = raw.get('groupItemTitle') or raw.get('question') or ''
        match = _TEAM_IN_PARENS.search(title)
        if not match or ':' not in title:
            continue
        team_text = match.group(1).strip().lower()
        team = next((t for t in teams if team_text in _team_names(t)), None)
        if team:
            mapping[_name_key(title.split(':')[0])] = team.get('alias') or team.get('name')
    return mapping


def _opponent(team, game):
    if not team:
        return None
    for mine, theirs in (('away_team', 'home_team'), ('home_team', 'away_team')):
        info = game.get(mine) or {}
        if team in (info.get('alias'), info.get('name')):
            return (game.get(theirs) or {}).get('alias')
    return None


def _implied_median(rungs):
    """
    The stat value where P(over) crosses 50%, interpolated between liquid ladder lines. None if there aren't
    liquid lines on both sides of 50%.
    """
    points = sorted((r for r in rungs if r['line'] is not None and r['probability'] is not None),
                    key=lambda r: r['line'])
    for low, high in zip(points, points[1:]):
        p_low, p_high = low['probability'], high['probability']
        if p_low >= 0.5 >= p_high and p_low != p_high:
            fraction = (p_low - 0.5) / (p_low - p_high)
            return round(low['line'] + fraction * (high['line'] - low['line']), 2)
    exact = [r['line'] for r in points if r['probability'] == 0.5]
    return exact[0] if exact else None


def build_prop_ladders(props):
    """
    Groups prop markets (from get_props/get_props_board with lines='all') into one ladder per player and
    prop type, with the main line and the market-implied median.
    """
    groups = {}
    for prop in props:
        groups.setdefault((prop.get('player'), prop['type']), []).append(prop)
    ladders = []
    for (player, prop_type), markets in groups.items():
        markets = sorted(markets, key=lambda m: (m['line'] is None, m['line'] or 0))
        rungs = [{
            'line': m['line'],
            'is_main': m['is_main'],
            'liquid': m['liquid'],
            # The midpoint is only a meaningful probability when the book is tight
            'probability': m['outcomes'][0]['mid'] if m['outcomes'] and m['liquid'] else None,
            'hold': m['hold'],
            'market_id': m['market_id'],
            'outcomes': m['outcomes'],
        } for m in markets]
        main = next((m for m in markets if m['is_main']), None)
        ladders.append({
            'player': player,
            'team': markets[0].get('team'),
            'type': prop_type,
            'key': markets[0]['key'],
            'main_line': main['line'] if main else None,
            'implied_median': _implied_median(rungs),
            'lines': rungs,
        })
    return sorted(ladders, key=lambda ladder: (ladder['player'] or '', ladder['type']))


def _team_summary(team):
    if not team:
        return None
    return {k: team.get(k) for k in ('id', 'name', 'abbreviation', 'alias', 'record', 'logo')}


def _parse_score(score):
    if not score:
        return None
    match = re.match(r'^\s*(\d+)\s*-\s*(\d+)\s*$', str(score))
    if not match:
        return {'raw': score}
    return {'away': int(match.group(1)), 'home': int(match.group(2)), 'raw': score}


def _team_names(team):
    return {str(team.get(k)).lower() for k in ('alias', 'name', 'abbreviation') if team.get(k)}


def _same_team(text, outcome_name, teams):
    text, outcome_name = str(text).strip().lower(), str(outcome_name).strip().lower()
    if text == outcome_name:
        return True
    return any(text in _team_names(t) and outcome_name in _team_names(t) for t in teams)


def _team_in(text, teams):
    """The alias of the team mentioned in text, if exactly one is."""
    text = str(text).lower()
    found = [t for t in teams if any(re.search(r'\b' + re.escape(n) + r'\b', text) for n in _team_names(t)
                                     if len(n) > 3 or n == str(t.get('alias', '')).lower())]
    return found[0].get('alias') or found[0].get('name') if len(found) == 1 else None


def odds_to_rows(odds):
    """
    Flattens get_odds()/get_props()/get_odds_board() output into one row per outcome, e.g. for
    pandas.DataFrame(odds_to_rows(...)).
    """
    games = odds if isinstance(odds, list) else [odds]
    rows = []
    for game in games:
        for market in game.get('markets', []) + game.get('props', []):
            for outcome in market['outcomes']:
                rows.append({
                    'game': game.get('title'),
                    'slug': game.get('slug'),
                    'start_time': game.get('start_time'),
                    'status': game.get('status'),
                    'market': market['key'],
                    'period': market['period'],
                    'subject': market.get('subject') or market.get('player'),
                    'team': market.get('team'),
                    'is_main': market['is_main'],
                    'liquid': market.get('liquid'),
                    'outcome': outcome['name'],
                    'point': outcome['point'],
                    'american': outcome['odds']['american'],
                    'decimal': outcome['odds']['decimal'],
                    'bid': outcome['bid'],
                    'ask': outcome['ask'],
                    'mid': outcome['mid'],
                    'hold': market['hold'],
                    'token_id': outcome['token_id'],
                })
    return rows
