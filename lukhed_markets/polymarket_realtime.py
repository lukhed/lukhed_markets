"""
Real-time Polymarket tools: the public market websocket and the monitors built on top of it.

- MarketWebSocket: reconnecting client for Polymarket's public market channel.
- WhaleMonitor: watches the market channel for large trades and identifies the trader.
- PositionMonitor: polls a user's positions and reports new / changed / closed positions.

The monitors take a ``Polymarket`` client instance for REST lookups. They never block the websocket
thread: trade enrichment and user callbacks run on a separate worker thread.
"""
import json
import logging
import queue
import threading
import time

from websocket import WebSocketApp

logger = logging.getLogger(__name__)

MARKET_WS_URL = 'wss://ws-subscriptions-clob.polymarket.com'


class MarketWebSocket:
    """
    Websocket connection to Polymarket's public market channel. Does NOT require authentication.

    Sends the text heartbeat ("PING" every 10s) the channel requires and reconnects automatically,
    re-subscribing to every asset added so far. Call ``start()`` to run it on a background thread,
    or ``run()`` to block the current thread. Call ``stop()`` to shut it down.

    https://docs.polymarket.com/market-data/websocket/market-channel
    """
    def __init__(self, url, asset_ids, message_callback=None, custom_feature_enabled=False, initial_dump=True,
                 ping_interval=10, reconnect=True, max_reconnect_delay=60, raw_message_filter=None):
        self.url = url.rstrip('/')
        self.endpoint = self.url if self.url.endswith('/ws/market') else self.url + '/ws/market'
        self.asset_ids = list(dict.fromkeys(str(a) for a in asset_ids))
        self.message_callback = message_callback
        self.custom_feature_enabled = custom_feature_enabled
        self.initial_dump = initial_dump
        self.ping_interval = ping_interval
        self.reconnect = reconnect
        self.max_reconnect_delay = max_reconnect_delay
        # Optional predicate on the raw message text. Messages it rejects are dropped before JSON parsing,
        # which keeps up with busy markets (the server disconnects clients that read too slowly).
        self.raw_message_filter = raw_message_filter

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._ws = None
        self._thread = None

    @property
    def ws(self):
        """The current underlying WebSocketApp (replaced on every reconnect)."""
        return self._ws

    @property
    def is_connected(self):
        return self._connected.is_set()

    def start(self):
        """Run the connection on a daemon thread and return self."""
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self.run, daemon=True, name='polymarket-market-ws')
            self._thread.start()
        return self

    def run(self):
        """Connect and process messages until ``stop()`` is called. Blocks the calling thread."""
        delay = 1
        while not self._stop.is_set():
            self._ws = WebSocketApp(
                self.endpoint,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            started = time.monotonic()
            try:
                self._ws.run_forever()
            except Exception:
                logger.exception("Market websocket crashed")
            self._connected.clear()

            if self._stop.is_set() or not self.reconnect:
                break
            if time.monotonic() - started > 60:
                delay = 1  # the last connection was healthy, so start backing off from scratch
            logger.warning("Market websocket disconnected, reconnecting in %ss", delay)
            self._stop.wait(delay)
            delay = min(delay * 2, self.max_reconnect_delay)

    def stop(self, timeout=5):
        """Close the connection and stop reconnecting."""
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    def subscribe_to_assets(self, new_asset_ids):
        """Subscribe to additional assets. Safe to call before the connection is open."""
        new_ids = [str(a) for a in new_asset_ids]
        with self._lock:
            added = [a for a in new_ids if a not in self.asset_ids]
            self.asset_ids.extend(added)
        if added and self.is_connected:
            self._send({"assets_ids": added, "operation": "subscribe"})
        logger.info("Subscribed to %d additional asset(s)", len(added))

    def unsubscribe_from_assets(self, asset_ids_to_remove):
        """Unsubscribe from specific assets."""
        remove = {str(a) for a in asset_ids_to_remove}
        with self._lock:
            self.asset_ids = [a for a in self.asset_ids if a not in remove]
        if remove and self.is_connected:
            self._send({"assets_ids": list(remove), "operation": "unsubscribe"})
        logger.info("Unsubscribed from %d asset(s)", len(remove))

    def _send(self, payload):
        ws = self._ws
        if ws is None:
            return
        try:
            ws.send(json.dumps(payload))
        except Exception as e:
            logger.warning("Could not send websocket message: %s", e)

    def _on_open(self, ws):
        self._connected.set()
        with self._lock:
            ids = list(self.asset_ids)
        message = {"assets_ids": ids, "type": "market"}
        if self.custom_feature_enabled:
            message["custom_feature_enabled"] = True
        if not self.initial_dump:
            message["initial_dump"] = False
        ws.send(json.dumps(message))
        logger.info("Market websocket connected, monitoring %d asset(s)", len(ids))
        threading.Thread(target=self._ping_loop, args=(ws,), daemon=True, name='polymarket-market-ws-ping').start()

    def _ping_loop(self, ws):
        # Each connection gets its own ping loop, which exits once that connection is replaced or closed.
        while not self._stop.is_set() and self._ws is ws and self._connected.is_set():
            try:
                ws.send("PING")
            except Exception:
                break
            self._stop.wait(self.ping_interval)

    def _on_message(self, ws, message):
        if message == "PONG":
            return
        if self.raw_message_filter is not None and not self.raw_message_filter(message):
            return
        try:
            data = json.loads(message)
        except (TypeError, ValueError):
            logger.debug("Ignoring non-JSON websocket message: %r", message)
            return
        try:
            if self.message_callback:
                self.message_callback(data)
            else:
                print(f"Market update: {json.dumps(data, indent=2)}")
        except Exception:
            logger.exception("Error in market websocket callback")

    def _on_error(self, ws, error):
        logger.warning("Market websocket error: %s", error)

    def _on_close(self, ws, close_status_code, close_msg):
        self._connected.clear()
        logger.info("Market websocket closed: %s %s", close_status_code, close_msg)


class WhaleMonitor:
    """
    Watches the market channel for trades over a size or dollar threshold.

    Matching trades are queued and handled on a worker thread, which (optionally) looks up the trader's
    wallet through the Data API and then calls ``callback(trade)``. ``trade`` is the websocket
    ``last_trade_price`` message plus these keys:

    - trade_value: size * price, in dollars
    - question, outcome, slug, event_slug: market details when known
    - trader, trader_name, data_api_trade: the taker's wallet, display name and full Data API trade
      row (None when the lookup is disabled or the trade isn't indexed in time)
    """
    def __init__(self, client, asset_ids, asset_info=None, min_trade_size=1000, min_trade_value=None,
                 callback=None, lookup_trader=True, find_trader_retries=5, retry_delay=3, max_retry_delay=15,
                 ws_url=MARKET_WS_URL):
        self.client = client
        self.asset_info = asset_info or {}
        self.min_trade_size = min_trade_size
        self.min_trade_value = min_trade_value
        self.callback = callback or print_whale_trade
        self.lookup_trader = lookup_trader
        self.find_trader_retries = find_trader_retries
        self.retry_delay = retry_delay
        self.max_retry_delay = max_retry_delay

        self._queue = queue.Queue()
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._work, daemon=True, name='polymarket-whale-worker')
        # Only trades matter here: skip the order book snapshots and drop every other message unparsed.
        self.ws = MarketWebSocket(ws_url, asset_ids, self._on_ws_message, initial_dump=False,
                                  raw_message_filter=lambda m: 'last_trade_price' in m)

    def start(self):
        self._worker.start()
        self.ws.start()
        return self

    def stop(self):
        self._stop.set()
        self.ws.stop()
        self._queue.put(None)

    def is_whale(self, size, price):
        if self.min_trade_value is not None:
            return size * price >= self.min_trade_value
        return size >= self.min_trade_size

    def _on_ws_message(self, data):
        # Runs on the websocket thread: filter only, never block here.
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict) or item.get('event_type') != 'last_trade_price':
                continue
            try:
                size = float(item.get('size', 0))
                price = float(item.get('price', 0))
            except (TypeError, ValueError):
                continue
            if self.is_whale(size, price):
                self._queue.put(item)

    def _work(self):
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:
                break
            try:
                self.callback(self._enrich(item))
            except Exception:
                logger.exception("Error handling whale trade")

    def _enrich(self, item):
        trade = dict(item)
        trade['trade_value'] = float(item.get('size', 0)) * float(item.get('price', 0))
        info = self.asset_info.get(str(item.get('asset_id')), {})
        for key in ('question', 'outcome', 'slug', 'event_slug'):
            trade.setdefault(key, info.get(key))
        trade['trader'] = None
        trade['trader_name'] = None
        trade['data_api_trade'] = None

        tx_hash = item.get('transaction_hash')
        condition_id = item.get('market')
        if not (self.lookup_trader and tx_hash and condition_id):
            return trade

        # The Data API indexes trades seconds to a minute after they hit the websocket, so wait and retry
        # with backoff (3, 6, 12, 15, 15... seconds by default).
        for attempt in range(self.find_trader_retries + 1):
            if self._stop.wait(min(self.retry_delay * 2 ** attempt, self.max_retry_delay)):
                break
            try:
                result = self.client.get_trader_from_transaction(tx_hash, condition_id=condition_id,
                                                                 trade_timestamp=item.get('timestamp'))
            except Exception as e:
                logger.warning("Trader lookup failed (attempt %d): %s", attempt + 1, e)
                continue
            if result:
                trade['trader'] = result['trader']
                trade['trader_name'] = result['trader_name']
                trade['data_api_trade'] = result['trade']
                break
        else:
            logger.info("Trade %s not indexed after %d attempts", tx_hash, self.find_trader_retries + 1)
        return trade


class PositionMonitor(threading.Thread):
    """
    Polls a user's open positions and reports changes. Runs as a daemon thread (start it with ``start()``).

    ``callback(address, positions, changes)`` is called after every poll. ``changes`` is a dict:

    - initial: True on the first poll (no diff yet)
    - new: positions that appeared since the last poll
    - changed: dicts with condition_id, outcome, old_size, new_size, old_value, new_value, position,
      last_position
    - closed: dicts with position (the last open snapshot), reason (CLOSED, REDEEMABLE, REDEEMABLE_LOST or
      None if unknown), final_position (the Data API row in that status, with realized P&L), and
      activity (recent TRADE/REDEEM/MERGE/CONVERSION activity in that market)

    If a poll fails, the error is logged, the previous snapshot is kept, and no changes are reported,
    so an API outage never looks like every position closing.
    """
    CLOSED_STATUSES = ('CLOSED', 'REDEEMABLE', 'REDEEMABLE_LOST')

    def __init__(self, client, address, poll_interval=60, callback=None, stop_event=None, size_threshold=0.01):
        super().__init__(daemon=True, name=f'polymarket-positions-{address[:10]}')
        self.client = client
        self.address = address
        self.poll_interval = poll_interval
        self.callback = callback or print_position_changes
        self.stop_event = stop_event or threading.Event()
        self.size_threshold = size_threshold
        self.last_positions = None

    def stop(self):
        self.stop_event.set()

    @staticmethod
    def position_key(position):
        return position.get('token_id') or f"{position.get('condition_id')}_{position.get('outcome_index')}"

    def run(self):
        logger.info("Monitoring positions for %s (polling every %ss)", self.address, self.poll_interval)
        while not self.stop_event.is_set():
            try:
                self.poll_once()
            except Exception:
                logger.exception("Error monitoring positions for %s", self.address)
            self.stop_event.wait(self.poll_interval)

    def poll_once(self):
        try:
            positions = self.client.get_current_positions_for_user(
                self.address, status='OPEN', size_threshold=self.size_threshold, get_all_data=True)
        except Exception as e:
            logger.warning("Position poll failed for %s, keeping previous snapshot: %s", self.address, e)
            return None

        current = {self.position_key(p): p for p in positions}
        if self.last_positions is None:
            changes = {'initial': True, 'new': [], 'changed': [], 'closed': []}
        else:
            changes = self._diff(self.last_positions, current)
        self.last_positions = current
        self.callback(self.address, positions, changes)
        return changes

    def _diff(self, last, current):
        changes = {'initial': False, 'new': [], 'changed': [], 'closed': []}
        for key, pos in current.items():
            old = last.get(key)
            if old is None:
                changes['new'].append(pos)
            elif abs(_num(pos.get('current_size')) - _num(old.get('current_size'))) > 1e-9:
                changes['changed'].append({
                    'condition_id': pos.get('condition_id'),
                    'outcome': pos.get('outcome'),
                    'old_size': _num(old.get('current_size')),
                    'new_size': _num(pos.get('current_size')),
                    'old_value': _num(old.get('current_value')),
                    'new_value': _num(pos.get('current_value')),
                    'position': pos,
                    'last_position': old,
                })
        for key, pos in last.items():
            if key not in current:
                changes['closed'].append(self._describe_closed(key, pos))
        return changes

    def _describe_closed(self, key, pos):
        closed = {'position': pos, 'reason': None, 'final_position': None, 'activity': None}
        condition_id = pos.get('condition_id')
        if not condition_id:
            return closed
        try:
            for status in self.CLOSED_STATUSES:
                rows = self.client.get_current_positions_for_user(
                    self.address, condition_id=condition_id, status=status, size_threshold=0)
                match = next((r for r in rows if self.position_key(r) == key), None)
                if match:
                    closed['reason'] = status
                    closed['final_position'] = match
                    break
            closed['activity'] = self.client.get_user_activity(
                self.address, activity_type_list=['TRADE', 'REDEEM', 'MERGE', 'CONVERSION'],
                condition_id=condition_id, max_results=50)
        except Exception as e:
            logger.warning("Could not fetch closing details for %s: %s", condition_id, e)
        return closed


def _num(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


###############################
# Default (print) callbacks
###############################
def print_whale_trade(trade):
    """Default WhaleMonitor callback: print the trade."""
    if trade.get('question'):
        market = f"{trade['question']} - {trade.get('outcome')}"
    else:
        market = f"Market ID: {trade.get('market', 'Unknown')}"
    size = _num(trade.get('size'))
    price = _num(trade.get('price'))
    print(f"\n{'=' * 60}")
    print(f"🐋 WHALE ALERT: ${trade.get('trade_value', size * price):,.0f} trade!")
    print(f"{'=' * 60}")
    print(f"Market: {market}")
    print(f"Side: {trade.get('side')}")
    print(f"Size: {size:,.0f} shares @ ${price:.3f}")
    print(f"Time: {trade.get('timestamp', 'Unknown')}")
    if trade.get('trader'):
        name = f" ({trade['trader_name']})" if trade.get('trader_name') else ""
        print(f"Trader: https://polymarket.com/profile/{trade['trader']}{name}")
    if trade.get('transaction_hash'):
        print(f"Tx: https://polygonscan.com/tx/{trade['transaction_hash']}")
    print(f"{'=' * 60}\n")


def print_position_changes(address, positions, changes):
    """Default PositionMonitor callback: print a table on the first poll, then only changes."""
    short = address[:10]
    if changes.get('initial'):
        print(f"📊 Initial fetch: {len(positions)} positions for {short}")
        if positions:
            print("\n" + "=" * 120)
            print(f"{'Market':<40} {'Outcome':<10} {'Size':<12} {'Avg Price':<12} {'Cost $':<12} "
                  f"{'Current $':<12} {'P&L':<12}")
            print("=" * 120)
            for pos in positions:
                pnl = _num(pos.get('total_pnl'))
                symbol = "📈" if pnl > 0 else "📉" if pnl < 0 else "➖"
                print(f"{str(pos.get('slug', 'N/A'))[:38]:<40} {str(pos.get('outcome', 'N/A'))[:8]:<10} "
                      f"{_num(pos.get('current_size')):<12.2f} ${_num(pos.get('avg_price')):<11.3f} "
                      f"${_num(pos.get('total_cost_usdc')):<11.2f} ${_num(pos.get('current_value')):<11.2f} "
                      f"{symbol}${pnl:<10.2f}")
            print("=" * 120 + "\n")
        return

    if not (changes['new'] or changes['changed'] or changes['closed']):
        return

    print(f"\n📊 Position changes for {short}...")
    if changes['new']:
        print(f"   ✅ {len(changes['new'])} new position(s)")
        for pos in changes['new']:
            print(f"      • {str(pos.get('slug', 'N/A'))[:35]} - {pos.get('outcome', 'N/A')}: "
                  f"{_num(pos.get('current_size')):.2f} shares @ ${_num(pos.get('avg_price')):.3f} "
                  f"(${_num(pos.get('total_cost_usdc')):.2f})")
    if changes['changed']:
        print(f"   📈 {len(changes['changed'])} position(s) changed")
        for change in changes['changed']:
            size_delta = change['new_size'] - change['old_size']
            value_delta = change['new_value'] - change['old_value']
            print(f"      • {str(change['position'].get('slug', 'N/A'))[:35]} - {change['outcome']}:")
            print(f"        size change: {change['old_size']:.2f} → {change['new_size']:.2f} ({size_delta:+.2f})")
            print(f"        value change: ${change['old_value']:.2f} → ${change['new_value']:.2f} "
                  f"({value_delta:+.2f})")
    if changes['closed']:
        print(f"   ❌ {len(changes['closed'])} position(s) closed")
        for closed in changes['closed']:
            pos = closed['position']
            final = closed.get('final_position') or {}
            pnl = final.get('total_pnl', pos.get('total_pnl'))
            reason = f" [{closed['reason']}]" if closed.get('reason') else ""
            print(f"      • {str(pos.get('slug', 'N/A'))[:35]} - {pos.get('outcome', 'N/A')}{reason}: "
                  f"P&L: {_num(pnl):+.2f}")
