"""
Polymarket API wrappers.

- Polymarket: public data (Gamma API for markets/events/tags/comments, Data API v2 for users, positions,
  trades, holders and leaderboards) plus real-time monitors. No authentication required.
- PolymarketAuth: adds an authenticated trading client built on Polymarket's unified SDK
  (``pip install "lukhed_markets[polymarket-trading]"``, Python 3.11+).

Errors: every request method raises ``PolymarketAPIError`` when the API returns an error, instead of
returning an empty result. Lookups by id or slug return None when the item doesn't exist (HTTP 404).

Logging: this module logs through the ``logging`` module (logger names ``lukhed_markets.polymarket`` and
``lukhed_markets.polymarket_realtime``). Call ``logging.basicConfig(level=logging.INFO)`` to see progress.

Docs:
- Gamma API: https://docs.polymarket.com/market-data/overview
- Data API v2: https://docs.polymarket.com/api-reference/data-api/overview
- Market websocket: https://docs.polymarket.com/market-data/websocket/market-channel
- Unified SDK: https://docs.polymarket.com/migrate/clob-sdk-to-unified-sdk
"""
import getpass
import json
import logging
import sys
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from lukhed_basic_utils import timeCommon as tC
from lukhed_basic_utils.classCommon import LukhedAuth

from .polymarket_tags import TAG_MAPPING
from .polymarket_realtime import MarketWebSocket, WhaleMonitor, PositionMonitor, MARKET_WS_URL

__all__ = ['Polymarket', 'PolymarketAuth', 'PolymarketAPIError', 'MarketWebSocket', 'WhaleMonitor',
           'PositionMonitor']

logger = logging.getLogger(__name__)

GAMMA_URL = 'https://gamma-api.polymarket.com'
DATA_URL = 'https://data-api.polymarket.com/v2'

GAMMA_PAGE_LIMIT = 100      # Gamma silently caps every page at 100 rows
DATA_PAGE_LIMIT = 1000      # Data API v2 maximum page size

POSITION_STATUSES = ('OPEN', 'REDEEMABLE', 'REDEEMABLE_LOST', 'MERGEABLE', 'CLOSED')
POSITION_SORT_FIELDS = ('CURRENT_VALUE', 'PRICE', 'TOKENS', 'UNREALIZED_PNL', 'REALIZED_PNL', 'TOTAL_PNL',
                        'TIMESTAMP')
LEADERBOARD_PERIODS = ('day', 'week', 'month', 'all')
LEADERBOARD_SORTS = {'profit': 'PNL', 'pnl': 'PNL', 'volume': 'VOLUME', 'vol': 'VOLUME'}
COMMENT_ENTITY_TYPES = {'event': 'Event', 'series': 'Series', 'perpsasset': 'PerpsAsset'}

_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


class PolymarketAPIError(Exception):
    """Raised when a Polymarket API request fails."""
    def __init__(self, message, status_code=None, url=None, response_data=None):
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.response_data = response_data


class Polymarket:
    """
    Wraps the public Polymarket Gamma and Data APIs and adds discovery and monitoring helpers.
    It does not require authentication.

    Parameters
    ----------
    api_delay : float, optional
        Minimum seconds between requests (shared across threads), by default 0.1
    timeout : float, optional
        Request timeout in seconds, by default 15
    max_retries : int, optional
        Retries for rate limits (429, honoring Retry-After), 5xx errors and connection errors, by default 3
    session : requests.Session, optional
        Session to use, e.g. one with custom proxies or headers. By default a new session is created.
    check_status : bool, optional
        If True, check that both APIs respond during construction and log the result, by default False
    """
    def __init__(self, api_delay=0.1, timeout=15, max_retries=3, session=None, check_status=False):
        self.delay = api_delay
        self.timeout = timeout
        self.max_retries = max_retries
        self.gamma_url = GAMMA_URL
        self.data_url = DATA_URL
        self.ws_url = MARKET_WS_URL

        self.session = session or requests.Session()
        self.session.headers.setdefault('User-Agent', 'lukhed_markets')

        self._throttle_lock = threading.Lock()
        self._last_request_time = 0.0
        self._tag_cache = {}

        if check_status:
            logger.info("gamma api status: %s", self.get_gamma_status())
            logger.info("data api status: %s", self.get_data_status())

    ###############################
    # Transport
    ###############################
    def _throttle(self):
        if not self.delay:
            return
        with self._throttle_lock:
            wait = self.delay - (time.monotonic() - self._last_request_time)
            if wait > 0:
                time.sleep(wait)
            self._last_request_time = time.monotonic()

    @staticmethod
    def _clean_params(params):
        """Drop None values, send booleans as true/false and lists as comma-separated strings."""
        cleaned = {}
        for key, value in (params or {}).items():
            if value is None:
                continue
            if isinstance(value, bool):
                value = 'true' if value else 'false'
            elif isinstance(value, (list, tuple, set)):
                value = ','.join(str(v) for v in value)
            cleaned[key] = value
        return cleaned

    @staticmethod
    def _retry_after_seconds(response):
        value = response.headers.get('Retry-After')
        try:
            return max(float(value), 0)
        except (TypeError, ValueError):
            return None

    def _request(self, url, params=None, allow_404=False):
        """
        GET a JSON endpoint. Retries rate limits, server errors and connection errors; raises
        PolymarketAPIError on failure. Returns None for a 404 when allow_404 is True.
        """
        params = self._clean_params(params)
        response = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            backoff = min(0.5 * 2 ** attempt, 30)
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as e:
                if attempt < self.max_retries:
                    logger.warning("Request to %s failed (%s), retrying in %.1fs", url, e, backoff)
                    time.sleep(backoff)
                    continue
                raise PolymarketAPIError(f"Request to {url} failed: {e}", url=url) from e

            if response.status_code in _RETRY_STATUS_CODES and attempt < self.max_retries:
                wait = self._retry_after_seconds(response)
                wait = backoff if wait is None else wait
                logger.warning("HTTP %s from %s, retrying in %.1fs", response.status_code, url, wait)
                time.sleep(wait)
                continue
            break

        if response.status_code == 404 and allow_404:
            return None

        try:
            data = response.json()
        except ValueError:
            data = None

        if not response.ok:
            message = data.get('error') if isinstance(data, dict) else None
            raise PolymarketAPIError(
                f"HTTP {response.status_code} from {url}: {message or response.text[:200]}",
                status_code=response.status_code, url=url, response_data=data)
        if data is None:
            raise PolymarketAPIError(f"Non-JSON response from {url}: {response.text[:200]}",
                                     status_code=response.status_code, url=url)
        return data

    @staticmethod
    def _page_limit(limit, max_results, collected):
        if max_results is None:
            return limit
        return max(1, min(limit, max_results - collected))

    @staticmethod
    def _done(get_all_data, max_results, collected):
        return not get_all_data or (max_results is not None and collected >= max_results)

    def _paginate_data(self, path, params=None, get_all_data=False, limit=500, max_results=None):
        """Data API v2 cursor pagination: follow pagination.next_cursor until it is null."""
        url = self.data_url + path
        limit = min(limit, DATA_PAGE_LIMIT)
        results = []
        cursor = None
        page = 0
        while True:
            page_params = dict(params or {}, limit=self._page_limit(limit, max_results, len(results)),
                               cursor=cursor)
            payload = self._request(url, page_params)
            data = payload.get('data') if isinstance(payload, dict) else payload
            if data is None:
                break
            if not isinstance(data, list):
                return data
            results.extend(data)
            page += 1
            if page % 10 == 0:
                logger.info("Fetched %d rows from %s...", len(results), path)
            cursor = (payload.get('pagination') or {}).get('next_cursor') if isinstance(payload, dict) else None
            if not cursor or not data or self._done(get_all_data, max_results, len(results)):
                break
        return results[:max_results] if max_results is not None else results

    def _paginate_gamma_keyset(self, path, items_key, params=None, get_all_data=False, limit=GAMMA_PAGE_LIMIT,
                               max_results=None):
        """Gamma keyset pagination: pass after_cursor, follow next_cursor."""
        url = self.gamma_url + path
        limit = min(limit, GAMMA_PAGE_LIMIT)
        results = []
        cursor = None
        page = 0
        while True:
            page_params = dict(params or {}, limit=self._page_limit(limit, max_results, len(results)),
                               after_cursor=cursor)
            payload = self._request(url, page_params)
            items = payload.get(items_key) or []
            results.extend(items)
            page += 1
            if page % 10 == 0:
                logger.info("Fetched %d %s...", len(results), items_key)
            cursor = payload.get('next_cursor')
            if not cursor or not items or self._done(get_all_data, max_results, len(results)):
                break
        return results[:max_results] if max_results is not None else results

    def _paginate_gamma_offset(self, path, params=None, get_all_data=False, limit=GAMMA_PAGE_LIMIT,
                               max_results=None):
        """Gamma offset pagination, for endpoints without a keyset variant (tags, comments)."""
        url = self.gamma_url + path
        limit = min(limit, GAMMA_PAGE_LIMIT)
        results = []
        offset = 0
        while True:
            page_params = dict(params or {}, limit=self._page_limit(limit, max_results, len(results)),
                               offset=offset)
            items = self._request(url, page_params) or []
            results.extend(items)
            # Advance by what was actually returned: Gamma may cap the page below the requested limit.
            offset += len(items)
            if not items or self._done(get_all_data, max_results, len(results)):
                break
        return results[:max_results] if max_results is not None else results

    ###############################
    # Helpers
    ###############################
    def _resolve_tag_id(self, tag):
        """Accept a tag id, a TAG_MAPPING name or a Gamma tag slug; return the tag id."""
        if tag is None:
            return None
        if isinstance(tag, int):
            return str(tag)
        text = str(tag).strip()
        if text.isdigit():
            return text
        key = text.lower()
        if key in TAG_MAPPING:
            return TAG_MAPPING[key]
        if key not in self._tag_cache:
            slug = key.replace(' ', '-')
            data = self._request(f'{self.gamma_url}/tags/slug/{slug}', allow_404=True)
            if not data:
                raise ValueError(f'Unknown Polymarket tag "{tag}". Pass a tag id or slug (see get_tags()).')
            self._tag_cache[key] = str(data['id'])
        return self._tag_cache[key]

    @staticmethod
    def _parse_date_inputs(start_date=None, end_date=None, date_format="%Y-%m-%d"):
        if start_date:
            start_date = tC.convert_to_unix(start_date, from_format=date_format)
        if end_date:
            end_date = tC.convert_to_unix(end_date, from_format=date_format)
        return start_date, end_date

    @staticmethod
    def _add_date_times(data):
        """Add 'utc' and 'est' datetime fields to rows that have a unix 'timestamp'."""
        eastern = ZoneInfo('America/New_York')
        for item in data or []:
            ts = item.get('timestamp') if isinstance(item, dict) else None
            if ts:
                utc_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                item['utc'] = utc_dt
                item['est'] = utc_dt.astimezone(eastern)
        return data

    @staticmethod
    def _json_list(value):
        """Gamma returns some list fields (outcomes, clobTokenIds) as JSON strings."""
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                return []
        return value or []

    @staticmethod
    def _check_one_selector(condition_id, event_id):
        if condition_id is not None and event_id is not None:
            raise ValueError("Provide condition_id or event_id, not both")

    ###############################
    # Status
    ###############################
    def get_gamma_status(self):
        """Returns the Gamma API status text ('OK' when healthy). Raises PolymarketAPIError on failure."""
        url = f'{self.gamma_url}/status'
        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as e:
            raise PolymarketAPIError(f"Request to {url} failed: {e}", url=url) from e
        if not response.ok:
            raise PolymarketAPIError(f"HTTP {response.status_code} from {url}", status_code=response.status_code,
                                     url=url)
        return response.text

    def get_data_status(self):
        """Returns the Data API v2 status (indexing lag and health details)."""
        return self._request(f'{self.data_url}/status').get('data')

    ###############################
    # Market Methods
    ###############################
    def get_markets(self, get_all_data=True, include_closed=False, active_only=True, tag_filter=None,
                    condition_ids=None, order=None, ascending=None, max_results=None):
        """
        Gets a list of markets from the Gamma API (keyset pagination, 100 per page).

        Parameters
        ----------
        get_all_data : bool, optional
            Whether to return all pages of data, by default True. Note there are hundreds of thousands of
            closed markets, so combine include_closed with a filter or max_results.
        include_closed : bool, optional
            Whether to include closed markets (in addition to open ones), by default False
        active_only : bool, optional
            Whether to only return active markets, by default True
        tag_filter : str or int, optional
            Tag id, TAG_MAPPING name or tag slug to filter markets, by default None
        condition_ids : str or list, optional
            Only return markets with these condition ids, by default None
        order : str, optional
            Comma-separated list of fields to order by, by default None
        ascending : bool, optional
            Order direction when order is given, by default None (API default)
        max_results : int, optional
            Stop after this many markets, by default None (no limit)

        Returns
        -------
        list
            List of markets
        """
        params = {
            "active": True if active_only else None,
            "tag_id": self._resolve_tag_id(tag_filter),
            "condition_ids": condition_ids,
            "order": order,
            "ascending": ascending,
        }
        results = []
        for closed in ([False, True] if include_closed else [False]):
            remaining = None if max_results is None else max_results - len(results)
            if remaining is not None and remaining <= 0:
                break
            results.extend(self._paginate_gamma_keyset(
                '/markets/keyset', 'markets', dict(params, closed=closed), get_all_data=get_all_data,
                max_results=remaining))
        return results

    def get_market_by_id(self, market_id, include_tag=True):
        """
        Gets data for a market given its Gamma market id.
        https://docs.polymarket.com/api-reference/markets/get-market-by-id

        Returns
        -------
        dict or None
            Market data, or None if the market doesn't exist
        """
        return self._request(f'{self.gamma_url}/markets/{market_id}', {"include_tag": include_tag or None},
                             allow_404=True)

    def get_market_by_slug(self, market_slug, include_tag=False):
        """Gets data for a market given its slug. Returns None if the market doesn't exist."""
        return self._request(f'{self.gamma_url}/markets/slug/{market_slug}', {"include_tag": include_tag or None},
                             allow_404=True)

    def get_markets_for_event(self, event_id, event_id_type='id', event_data=None):
        """
        Gets markets for a specific event by event ID or slug.

        Parameters
        ----------
        event_id : str
            The event ID or slug to get markets for.
        event_id_type : str, optional
            Type of event identifier ('id' or 'slug'), by default 'id'
        event_data : dict, optional
            Event data you already have, to avoid a request, by default None

        Returns
        -------
        list
            List of markets for the event (empty if the event doesn't exist)
        """
        if event_data is None:
            if event_id_type == 'slug':
                event_data = self.get_event_by_slug(event_id)
            else:
                event_data = self.get_event_by_id(event_id)
        if not event_data:
            logger.warning("Event not found for %s: %s", event_id_type, event_id)
            return []
        return event_data.get('markets', [])

    def get_top_holders_for_market(self, market_condition_id, min_balance=1, limit=20, include_pnl=False):
        """
        Gets the top holders for a market (Data API v2).

        Parameters
        ----------
        market_condition_id : str
            The market condition ID.
        min_balance : float, optional
            Minimum balance filter, by default 1
        limit : int, optional
            Number of holders per outcome token, by default 20
        include_pnl : bool, optional
            Whether to add entry and P&L data per holder, by default False

        Returns
        -------
        list
            One entry per outcome token: {'token_id': ..., 'holders': [...]}
        """
        params = {"condition": market_condition_id, "min_balance": min_balance, "include_pnl": include_pnl or None}
        return self._paginate_data('/holders', params, limit=limit) or []

    ##############################
    # Event Methods
    ##############################
    def get_events(self, tag=None, include_closed=False, active_only=True, get_all_data=True, order=None,
                   ascending=True, max_results=None):
        """
        Gets a list of events from the Gamma API (keyset pagination, 100 per page).

        Parameters
        ----------
        tag : str or int, optional
            Tag id, TAG_MAPPING name or tag slug to filter events, by default None
        include_closed : bool, optional
            Whether to include closed events (in addition to open ones), by default False
        active_only : bool, optional
            Whether to only return active events, by default True
        get_all_data : bool, optional
            Whether to return all pages of data, by default True
        order : str, optional
            Comma-separated list of fields to order by, e.g. 'volume24hr'
        ascending : bool, optional
            Whether to order in ascending order, by default True
        max_results : int, optional
            Stop after this many events, by default None (no limit)

        Returns
        -------
        list
            List of events
        """
        params = {
            "tag_id": self._resolve_tag_id(tag),
            "active": True if active_only else None,
            "order": order,
            "ascending": ascending if order else None,
        }
        results = []
        for closed in ([False, True] if include_closed else [False]):
            remaining = None if max_results is None else max_results - len(results)
            if remaining is not None and remaining <= 0:
                break
            results.extend(self._paginate_gamma_keyset(
                '/events/keyset', 'events', dict(params, closed=closed), get_all_data=get_all_data,
                max_results=remaining))
        return results

    def get_event_by_id(self, event_id):
        """Returns event data for an event id, or None if it doesn't exist."""
        return self._request(f'{self.gamma_url}/events/{event_id}', allow_404=True)

    def get_event_by_slug(self, event_slug):
        """
        Returns event data for a given event slug, or None if it doesn't exist.

        Each event on Polymarket has a slug in its URL. For example, in
        https://polymarket.com/event/fed-decision-in-january?tid=1767460047178 the slug is
        'fed-decision-in-january'.
        """
        return self._request(f'{self.gamma_url}/events/slug/{event_slug}', allow_404=True)

    ###############################
    # Tags
    ###############################
    def get_tags(self, get_all_data=True, max_results=None):
        """Gets the list of tags from the Gamma API."""
        return self._paginate_gamma_offset('/tags', get_all_data=get_all_data, max_results=max_results)

    def get_tag_by_id(self, tag_id):
        """Gets tag data for a tag id, or None if it doesn't exist."""
        return self._request(f'{self.gamma_url}/tags/{tag_id}', allow_404=True)

    def get_tag_by_slug(self, tag_slug):
        """Gets tag data for a tag slug (e.g. 'politics'), or None if it doesn't exist."""
        return self._request(f'{self.gamma_url}/tags/slug/{tag_slug}', allow_404=True)

    def get_related_tags(self, tag, tag_id=False):
        """
        Gets tags related to a tag.

        Parameters
        ----------
        tag : str or int
            Tag id, TAG_MAPPING name or tag slug
        tag_id : bool, optional
            Whether the provided tag is a tag id, by default False (resolved automatically either way)
        """
        resolved = str(tag) if tag_id else self._resolve_tag_id(tag)
        return self._request(f'{self.gamma_url}/tags/{resolved}/related-tags/tags') or []

    ###############################
    # Comments
    ###############################
    def list_comments(self, entity_type, entity_id, get_positions=True, get_all_data=True, ascending=True,
                      holders_only=False, max_results=None):
        """
        Gets comments for an event or series.

        Parameters
        ----------
        entity_type : str
            'Event', 'Series' or 'PerpsAsset'. Markets don't have their own comment threads; use the
            market's event id.
        entity_id : str
            The id of the entity.
        get_positions : bool, optional
            Whether to include commenters' positions, by default True
        get_all_data : bool, optional
            Whether to retrieve all pages of comments, by default True
        ascending : bool, optional
            Whether to sort comments in ascending order, by default True
        holders_only : bool, optional
            Whether to only include comments from holders, by default False
        max_results : int, optional
            Stop after this many comments, by default None (no limit)
        """
        normalized = COMMENT_ENTITY_TYPES.get(str(entity_type).strip().lower())
        if normalized is None:
            raise ValueError(f"entity_type must be one of {sorted(COMMENT_ENTITY_TYPES.values())}; "
                             f"for a market, pass its event id with entity_type='Event'")
        params = {
            "parent_entity_type": normalized,
            "parent_entity_id": entity_id,
            "get_positions": get_positions,
            "ascending": ascending,
            "holders_only": holders_only,
        }
        return self._paginate_gamma_offset('/comments', params, get_all_data=get_all_data, max_results=max_results)

    ###############################
    # Users (Data API v2)
    ###############################
    def get_leaderboards(self, category='OVERALL', time_period='ALL', rank_by='profit', get_all_data=False,
                         single_user_check=None, user_identifier='address', limit=50, max_results=None):
        """
        Gets the trader leaderboard, as shown at https://polymarket.com/leaderboard

        Parameters
        ----------
        category : str, optional
            Leaderboard category, e.g. OVERALL, POLITICS, SPORTS, CRYPTO, CULTURE, MENTIONS, WEATHER,
            ECONOMICS, TECH, FINANCE, by default 'OVERALL'
        time_period : str, optional
            DAY, WEEK, MONTH or ALL, by default 'ALL'
        rank_by : str, optional
            'profit' or 'volume', by default 'profit'
        get_all_data : bool, optional
            Whether to retrieve all pages, by default False
        single_user_check : str, optional
            A wallet address. If given, returns that user's standing instead of the leaderboard.
        user_identifier : str, optional
            Must be 'address': Data API v2 doesn't support username lookups.
        limit : int, optional
            Page size, by default 50
        max_results : int, optional
            Stop after this many entries, by default None

        Returns
        -------
        list or dict or None
            Leaderboard entries (rank, user_id, user_name, pnl, volume, ...). With single_user_check, a dict
            with the user's pnl, volume, rank_pnl and rank_volume, or None if the user isn't ranked.
        """
        period = str(time_period).lower()
        if period not in LEADERBOARD_PERIODS:
            raise ValueError(f"time_period must be one of {[p.upper() for p in LEADERBOARD_PERIODS]}")
        sort_by = LEADERBOARD_SORTS.get(str(rank_by).lower())
        if sort_by is None:
            raise ValueError("rank_by must be 'profit' or 'volume'")
        params = {"category": str(category).lower(), "time_period": period}

        if single_user_check:
            if user_identifier != 'address':
                raise ValueError("Data API v2 only looks up leaderboard standing by wallet address; "
                                 "use user_identifier='address'")
            payload = self._request(f'{self.data_url}/leaderboard', dict(params, user=single_user_check))
            return payload.get('data')

        params["sort_by"] = sort_by
        return self._paginate_data('/leaderboard', params, get_all_data=get_all_data, limit=limit,
                                   max_results=max_results)

    def get_user_activity(self, address, activity_type_list=("TRADE",), side=None, event_id=None,
                          condition_id=None, get_all_data=False, start_date=None, end_date=None,
                          date_format="%Y-%m-%d", add_datetime=True, limit=500, max_results=None):
        """
        Gets a user's activity, newest first (Data API v2).

        Parameters
        ----------
        address : str
            The user's wallet address.
        activity_type_list : list, optional
            Activity types to include, e.g. TRADE, SPLIT, MERGE, REDEEM, REWARD, CONVERSION, DEPOSIT,
            WITHDRAWAL, MAKER_REBATE, TAKER_REBATE, by default ["TRADE"]
        side : str, optional
            "BUY" or "SELL", by default None
        event_id : int, str or list, optional
            Event id(s) to filter by. Mutually exclusive with condition_id.
        condition_id : str or list, optional
            Market condition id(s) to filter by (up to 20). Mutually exclusive with event_id.
        get_all_data : bool, optional
            Whether to retrieve all pages, by default False
        start_date, end_date : str, optional
            Date range, parsed with date_format
        date_format : str, optional
            Format of the start and end dates, by default "%Y-%m-%d"
        add_datetime : bool, optional
            Whether to add 'utc' and 'est' datetime fields, by default True
        limit : int, optional
            Page size (max 1000), by default 500
        max_results : int, optional
            Stop after this many rows, by default None

        Returns
        -------
        list
            Activity rows
        """
        self._check_one_selector(condition_id, event_id)
        start_date, end_date = self._parse_date_inputs(start_date, end_date, date_format=date_format)
        params = {
            "user": address,
            "type": list(activity_type_list) if activity_type_list else None,
            "side": side.upper() if side else None,
            "event_id": event_id,
            "condition": condition_id,
            "start": start_date,
            "end": end_date,
        }
        data = self._paginate_data('/activity', params, get_all_data=get_all_data, limit=limit,
                                   max_results=max_results) or []
        return self._add_date_times(data) if add_datetime else data

    def get_current_positions_for_user(self, address, condition_id=None, event_id=None, status=None,
                                       size_threshold=1, size_threshold_type='TOKENS', sort_by='TOKENS',
                                       sort_direction='DESC', include_archived=None, get_all_data=False,
                                       limit=500, max_results=None):
        """
        Gets a user's positions (Data API v2).

        Parameters
        ----------
        address : str
            User wallet address (0x-prefixed, 40 hex chars)
        condition_id : str or list, optional
            Market condition id(s), up to 20. Mutually exclusive with event_id.
        event_id : int, str or list, optional
            Event id(s). Mutually exclusive with condition_id.
        status : str, optional
            OPEN, REDEEMABLE (resolved, won), REDEEMABLE_LOST (resolved, lost), MERGEABLE or CLOSED.
            By default None, which the API treats as OPEN.
        size_threshold : float, optional
            Minimum position size, by default 1
        size_threshold_type : str, optional
            'TOKENS' (shares) or 'CASH' (dollars) for size_threshold, by default 'TOKENS'
        sort_by : str, optional
            CURRENT_VALUE, PRICE, TOKENS, UNREALIZED_PNL, REALIZED_PNL, TOTAL_PNL or TIMESTAMP,
            by default 'TOKENS'
        sort_direction : str, optional
            'ASC' or 'DESC', by default 'DESC'
        include_archived : bool, optional
            Whether to include archived positions, by default None (API default)
        get_all_data : bool, optional
            Whether to retrieve all pages, by default False
        limit : int, optional
            Page size (max 1000), by default 500
        max_results : int, optional
            Stop after this many positions, by default None

        Returns
        -------
        list
            Positions. Key fields: token_id, condition_id, outcome, current_size, avg_price,
            total_cost_usdc, current_value, unrealized_pnl, realized_pnl, total_pnl, status, slug.
        """
        self._check_one_selector(condition_id, event_id)
        if status is not None and status.upper() not in POSITION_STATUSES:
            raise ValueError(f"status must be one of {POSITION_STATUSES}")
        if sort_by.upper() not in POSITION_SORT_FIELDS:
            raise ValueError(f"sort_by must be one of {POSITION_SORT_FIELDS}")
        params = {
            "user": address,
            "condition": condition_id,
            "event_id": event_id,
            "status": status.upper() if status else None,
            "filter_type": size_threshold_type.upper() if size_threshold else None,
            "filter_amount": size_threshold or None,
            "sort_by": sort_by.upper(),
            "sort_direction": sort_direction.upper(),
            "include_archived": include_archived,
        }
        return self._paginate_data('/positions', params, get_all_data=get_all_data, limit=limit,
                                   max_results=max_results) or []

    def get_trades(self, condition_id=None, event_id=None, user=None, side=None, min_trade_value=None,
                   min_trade_size=None, taker_only=None, start_date=None, end_date=None, date_format="%Y-%m-%d",
                   get_all_data=False, limit=100, max_results=None, add_datetime=False):
        """
        Gets trades, newest first (Data API v2). Each row includes the trader's proxy_wallet and the
        transaction_hash.

        Note: Polymarket's CDN caches identical trades queries for up to 5 minutes. When polling for new
        trades, vary the query (for example, pass a moving end_date) to get fresh results.

        Parameters
        ----------
        condition_id : str or list, optional
            Market condition id(s). Mutually exclusive with event_id.
        event_id : int, str or list, optional
            Event id(s). Mutually exclusive with condition_id.
        user : str, optional
            Only trades by this wallet address
        side : str, optional
            "BUY" or "SELL"
        min_trade_value : float, optional
            Only trades of at least this many dollars. Mutually exclusive with min_trade_size.
        min_trade_size : float, optional
            Only trades of at least this many shares. Mutually exclusive with min_trade_value.
        taker_only : bool, optional
            Only return the taker side of each match, by default None (API default)
        start_date, end_date : str, optional
            Date range, parsed with date_format
        get_all_data : bool, optional
            Whether to retrieve all pages, by default False
        limit : int, optional
            Page size (max 1000), by default 100
        max_results : int, optional
            Stop after this many trades, by default None
        add_datetime : bool, optional
            Whether to add 'utc' and 'est' datetime fields, by default False
        """
        self._check_one_selector(condition_id, event_id)
        if min_trade_value is not None and min_trade_size is not None:
            raise ValueError("Provide min_trade_value or min_trade_size, not both")
        start_date, end_date = self._parse_date_inputs(start_date, end_date, date_format=date_format)
        filter_type, filter_amount = None, None
        if min_trade_value is not None:
            filter_type, filter_amount = 'CASH', min_trade_value
        elif min_trade_size is not None:
            filter_type, filter_amount = 'TOKENS', min_trade_size
        params = {
            "condition": condition_id,
            "event_id": event_id,
            "user": user,
            "side": side.upper() if side else None,
            "filter_type": filter_type,
            "filter_amount": filter_amount,
            "taker_only": taker_only,
            "start": start_date,
            "end": end_date,
        }
        data = self._paginate_data('/trades', params, get_all_data=get_all_data, limit=limit,
                                   max_results=max_results) or []
        return self._add_date_times(data) if add_datetime else data

    def get_trader_from_transaction(self, tx_hash, condition_id, buy_or_sell=None, lookback=200,
                                    trade_timestamp=None):
        """
        Finds the trader (taker) behind a trade transaction using the Data API.

        The Data API has no lookup by transaction hash, so this searches the market's most recent trades.
        Trades are indexed a few seconds after they happen, so a very recent trade may not be found yet.
        Each call uses a distinct time window so retries aren't served a stale CDN-cached response
        (the trades endpoint is cached for up to 5 minutes).

        Parameters
        ----------
        tx_hash : str
            Transaction hash (0x-prefixed), e.g. from a websocket last_trade_price message
        condition_id : str
            The market condition id the trade happened in (the websocket message's 'market' field)
        buy_or_sell : str, optional
            'buy' or 'sell' to narrow the match, by default None
        lookback : int, optional
            How many of the market's most recent taker trades to search (max 1000), by default 200
        trade_timestamp : int, optional
            When the trade happened (unix seconds or milliseconds, like the websocket 'timestamp'). Narrows
            the search to trades from a minute before it, by default None (last hour)

        Returns
        -------
        dict or None
            {'trader', 'trader_name', 'trade', 'trades', 'trade_value'} or None if the trade wasn't found
        """
        tx_hash = tx_hash.lower()
        now = int(time.time())
        try:
            ts = int(float(trade_timestamp))
            ts = ts // 1000 if ts > 10 ** 12 else ts
        except (TypeError, ValueError):
            ts = now - 3600
        params = {
            "condition": condition_id,
            "taker_only": True,
            "start": ts - 60,
            "end": now + 1,   # changes every call, so retries bypass the CDN cache
        }
        trades = self._paginate_data('/trades', params, get_all_data=lookback > DATA_PAGE_LIMIT,
                                     limit=min(lookback, DATA_PAGE_LIMIT), max_results=lookback) or []
        matches = [t for t in trades if str(t.get('transaction_hash', '')).lower() == tx_hash]
        if buy_or_sell:
            matches = [t for t in matches if str(t.get('side', '')).upper() == buy_or_sell.upper()]
        if not matches:
            return None
        trade = matches[0]
        return {
            'trader': trade.get('proxy_wallet'),
            'trader_name': trade.get('name') or trade.get('pseudonym'),
            'trade': trade,
            'trades': matches,
            'trade_value': sum(float(t.get('size', 0)) * float(t.get('price', 0)) for t in matches),
        }

    ###############################
    # Websocket and monitoring
    ###############################
    def subscribe_to_markets(self, asset_ids, callback=None, custom_feature_enabled=False, initial_dump=True):
        """
        Subscribe to market updates via websocket for specific asset (token) ids. Does NOT require
        authentication. The connection runs on a background thread and reconnects automatically.

        Parameters
        ----------
        asset_ids : list
            Asset (token) ids to monitor
        callback : callable, optional
            Called with each message (a dict or a list of dicts). Prints messages if not provided.
        custom_feature_enabled : bool, optional
            Also receive best_bid_ask, new_market and market_resolved events, by default False
        initial_dump : bool, optional
            Whether to receive order book snapshots on connect, by default True

        Returns
        -------
        MarketWebSocket
            The running connection; call .stop() to close it.

        Example
        -------
        ws = pm.subscribe_to_markets(["1096819599459733004645686984029682..."], callback=print)
        """
        return MarketWebSocket(self.ws_url, asset_ids, callback, custom_feature_enabled=custom_feature_enabled,
                               initial_dump=initial_dump).start()

    def get_asset_map(self, markets):
        """
        Resolves event slugs, market slugs or condition ids to their outcome tokens.

        Returns
        -------
        dict
            asset_id -> {'question', 'outcome', 'condition_id', 'slug', 'event_slug'}
        """
        asset_map = {}
        for identifier in markets:
            identifier = str(identifier).strip()
            found, event_slug = [], None
            if identifier.startswith('0x') and len(identifier) == 66:
                found = self.get_markets(condition_ids=identifier, active_only=False, include_closed=True,
                                         get_all_data=False)
            else:
                event = self.get_event_by_slug(identifier)
                if event:
                    found, event_slug = event.get('markets', []), event.get('slug')
                else:
                    market = self.get_market_by_slug(identifier)
                    found = [market] if market else []
            if not found:
                logger.warning("No market found for %s", identifier)
            for market in found:
                tokens = self._json_list(market.get('clobTokenIds'))
                outcomes = self._json_list(market.get('outcomes'))
                for asset_id, outcome in zip(tokens, outcomes):
                    asset_map[str(asset_id)] = {
                        'question': market.get('question'),
                        'outcome': outcome,
                        'condition_id': market.get('conditionId'),
                        'slug': market.get('slug'),
                        'event_slug': event_slug,
                    }
        return asset_map

    def monitor_market_for_whales(self, markets=None, asset_ids=None, min_trade_size=1000, min_trade_value=None,
                                  callback=None, lookup_trader=True, find_trader_retries=5):
        """
        Monitor markets for large trades ("whale" activity) via the public websocket.

        Matching trades are handled on a worker thread so the websocket never blocks. Each trade passed to
        the callback includes trade_value, question/outcome (when known) and the trader's wallet
        (when lookup_trader is True and the trade is indexed in time). See WhaleMonitor.

        Parameters
        ----------
        markets : list, optional
            Event slugs, market slugs or condition ids to monitor.
        asset_ids : list, optional
            Asset (token) ids to monitor, if you already have them.
        min_trade_size : float, optional
            Minimum number of shares for a trade to count, by default 1000
        min_trade_value : float, optional
            Minimum dollar value (size * price). If provided, overrides min_trade_size.
        callback : callable, optional
            Called with each whale trade dict. Prints the trade if not provided.
        lookup_trader : bool, optional
            Whether to look up the trader's wallet via the Data API, by default True
        find_trader_retries : int, optional
            Retries for the trader lookup while the trade is being indexed (backoff 3s..15s), by default 5

        Returns
        -------
        WhaleMonitor
            The running monitor; call .stop() to stop it.

        Example
        -------
        monitor = pm.monitor_market_for_whales(markets=["fed-decision-in-january"], min_trade_value=5000)
        """
        if asset_ids is None and markets is None:
            raise ValueError("Must provide either 'markets' or 'asset_ids'")

        asset_map = self.get_asset_map(markets) if markets is not None else {}
        ids = list(asset_ids or []) + [a for a in asset_map if a not in set(asset_ids or [])]
        if not ids:
            raise ValueError(f"Could not find asset ids for markets: {markets}")
        logger.info("Monitoring %d assets for large trades", len(ids))

        return WhaleMonitor(self, ids, asset_info=asset_map, min_trade_size=min_trade_size,
                            min_trade_value=min_trade_value, callback=callback, lookup_trader=lookup_trader,
                            find_trader_retries=find_trader_retries, ws_url=self.ws_url).start()

    def monitor_user_positions(self, address, poll_interval=60, callback=None, stop_event=None,
                               size_threshold=0.01):
        """
        Monitor a user's open positions by polling the Data API.

        By default changes are printed. A custom callback receives (address, positions, changes); see
        PositionMonitor for the shape of changes. If a poll fails, the error is logged and no changes are
        reported for that poll.

        Parameters
        ----------
        address : str
            The wallet address to monitor
        poll_interval : int, optional
            Seconds between polls, by default 60
        callback : callable, optional
            Called after every poll with (address, positions, changes)
        stop_event : threading.Event, optional
            Event that stops the monitor when set. You can also call .stop() on the returned monitor.
        size_threshold : float, optional
            Minimum position size in shares, by default 0.01

        Returns
        -------
        PositionMonitor
            The running monitor (a threading.Thread).
        """
        monitor = PositionMonitor(self, address, poll_interval=poll_interval, callback=callback,
                                  stop_event=stop_event, size_threshold=size_threshold)
        monitor.start()
        return monitor


class PolymarketAuth(Polymarket):
    """
    Extends Polymarket with an authenticated trading client from Polymarket's unified SDK
    (``polymarket-client``), available as ``self.api``. Install it with
    ``pip install "lukhed_markets[polymarket-trading]"`` (Python 3.11+).

    Credentials are a wallet private key and (optionally) the Polymarket wallet address that holds your
    funds. They are stored with lukhed key management (github or local) under the project name
    'polymarketClobApi', or you can pass them directly with auth_data.

    Parameters
    ----------
    api_delay : float, optional
        Minimum seconds between public API requests, by default 0.1
    key_management : str, optional
        'github' or 'local', by default 'github'
    auth_data : dict, optional
        {'private_key': ..., 'wallet': ...} to skip key management entirely, by default None
    interactive_setup : bool, optional
        If no stored credentials exist and this is an interactive terminal, run the guided setup,
        by default True. Otherwise a RuntimeError is raised.

    Example
    -------
    pm = PolymarketAuth()
    print(pm.api.get_balance_allowance(...))   # see the unified SDK docs for trading methods
    """
    def __init__(self, api_delay=0.1, key_management='github', auth_data=None, interactive_setup=True, **kwargs):
        super().__init__(api_delay=api_delay, **kwargs)
        self._key_management = key_management
        self._lukhed_auth = None
        self.kM = None

        if auth_data is None:
            self._lukhed_auth = LukhedAuth(project_name='polymarketClobApi', key_management=key_management)
            self.kM = self._lukhed_auth.kM
            auth_data = self._lukhed_auth._auth_data
            if auth_data is None:
                if not (interactive_setup and sys.stdin is not None and sys.stdin.isatty()):
                    raise RuntimeError(
                        "No stored Polymarket credentials. Run PolymarketAuth() once from an interactive terminal "
                        "to set them up, or pass auth_data={'private_key': ..., 'wallet': ...}.")
                auth_data = self._polymarket_api_setup()

        self._auth_data = self._normalize_auth_data(auth_data)
        self.api = self._create_client()

    @staticmethod
    def _normalize_auth_data(auth_data):
        """Accepts the current format and the pre-0.4 format ('key'/'address'/'signature_type')."""
        private_key = auth_data.get('private_key') or auth_data.get('key')
        wallet = auth_data.get('wallet') or auth_data.get('address') or None
        if not private_key:
            raise ValueError("Polymarket auth data needs a 'private_key'")
        return {'private_key': private_key, 'wallet': wallet}

    def _create_client(self):
        try:
            from polymarket import SecureClient
        except ImportError as e:
            raise ImportError(
                "PolymarketAuth needs Polymarket's unified SDK. Install it with "
                "pip install \"lukhed_markets[polymarket-trading]\" (requires Python 3.11+).") from e
        client = SecureClient.create(private_key=self._auth_data['private_key'], wallet=self._auth_data['wallet'])
        logger.info("Polymarket trading client ready for wallet %s", client.wallet)
        return client

    def close(self):
        """Close the trading client's connections."""
        if getattr(self, 'api', None) is not None:
            self.api.close()

    def _polymarket_api_setup(self):
        """Guided first-time setup. Stores credentials with lukhed key management and returns them."""
        print("\n\n***********************************\n"
              "This is the lukhed setup for the Polymarket trading client.\n"
              f"The data you provide will be stored based on your key management parameter ({self._key_management}).\n\n"
              "You need:\n"
              "- The private key of the wallet that signs your orders.\n"
              "    Email (Magic) accounts: export it at https://reveal.magic.link/polymarket\n"
              "    MetaMask/hardware wallets: export it from your wallet.\n"
              "- Your Polymarket wallet address (shown on your Polymarket profile). Leave it blank to let the\n"
              "  SDK use the default deposit wallet for your key.\n\n"
              "WARNING: your private key will be stored as plain text on this machine or in your private github\n"
              "repo, depending on key management. Make sure you understand the security implications.\n\n"
              "Help: https://docs.polymarket.com/trading/quickstart")

        if input("\nAre you ready to continue (y/n)? ").strip().lower() != 'y':
            raise RuntimeError("Polymarket setup cancelled")

        private_key = getpass.getpass("Private key (input hidden): ").strip()
        wallet = input("Polymarket wallet address (blank for default): ").strip() or None
        auth_data = {"private_key": private_key, "wallet": wallet}

        self.kM.force_update_key_data(auth_data)
        print("Setup complete!")
        return auth_data
