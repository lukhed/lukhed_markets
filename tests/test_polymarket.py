"""Offline tests for the Polymarket wrapper. No network access: HTTP goes through a fake session."""
import sys
import threading
import types

import pytest

from lukhed_markets import polymarket as pm_module
from lukhed_markets.polymarket import Polymarket, PolymarketAuth, PolymarketAPIError
from lukhed_markets.polymarket_realtime import MarketWebSocket, PositionMonitor, WhaleMonitor


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=None, headers=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text if text is not None else ('' if json_data is None else str(json_data))
        self.headers = headers or {}

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeSession:
    """Returns queued responses (or calls a handler) and records every request."""
    def __init__(self, responses=None, handler=None):
        self.responses = list(responses or [])
        self.handler = handler
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        if self.handler:
            return self.handler(url, params or {})
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(pm_module.time, 'sleep', lambda s: None)


def client(session):
    return Polymarket(api_delay=0, session=session)


###############################
# Transport
###############################
def test_clean_params_drops_none_and_formats_values():
    assert Polymarket._clean_params({'a': None, 'b': True, 'c': False, 'd': ['x', 1], 'e': 5}) == \
        {'b': 'true', 'c': 'false', 'd': 'x,1', 'e': 5}


def test_request_retries_429_then_succeeds():
    session = FakeSession([FakeResponse(429, {'error': 'slow down'}, headers={'Retry-After': '2'}),
                           FakeResponse(200, {'ok': 1})])
    assert client(session)._request('https://x/y') == {'ok': 1}
    assert len(session.calls) == 2


def test_request_raises_on_retired_endpoint():
    session = FakeSession([FakeResponse(410, {'error': 'Data API v1 has been retired'})])
    with pytest.raises(PolymarketAPIError) as exc:
        client(session)._request('https://x/positions')
    assert exc.value.status_code == 410
    assert 'retired' in str(exc.value)


def test_request_gives_up_after_max_retries():
    session = FakeSession(handler=lambda url, params: FakeResponse(503, {'error': 'down'}))
    with pytest.raises(PolymarketAPIError):
        client(session)._request('https://x')
    assert len(session.calls) == 4  # first try + 3 retries


def test_request_404_returns_none_when_allowed():
    session = FakeSession([FakeResponse(404, {'error': 'not found'})])
    assert client(session)._request('https://x', allow_404=True) is None


###############################
# Pagination
###############################
def test_data_pagination_follows_cursor_and_never_sends_offset():
    pages = {None: (['a', 'b'], 'c1'), 'c1': (['c', 'd'], 'c2'), 'c2': (['e'], None)}

    def handler(url, params):
        rows, nxt = pages[params.get('cursor')]
        return FakeResponse(200, {'data': rows, 'pagination': {'next_cursor': nxt}})

    session = FakeSession(handler=handler)
    assert client(session)._paginate_data('/activity', {'user': 'u'}, get_all_data=True, limit=2) == \
        ['a', 'b', 'c', 'd', 'e']
    assert all('offset' not in params for _, params in session.calls)
    assert session.calls[0][0] == 'https://data-api.polymarket.com/v2/activity'


def test_data_pagination_respects_max_results():
    def handler(url, params):
        return FakeResponse(200, {'data': list(range(params['limit'])), 'pagination': {'next_cursor': 'more'}})

    session = FakeSession(handler=handler)
    assert len(client(session)._paginate_data('/trades', get_all_data=True, limit=1000, max_results=1500)) == 1500
    assert [params['limit'] for _, params in session.calls] == [1000, 500]


def test_data_pagination_returns_dict_payloads():
    session = FakeSession([FakeResponse(200, {'data': {'pnl': 1}})])
    assert client(session)._paginate_data('/leaderboard') == {'pnl': 1}


def test_gamma_keyset_pagination():
    pages = {None: ([1, 2], 'k1'), 'k1': ([3], None)}

    def handler(url, params):
        items, nxt = pages[params.get('after_cursor')]
        return FakeResponse(200, {'markets': items, 'next_cursor': nxt})

    session = FakeSession(handler=handler)
    assert client(session)._paginate_gamma_keyset('/markets/keyset', 'markets', get_all_data=True) == [1, 2, 3]


def test_gamma_offset_pagination_advances_by_rows_received():
    # Gamma caps pages at 100 even when more are requested, so offsets must follow what came back.
    data = list(range(250))

    def handler(url, params):
        return FakeResponse(200, data[params['offset']:params['offset'] + 100])

    session = FakeSession(handler=handler)
    assert client(session)._paginate_gamma_offset('/tags', get_all_data=True) == data
    assert [params['offset'] for _, params in session.calls] == [0, 100, 200, 250]


###############################
# Endpoint methods
###############################
def test_get_markets_include_closed_queries_open_and_closed():
    def handler(url, params):
        return FakeResponse(200, {'markets': [params['closed']], 'next_cursor': None})

    session = FakeSession(handler=handler)
    assert client(session).get_markets(include_closed=True) == ['false', 'true']
    assert all(url.endswith('/markets/keyset') for url, _ in session.calls)


def test_unknown_tag_raises_instead_of_silently_unfiltering():
    session = FakeSession([FakeResponse(404, {'error': 'slug not found'})])
    with pytest.raises(ValueError):
        client(session).get_markets(tag_filter='not-a-tag')


def test_tag_slug_lookup_is_cached():
    session = FakeSession(handler=lambda url, params: FakeResponse(200, {'id': '2'}))
    pm = client(session)
    assert pm._resolve_tag_id('Politics') == '2'
    assert pm._resolve_tag_id('politics') == '2'
    assert len(session.calls) == 1


def test_positions_maps_parameters_to_v2():
    session = FakeSession([FakeResponse(200, {'data': [], 'pagination': {'next_cursor': None}})])
    client(session).get_current_positions_for_user('0xabc', condition_id=['c1', 'c2'], status='closed',
                                                   size_threshold=5)
    url, params = session.calls[0]
    assert url.endswith('/v2/positions')
    assert params['condition'] == 'c1,c2'
    assert params['status'] == 'CLOSED'
    assert (params['filter_type'], params['filter_amount']) == ('TOKENS', 5)
    assert 'market' not in params


def test_positions_rejects_conflicting_selectors():
    with pytest.raises(ValueError):
        client(FakeSession()).get_current_positions_for_user('0xabc', condition_id='c', event_id='e')


def test_leaderboard_single_user_returns_standing():
    session = FakeSession([FakeResponse(200, {'data': {'rank_pnl': 7}})])
    assert client(session).get_leaderboards(single_user_check='0xabc') == {'rank_pnl': 7}
    assert session.calls[0][1]['time_period'] == 'all'


def test_leaderboard_validates_inputs():
    pm = client(FakeSession())
    with pytest.raises(ValueError):
        pm.get_leaderboards(time_period='year')
    with pytest.raises(ValueError):
        pm.get_leaderboards(rank_by='likes')
    with pytest.raises(ValueError):
        pm.get_leaderboards(single_user_check='bob', user_identifier='username')


def test_trader_from_transaction_matches_hash():
    rows = [{'transaction_hash': '0xAAA', 'proxy_wallet': '0x1', 'name': 'whale', 'size': 10, 'price': 0.5},
            {'transaction_hash': '0xbbb', 'proxy_wallet': '0x2', 'size': 1, 'price': 0.5}]
    session = FakeSession([FakeResponse(200, {'data': rows, 'pagination': {'next_cursor': None}})])
    result = client(session).get_trader_from_transaction('0xaaa', condition_id='0xcond',
                                                         trade_timestamp=1_700_000_000_000)
    assert result['trader'] == '0x1'
    assert result['trader_name'] == 'whale'
    assert result['trade_value'] == 5
    params = session.calls[0][1]
    assert params['taker_only'] == 'true'
    assert params['start'] == 1_700_000_000 - 60  # millisecond websocket timestamps are converted


def test_trader_lookup_retries_use_distinct_urls(monkeypatch):
    # The trades endpoint is CDN-cached for minutes, so each retry must change the query string.
    clock = iter([1000, 1004])
    monkeypatch.setattr(pm_module.time, 'time', lambda: next(clock))
    session = FakeSession(handler=lambda url, params: FakeResponse(200, {'data': [], 'pagination': {}}))
    pm = client(session)
    pm.get_trader_from_transaction('0xaaa', condition_id='0xcond', trade_timestamp=990)
    pm.get_trader_from_transaction('0xaaa', condition_id='0xcond', trade_timestamp=990)
    assert session.calls[0][1] != session.calls[1][1]


def test_trader_from_transaction_returns_none_when_not_indexed():
    session = FakeSession([FakeResponse(200, {'data': [], 'pagination': {'next_cursor': None}})])
    assert client(session).get_trader_from_transaction('0xaaa', condition_id='0xcond') is None


def test_comments_reject_market_entity():
    with pytest.raises(ValueError):
        client(FakeSession()).list_comments('Market', '1')


###############################
# Realtime
###############################
class FakeClient:
    def __init__(self, polls):
        self.polls = list(polls)

    def get_current_positions_for_user(self, address, status=None, **kwargs):
        if status == 'OPEN':
            result = self.polls.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        if status == 'CLOSED':
            return [{'token_id': 't2', 'status': 'CLOSED', 'realized_pnl': 12}]
        return []

    def get_user_activity(self, *args, **kwargs):
        return [{'type': 'TRADE', 'side': 'SELL'}]

    def get_trader_from_transaction(self, tx_hash, condition_id, trade_timestamp=None):
        return {'trader': '0xwhale', 'trader_name': 'Whale', 'trade': {'transaction_hash': tx_hash}}


def pos(token, size, value=1):
    return {'token_id': token, 'condition_id': 'c-' + token, 'outcome': 'Yes', 'current_size': size,
            'current_value': value}


def test_position_monitor_diffs_and_survives_api_errors():
    fake = FakeClient([
        [pos('t1', 10), pos('t2', 5)],
        PolymarketAPIError('boom', status_code=500),
        [pos('t1', 12), pos('t3', 1)],
    ])
    calls = []
    monitor = PositionMonitor(fake, '0xuser', callback=lambda a, p, c: calls.append(c))

    first = monitor.poll_once()
    assert first['initial'] and not first['new']

    assert monitor.poll_once() is None  # failed poll: no callback, snapshot kept
    assert len(calls) == 1

    third = monitor.poll_once()
    assert [p['token_id'] for p in third['new']] == ['t3']
    assert third['changed'][0]['old_size'] == 10 and third['changed'][0]['new_size'] == 12
    closed = third['closed'][0]
    assert closed['position']['token_id'] == 't2'
    assert closed['reason'] == 'CLOSED'
    assert closed['final_position']['realized_pnl'] == 12
    assert closed['activity']


def test_whale_monitor_filters_and_enriches():
    got = []
    monitor = WhaleMonitor(FakeClient([]), ['a1'], asset_info={'a1': {'question': 'Q?', 'outcome': 'Yes'}},
                           min_trade_value=100, callback=got.append, retry_delay=0)
    monitor._on_ws_message([
        {'event_type': 'book'},
        {'event_type': 'last_trade_price', 'asset_id': 'a1', 'size': '10', 'price': '0.5'},  # $5: ignored
        {'event_type': 'last_trade_price', 'asset_id': 'a1', 'size': '1000', 'price': '0.5', 'side': 'BUY',
         'transaction_hash': '0xtx', 'market': '0xcond'},
    ])
    assert monitor._queue.qsize() == 1
    trade = monitor._enrich(monitor._queue.get())
    assert trade['trade_value'] == 500
    assert trade['question'] == 'Q?' and trade['outcome'] == 'Yes'
    assert trade['trader'] == '0xwhale' and trade['trader_name'] == 'Whale'


def test_market_websocket_tracks_subscriptions_before_connect():
    received = []
    ws = MarketWebSocket('wss://example', ['a', 'a', 'b'], received.append)
    assert ws.endpoint == 'wss://example/ws/market'
    assert ws.asset_ids == ['a', 'b']
    ws.subscribe_to_assets(['b', 'c'])
    ws.unsubscribe_from_assets(['a'])
    assert ws.asset_ids == ['b', 'c']
    ws._on_message(None, 'PONG')
    ws._on_message(None, '{"event_type": "book"}')
    assert received == [{'event_type': 'book'}]


###############################
# Auth
###############################
def test_auth_normalizes_legacy_credentials():
    legacy = {'key': '0xkey', 'address': '0xwallet', 'signature_type': 1, 'private_key': None}
    assert PolymarketAuth._normalize_auth_data(legacy) == {'private_key': '0xkey', 'wallet': '0xwallet'}
    with pytest.raises(ValueError):
        PolymarketAuth._normalize_auth_data({'address': '0xwallet'})


def test_auth_builds_sdk_client(monkeypatch):
    created = {}

    class FakeSecureClient:
        wallet = '0xwallet'

        @classmethod
        def create(cls, **kwargs):
            created.update(kwargs)
            return cls()

    monkeypatch.setitem(sys.modules, 'polymarket', types.SimpleNamespace(SecureClient=FakeSecureClient))
    auth = PolymarketAuth(auth_data={'private_key': '0xkey', 'wallet': '0xwallet'}, api_delay=0)
    assert isinstance(auth.api, FakeSecureClient)
    assert created == {'private_key': '0xkey', 'wallet': '0xwallet'}


def test_auth_without_sdk_explains_install(monkeypatch):
    monkeypatch.setitem(sys.modules, 'polymarket', None)
    with pytest.raises(ImportError, match='polymarket-trading'):
        PolymarketAuth(auth_data={'private_key': '0xkey'}, api_delay=0)


def test_auth_never_prompts_when_not_interactive(monkeypatch):
    class FakeLukhedAuth:
        def __init__(self, **kwargs):
            self.kM = None
            self._auth_data = None

    monkeypatch.setattr(pm_module, 'LukhedAuth', FakeLukhedAuth)
    monkeypatch.setattr(sys, 'stdin', None)
    with pytest.raises(RuntimeError, match='No stored Polymarket credentials'):
        PolymarketAuth(api_delay=0)
