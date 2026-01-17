from xmlrpc import client
from lukhed_basic_utils import timeCommon as tC
from lukhed_basic_utils import requestsCommon as rC
from lukhed_basic_utils.classCommon import LukhedAuth
from py_clob_client.client import ClobClient
from .polymarket_tags import TAG_MAPPING
import json
import time
import threading
from websocket import WebSocketApp


class MarketWebSocket:
    """
    Websocket connection to Polymarket's public market channel.
    Does NOT require authentication.
    """
    def __init__(self, url, asset_ids, message_callback):
        self.url = url
        self.asset_ids = asset_ids
        self.message_callback = message_callback
        
        furl = url + "/ws/market"
        self.ws = WebSocketApp(
            furl,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self.on_open,
        )
    
    def on_message(self, ws, message):
        try:
            if message != "PONG":
                data = json.loads(message)
                if self.message_callback:
                    self.message_callback(data)
                else:
                    print(f"Market update: {json.dumps(data, indent=2)}")
        except Exception as e:
            print(f"Error processing message: {e}")
    
    def on_error(self, ws, error):
        print(f"WebSocket error: {error}")
    
    def on_close(self, ws, close_status_code, close_msg):
        print(f"WebSocket closed: {close_status_code} - {close_msg}")
    
    def on_open(self, ws):
        print(f"WebSocket connected. Monitoring {len(self.asset_ids)} asset(s)...")
        ws.send(json.dumps({"assets_ids": self.asset_ids, "type": "market"}))
        
        # Start ping thread
        def ping_loop():
            while True:
                try:
                    ws.send("PING")
                    time.sleep(10)
                except:
                    break
        
        ping_thread = threading.Thread(target=ping_loop, daemon=True)
        ping_thread.start()
    
    def subscribe_to_assets(self, new_asset_ids):
        """Subscribe to additional assets"""
        self.ws.send(json.dumps({"assets_ids": new_asset_ids, "operation": "subscribe"}))
        print(f"Subscribed to {len(new_asset_ids)} additional asset(s)")
    
    def unsubscribe_from_assets(self, asset_ids_to_remove):
        """Unsubscribe from specific assets"""
        self.ws.send(json.dumps({"assets_ids": asset_ids_to_remove, "operation": "unsubscribe"}))
        print(f"Unsubscribed from {len(asset_ids_to_remove)} asset(s)")
    
    def run(self):
        self.ws.run_forever()


class Polymarket:
    """
    This class wraps the polymarket gamma and data APIs and adds custom discovery methods for convenience. 
    It does not require authentication for public data access.

    clob_api documentation: https://github.com/Polymarket/py-clob-client
    gamma_api documentation: https://docs.polymarket.com/developers/gamma-markets-api/overview
    data_api documentation: https://docs.polymarket.com/developers/data-api/overview
    """
    def __init__(self, api_delay=0.1):
        self.delay = api_delay
        self.gamma_url = 'https://gamma-api.polymarket.com'
        self.data_url = 'https://data.polymarket.com'
        print("gamma api status:", self.get_gamma_status())
        print("data api status:", self.get_data_status())

    def _parse_api_delay(self, rate_limit=None):
        """
        Parse API delay based on rate limit.
        
        Parameters
        ----------
        rate_limit : tuple, optional
            (requests, per_seconds), e.g., (900, 10) for 900 requests per 10 seconds
        """
        if rate_limit:
            requests, per_seconds = rate_limit
            delay = per_seconds / requests
            tC.sleep(delay)
        elif self.delay:
            tC.sleep(self.delay)

    def _parse_tag(self, tag):
        if tag is None:
            return None
        
        tag = tag.lower()
        
        if tag in TAG_MAPPING:
            return TAG_MAPPING[tag]
        else:
            print(f'Warning: Tag "{tag}" not recognized')
            return None
        
    def _call_api(self, url, params=None, rate_limit_tuple=None):
        response = rC.make_request(url, params=params)
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            data = None

        self._parse_api_delay(rate_limit_tuple)
        response_data = {
            "statusCode": response.status_code,
            "data": data
        }
        return response_data
    
    def _call_api_get_all_responses(self, url, limit, params, print_progress=False):
        all_data = []
        offset = 0
        
        print("Fetching all paginated data from API...")
        while True:
            params['limit'] = limit
            params['offset'] = offset
            
            response = self._call_api(url, params=params)

            if print_progress and offset % (limit * 10) == 0:
                print(f"Completed fetching data with offset {offset} and limit {limit}. Continuing...")
            
            if response['statusCode'] != 200:
                print(f"Error fetching markets: {response['statusCode']}")
                break
            
            data = response['data']
            if not data:  # No more data, stop pagination
                break
            
            all_data.extend(data)
            
            offset += limit  # Increment offset for next page
    
        return all_data

    def _parse_date_inputs(self, start_date=None, end_date=None, date_format="%Y-%m-%d"):
        if start_date:
            start_date = tC.convert_to_unix(start_date, from_format=date_format)
        if end_date:
            end_date = tC.convert_to_unix(end_date, from_format=date_format)

        return start_date, end_date
    
    def _add_date_times(self, data):
        # working timestamp conversion test
        utc_tz = tC.ZoneInfo("UTC")
        est_tz = tC.ZoneInfo('America/New_York')

        for item in data:
            ts = item.get('timestamp', None)
            if ts:
                utc_dt = tC.datetime.fromtimestamp(ts, tz=utc_tz)
                eastern_dt = utc_dt.astimezone(est_tz)
                item['est'] = eastern_dt
                item['utc'] = utc_dt

        return data

        
    def get_gamma_status(self):
        url = 'https://gamma-api.polymarket.com/status'
        response = rC.make_request(url)
        if response.status_code != 200:
            print(f"Error fetching status: {response.status_code}")
            return None
        return response.text
    
    def get_data_status(self):
        url = 'https://data-api.polymarket.com/'
        try:
            response = rC.request_json(url)['data']
            return response
        except Exception as e:
            return f"Status error : {e}"


    ###############################
    # Market Methods
    ###############################
    def get_markets(self, get_all_data=True, include_closed=False, active_only=True, tag_filter=None):
        """
        Gets a list of markets from the Polymarket Gamma API.

        900 requests / 10s	Throttle requests over the maximum configured rate

        Parameters
        ----------
        get_all_data : bool, optional
            Whether or not to return all pages of data, by default True
        include_closed : bool, optional
            Whether or not to include closed markets, by default False
        tag_filter : string, optional
            Tag ID label to filter markets, by default None
        Returns
        -------
        list
            List of markets with market data
        """

        tag_filter = self._parse_tag(tag_filter)
        params = {
            "limit": 500, # Max limit per request
            "closed": include_closed if not include_closed else None,
            "active": active_only if active_only else None,
            "tag_id": tag_filter
            }
        
        url = 'https://gamma-api.polymarket.com/markets'

        if get_all_data:
            return self._call_api_get_all_responses(url, 500, params, True)
        else:
            response = self._call_api(url, params=params)
            if response['statusCode'] != 200:
                print(f"Error fetching markets: {response['statusCode']}")
                return []
            
            return response['data']
        
    def get_top_holders_for_market(self, market_condition_id, min_balance=1):
        """
        Gets the top holders for a specific market.

        Parameters
        ----------
        market_condition_id : str
            The market condition ID to get holders for.
        min_balance : int, optional
            Minimum balance filter, by default 1
        get_all_data : bool, optional
            Whether to retrieve all pages of holders, by default False

        Returns
        -------
        list
            List of top holders for the market. Note if this is a yes/no market, the both holders are returned in two 
            separate lists.
        """
        limit = 20
        params = {
            "limit": limit,
            "minBalance": min_balance,
            "market": market_condition_id
        }
        url = 'https://data-api.polymarket.com/holders'

        response = self._call_api(url, params=params)
        if response['statusCode'] != 200:
            print(f"Error fetching holders: {response['statusCode']}")
            return []
        return response['data']

    
    
    ##############################
    # Event Methods
    ##############################
    def get_events(self, tag=None, include_closed=False, active_only=True, get_all_data=True, order_by=None, 
                   ascending=True):
        """
        Gets a list of events from the Polymarket Gamma API.

        Parameters
        ----------
        tag : string, optional
            Tag ID label to filter events, by default None
        include_closed : bool, optional
            Whether or not to include closed events, by default False
        get_all_data : bool, optional
            Whether or not to return all pages of data, by default True
        order_by : str, optional
            Comma-separated list of fields to order by.
        ascending : bool, optional
            Whether to order in ascending order, by default True
        Returns
        -------
        list
            List of events
        """
        tag = self._parse_tag(tag)
        params = {
            "limit": 500,  # Max limit per request
            "tag_id": tag,
            "closed": include_closed,
            "active": active_only,
            "order_by": order_by,
            "ascending": ascending
        }
        url = 'https://gamma-api.polymarket.com/events'
        
        if get_all_data:
            return self._call_api_get_all_responses(url, 500, params, True)
        else:
            response = self._call_api(url, params=params)
            if response['statusCode'] != 200:
                print(f"Error fetching events: {response['statusCode']}")
                return []
            return response['data']
        
    def get_event_by_id(self, event_id):
        response = self._call_api(f'https://gamma-api.polymarket.com/events/{event_id}')
        if response['statusCode'] != 200:
            print(f"Error fetching event: {response['statusCode']}")
            return None
        return response['data']
    
    def get_event_by_slug(self, event_slug):
        """
        Returns event data for a given event slug.

        **Each event in polymarket has a slug in the URL. For example, when you visit:
        https://polymarket.com/event/fed-decision-in-january?tid=1767460047178, the slug is 
        'fed-decision-in-january'.**

        Parameters
        ----------
        event_slug : str()
            The slug of the event to retrieve.

        Returns
        -------
        dict
            Event data for the given slug.
        """
        response = self._call_api(f'https://gamma-api.polymarket.com/events/slug/{event_slug}')
        if response['statusCode'] != 200:
            print(f"Error fetching event: {response['statusCode']}")
            return None
        return response['data']
    
    
    ###############################
    # Tags
    ###############################
    def get_tags(self, get_all_data=True):
        """
        Gets a list of tags from the Polymarket Gamma API.

        Parameters
        ----------
        get_all_data : bool, optional
            Whether or not to return all pages of data, by default True
        Returns
        -------
        list
            List of tags
        """
        params = {
            "limit": 300,  # Max limit per request
        }
        url = 'https://gamma-api.polymarket.com/tags'
        
        if get_all_data:
            return self._call_api_get_all_responses(url, 300, params, True)
        else:
            response = self._call_api(url, params=params)
            if response['statusCode'] != 200:
                print(f"Error fetching tags: {response['statusCode']}")
                return []
            return response['data']
        
    def get_tag_by_id(self, tag_id):
        """
        Gets tag data for a given tag ID from the Polymarket Gamma API.

        Parameters
        ----------
        tag_id : string
            Tag ID to retrieve
        Returns
        -------
        dict
            Tag data
        """
        response = self._call_api(f'https://gamma-api.polymarket.com/tags/{tag_id}')
        if response['statusCode'] != 200:
            print(f"Error fetching tag: {response['statusCode']}")
            return None
        return response['data']
        
    def get_related_tags(self, tag, tag_id=False):
        """
        Gets related tags for a given tag from the Polymarket Gamma API.

        Parameters
        ----------
        tag : string
            Tag label to find related tags for
        tag_id : bool, optional
            Whether or not the provided tag is a tag ID, by default False
        Returns
        -------
        list
            List of related tags
        """
        if not tag_id:
            tag = self._parse_tag(tag)
        
        response = self._call_api(f'https://gamma-api.polymarket.com/tags/{tag}/related-tags/tags')
        if response['statusCode'] != 200:
            print(f"Error fetching related tags: {response['statusCode']}")
            return []
        return response['data']
    
    
    ###############################
    # Users
    ###############################
    def list_comments(self, entity_type, entity_id, get_positions=True, get_all_data=True, ascending=True, 
                      holders_only=False):
        """
        Gets comments for a given entity type (series, event, or market)

        Parameters
        ----------
        entity_type : str
            The type of entity to get comments for (e.g., "Series", "Event", or "Market").
        entity_id : str
            The ID of the entity to get comments for.
        get_positions : bool, optional
            Whether to include position data in the comments, by default True
        get_all_data : bool, optional
            Whether to retrieve all pages of comments, by default True
        ascending : bool, optional
            Whether to sort comments in ascending order, by default True
        holders_only : bool, optional
            Whether to include only comments from holders, by default False
        Returns
        -------
        list
            List of comments
        """

        # ensure entity_type is singular and capitalized
        entity_type = entity_type[0].capitalize() + entity_type[1:]

        url = 'https://gamma-api.polymarket.com/comments'
        limit = 100
        params = {
            "limit": limit,
            "parent_entity_type": entity_type,
            "parent_entity_id": entity_id,
            "get_positions": get_positions,
            "ascending": ascending,
            "holders_only": holders_only
        }

        if get_all_data:
            return self._call_api_get_all_responses(url, limit, params, True)
        else:
            response = self._call_api(url, params=params)
            if response['statusCode'] != 200:
                print(f"Error fetching comments: {response['statusCode']}")
                return []
            return response['data']

    def get_leaderboards(self, category='OVERALL', time_period='ALL', rank_by='profit', get_all_data=False, 
                         single_user_check=None, user_identifier='address'):
        """
        Gets the user leaderboard as available here: https://polymarket.com/leaderboard

        Parameters
        ----------
        category : str, optional
            Leaderboard type, options are (OVERALL, POLITICS, SPORTS, CRYPTO, CULTURE, MENTIONS, WEATHER, 
            ECONOMICS, TECh, FINANCE), by default 'OVERALL'
        time_period : str, optional
            Leaderboard filter by time period, options are (ALL, DAY, WEEK, MONTH), by default 'ALL'
        rank_by : str, optional
            Ranks by profit or volume, by default 'profit'
        get_all_data : bool, optional
            Whether to retrieve all pages of leaderboard data, by default False
        single_user_check : str, optional
            User identifier to check for in the leaderboard. You can use either an address or a username as defined 
            by user_identifier, by default None
        user_identifier : str, optional
            Identifier type for single user check, options are 'address' or 'username', by default 'address'

        Returns
        -------
        list
            List of leaderboard entries
        """

        limit = 50
        url = 'https://data-api.polymarket.com/v1/leaderboard'
        category = category.upper()
        time_period = time_period.upper()

        if rank_by.lower() == 'profit':
            order_by = 'PNL'
        elif rank_by.lower() == 'volume':
            order_by = 'VOL'

        user = single_user_check if user_identifier == 'address' else None
        username = single_user_check if user_identifier == 'username' else None

        params = {
            "category": category,
            "timePeriod": time_period,
            "orderBy": order_by,
            "user": user,
            "username": username,
            "limit": limit
        }

        if get_all_data:
            return self._call_api_get_all_responses(url, limit, params, True)
        else:
            response = self._call_api(url, params=params)
            if response['statusCode'] != 200:
                print(f"Error fetching leaderboards: {response['statusCode']}")
                return []
            return response['data']
        
    def get_user_activity(self, address, activity_type_list=["TRADE"], side=None, get_all_data=False, 
                          start_date=None, end_date=None, date_format="%Y-%m-%d", add_datetime=True):
        """
        Get user activity from the Polymarket Data API.

        Parameters
        ----------
        address : str
            The user's address to fetch activity for.
        activity_type_list : list, optional
            List of activity types to filter by (TRADE, SPLIT, MERGE, REDEEM, REWARD, CONVERSION), 
            by default ["TRADE"]
        side : str, optional
            Side of the trade to filter by (e.g., "BUY" or "SELL"), by default None
        get_all_data : bool, optional
            Whether to retrieve all pages of user activity data, by default False
        start_date : str, optional
            Start date for filtering activity, by default None
        end_date : str, optional
            End date for filtering activity, by default None
        date_format : str, optional
            Format of the start and end date strings, by default "%Y-%m-%d"
        add_datetime : bool, optional
            Whether to add datetime fields to the returned data, by default True

        Returns
        -------
        list
            List of user activity records
        """
        start_date, end_date = self._parse_date_inputs(start_date, end_date, date_format=date_format)
        limit = 500 # Max limit per request
        params = {
            "user": address,
            "limit": limit,  
            "type": ','.join(activity_type_list),
            "sortBy": "TIMESTAMP",
            "sortDirection": "DESC",
            "start": start_date,
            "end": end_date,
            "side": side.upper() if side else None
        }
        url = f'https://data-api.polymarket.com/activity'

        if get_all_data:
            data = self._call_api_get_all_responses(url, limit, params, True)
        else:
            response = self._call_api(url, params=params)
            if response['statusCode'] != 200:
                print(f"Error fetching events: {response['statusCode']}")
                return []
            else:
                data = response['data']
            
        if add_datetime:
            data = self._add_date_times(data)
            return data

        return data
    
    def get_current_positions_for_user(self, address, market=None, event_id=None, size_threshold=1, 
                                       redeemable=False, mergeable=False, sort_by='TOKENS', 
                                       sort_direction='DESC', get_all_data=False):
        """
        Gets current positions for a user from the Polymarket Data API.

        Parameters
        ----------
        address : str
            User address (required). User Profile Address (0x-prefixed, 40 hex chars)
        market : str or list, optional
            Condition ID or comma-separated list of condition IDs. Mutually exclusive with event_id, by default None
        event_id : int or list, optional
            Event ID or comma-separated list of event IDs. Mutually exclusive with market, by default None
        size_threshold : number, optional
            Minimum position size threshold, by default 1
        redeemable : bool, optional
            Filter for redeemable positions, by default False
        mergeable : bool, optional
            Filter for mergeable positions, by default False
        sort_by : str, optional
            Field to sort by. Options: CURRENT, INITIAL, TOKENS, CASHPNL, PERCENTPNL, TITLE, RESOLVING, PRICE, 
            AVGPRICE, by default 'TOKENS'
        sort_direction : str, optional
            Sort direction (ASC or DESC), by default 'DESC'
        get_all_data : bool, optional
            Whether to retrieve all pages of positions, by default False

        Returns
        -------
        list
            List of user positions
        """
        limit = 500
        
        # Convert market and event_id to comma-separated strings if they're lists
        if isinstance(market, list):
            market = ','.join(market)
        if isinstance(event_id, list):
            event_id = ','.join(str(id) for id in event_id)
        
        params = {
            "user": address,
            "market": market,
            "eventId": event_id,
            "sizeThreshold": size_threshold,
            "redeemable": redeemable,
            "mergeable": mergeable,
            "limit": limit,
            "sortBy": sort_by.upper(),
            "sortDirection": sort_direction.upper()
        }
        
        url = 'https://data-api.polymarket.com/positions'

        if get_all_data:
            return self._call_api_get_all_responses(url, limit, params, True)
        else:
            response = self._call_api(url, params=params)
            if response['statusCode'] != 200:
                print(f"Error fetching positions: {response['statusCode']}")
                return []
            return response['data']
    
    
    ###############################
    # Websocket Methods
    ###############################
    def subscribe_to_markets(self, asset_ids, callback=None):
        """
        Subscribe to market updates via websocket for specific asset/token IDs.
        Does NOT require authentication.
        
        Parameters
        ----------
        asset_ids : list
            List of asset IDs (token IDs) to monitor
        callback : callable, optional
            Function to call when market updates are received.
            Receives (message_data) as parameter.
            
        Returns
        -------
        MarketWebSocket
            The websocket connection object
            
        Example
        -------
        def my_callback(data):
            print(f"Market update: {data}")
            
        ws = pm.subscribe_to_markets(
            asset_ids=["109681959945973300464568698402968596289258214226684818748321941747028805721376"],
            callback=my_callback
        )
        """
        ws_monitor = MarketWebSocket(
            "wss://ws-subscriptions-clob.polymarket.com",
            asset_ids,
            callback
        )
        
        # Run in separate thread
        ws_thread = threading.Thread(target=ws_monitor.run, daemon=True)
        ws_thread.start()
        
        return ws_monitor
    
    def monitor_market_for_whales(self, markets=None, asset_ids=None, min_trade_size=1000, 
                                   min_trade_value=None, callback=None):
        """
        Monitor markets for large trades ("whale" activity) via websocket.
        Does NOT require authentication - uses public market channel.
        
        This is ideal for tracking when big bets come into specific markets.
        
        Parameters
        ----------
        markets : list, optional
            List of market slugs or condition IDs to monitor.
        asset_ids : list, optional
            List of specific asset IDs (token IDs) to monitor. 
        min_trade_size : float, optional
            Minimum number of shares for a trade to trigger callback, by default 1000
        min_trade_value : float, optional
            Minimum dollar value (size * price) for a trade to trigger callback.
            If provided, overrides min_trade_size.
        callback : callable, optional
            Function called when a large trade is detected.
            Receives (trade_data_dict) as parameter.
            If not provided, prints trade details to console.
            
        Returns
        -------
        MarketWebSocket
            The websocket connection object. Keeps running in background thread.
            
        Examples
        --------
        # Monitor for trades over $5000 on Trump market
        ws = pm.monitor_market_for_whales(
            markets=["will-donald-trump-be-elected-president-in-2024"],
            min_trade_value=5000,
            callback=lambda trade: print(f"🐋 Whale alert! {trade['side']} ${float(trade['size'])*float(trade['price']):.0f}")
        )
        
        # Keep script running
        import time
        while True:
            time.sleep(1)
        """
        # Get asset IDs if markets were provided
        if asset_ids is None and markets is None:
            raise ValueError("Must provide either 'markets' or 'asset_ids' parameter")
        
        if markets is not None:
            # Fetch asset IDs for the specified markets
            asset_ids = []
            for market_identifier in markets:
                # Try to get market by slug or condition_id
                try:
                    market_data = self.get_event_by_slug(market_identifier)
                    if market_data and 'markets' in market_data:
                        for market in market_data['markets']:
                            if 'tokens' in market:
                                for token in market['tokens']:
                                    asset_ids.append(token['token_id'])
                except:
                    # If slug doesn't work, assume it's a condition_id
                    markets_list = self.get_markets(get_all_data=False)
                    for market in markets_list:
                        if market.get('condition_id') == market_identifier:
                            if 'tokens' in market:
                                for token in market['tokens']:
                                    asset_ids.append(token['token_id'])
                            break
            
            if not asset_ids:
                raise ValueError(f"Could not find asset IDs for markets: {markets}")
            
            print(f"🐋 Monitoring {len(asset_ids)} assets from {len(markets)} market(s) for large trades...")
        else:
            print(f"🐋 Monitoring {len(asset_ids)} assets for large trades...")
        
        def whale_filter_callback(data):
            """Filter market messages for large trades"""
            try:
                if data.get('event_type') == 'trade' and data.get('status') == 'MATCHED':
                    size = float(data.get('size', 0))
                    price = float(data.get('price', 0))
                    trade_value = size * price
                    
                    # Check if trade meets threshold
                    is_whale = False
                    if min_trade_value is not None:
                        is_whale = trade_value >= min_trade_value
                    else:
                        is_whale = size >= min_trade_size
                    
                    if is_whale:
                        if callback:
                            callback(data)
                        else:
                            print(f"\n🐋 WHALE ALERT!")
                            print(f"   Trade Value: ${trade_value:,.2f}")
                            print(f"   Side: {data.get('side')}")
                            print(f"   Size: {size:,.0f} shares")
                            print(f"   Price: ${price:.3f}")
                            print(f"   Market: {data.get('market')}")
                            print(f"   Trader: {data.get('trade_owner', 'Unknown')[:10]}...")
            except Exception as e:
                print(f"Error filtering message: {e}")
        
        return self.subscribe_to_markets(asset_ids, whale_filter_callback)    
    
    def monitor_user_positions(self, address, poll_interval=60, callback=None):
        """
        Monitor a user's positions by polling the REST API periodically.
        Does NOT require authentication.
        
        This is the RECOMMENDED way to track specific user activity (better than websockets).
        You'll be notified when their positions change (new trades, exits, etc).
        
        Parameters
        ----------
        address : str
            The public address of the user to monitor
        poll_interval : int, optional
            Seconds between checks, by default 60
        callback : callable, optional
            Function called when positions change.
            Receives (address, positions_dict, changes_dict) as parameters.
            
        Returns
        -------
        threading.Thread
            The monitoring thread running in background
            
        Example
        -------
        def position_changed(addr, positions, changes):
            print(f"User {addr[:8]}... positions updated:")
            print(f"  New positions: {len(changes.get('new', []))}")
            print(f"  Changed positions: {len(changes.get('changed', []))}")
            print(f"  Closed positions: {len(changes.get('closed', []))}")
        
        thread = pm.monitor_user_positions(
            "0x123...",
            poll_interval=30,
            callback=position_changed
        )
        
        # Keep running
        import time
        while True:
            time.sleep(1)
        """
        def poll_loop():
            last_positions = {}
            print(f"📊 Monitoring positions for {address[:10]}... (polling every {poll_interval}s)")
            
            while True:
                try:
                    # Get current positions
                    current_positions = self.get_current_positions_for_user(
                        address, 
                        size_threshold=0.01
                    )
                    
                    # Build position map by market+outcome
                    current_map = {}
                    for pos in current_positions:
                        key = f"{pos.get('market')}_{pos.get('outcome')}"
                        current_map[key] = pos
                    
                    # Detect changes
                    if last_positions:
                        changes = {
                            'new': [],
                            'changed': [],
                            'closed': []
                        }
                        
                        # Check for new and changed positions
                        for key, pos in current_map.items():
                            if key not in last_positions:
                                changes['new'].append(pos)
                            elif pos.get('size') != last_positions[key].get('size'):
                                changes['changed'].append({
                                    'market': pos.get('market'),
                                    'outcome': pos.get('outcome'),
                                    'old_size': last_positions[key].get('size'),
                                    'new_size': pos.get('size'),
                                    'position': pos
                                })
                        
                        # Check for closed positions
                        for key, pos in last_positions.items():
                            if key not in current_map:
                                changes['closed'].append(pos)
                        
                        # Notify if there are changes
                        if any(changes.values()):
                            if callback:
                                callback(address, current_positions, changes)
                            else:
                                print(f"\n📊 Position changes for {address[:10]}...")
                                if changes['new']:
                                    print(f"   ✅ {len(changes['new'])} new position(s)")
                                if changes['changed']:
                                    print(f"   📈 {len(changes['changed'])} position(s) changed")
                                if changes['closed']:
                                    print(f"   ❌ {len(changes['closed'])} position(s) closed")
                    
                    last_positions = current_map
                    time.sleep(poll_interval)
                    
                except Exception as e:
                    print(f"Error monitoring user positions: {e}")
                    time.sleep(poll_interval)
        
        thread = threading.Thread(target=poll_loop, daemon=True)
        thread.start()
        return thread        

class PolymarketAuth(Polymarket, LukhedAuth):
    """
    This class extends the Polymarket class to include the ability to use the clob API authenticated methods.
    It requires setting up API key authentication via the LukhedAuth class.
    Then use the clob client to make authenticated requests using self.api.

    clob_api documentation:
    https://github.com/Polymarket/py-clob-client
    """
    def __init__(self, api_delay=0.1, key_management='github'):
        Polymarket.__init__(self, api_delay=api_delay)
        LukhedAuth.__init__(self, project_name='polymarketClobApi', key_management=key_management)

        if self._auth_data is None:
            print("No existing Polymarket API key data found, starting setup...")
            self._polymarket_api_setup()

        # Initialize ClobClient based on signature type
        if self._auth_data.get('signature_type', 1) == 0:
            # Standard wallet (MetaMask/Hardware) - uses private key for signing
            self.api = ClobClient(
                "https://clob.polymarket.com",
                key=self._auth_data['private_key'],  # Private key for signing
                chain_id=137,
                signature_type=0,
                funder=self._auth_data['address']  # Address holding funds
            )
        elif self._auth_data.get('signature_type', 1) == 1:
            # Magic wallet - uses API key for signing
            self.api = ClobClient(
                "https://clob.polymarket.com",
                key=self._auth_data['key'],  # API key acts as the signing key
                chain_id=137,
                signature_type=1,
                funder=self._auth_data['address']  # Proxy address holding funds
            )
        
        # Derive API credentials for authenticated requests
        self.api.set_api_creds(self.api.create_or_derive_api_creds())

        ok = self.api.get_ok()
        time = self.api.get_server_time()
        print(ok, time)

    def _polymarket_api_setup(self):
        """
        Sets up the Polymarket API key for authenticated requests.
        """
        
        print("\n\n***********************************\n" \
        "This is the lukhed setup for Polymarket API wrapper.\nIf you haven't already, you first need to setup a"
              f" Polymarket account (free) and generate an api key.\nThe data you provide in this setup will be stored "
              f"based on your key management parameter ({self._key_management}).\n\n"

              "Polymarket supports two authentication methods:\n"
                "1. Magic (Email) Wallet - Uses API key only\n"
                "2. MetaMask/Hardware Wallet - Requires private key\n\n"

               "Assuming option 1 (Magic wallet) setup, you need:\n"
                "- API key from: https://reveal.magic.link/polymarket\n"
                "- Your Polymarket proxy address (your public account address)\n\n"
                
                "General API help: https://docs.polymarket.com/quickstart/overview")
            
        if input("\n\nAre you ready to continue (y/n)?") != 'y':
            print("OK, come back when you have setup your developer account")
            quit()

        wallet_type = input("\nAre you using a Magic (email) wallet? (y/n): ").lower()

        if wallet_type == 'y':
            print("\nFor Magic wallets, you only need your API key and proxy address.")
            print("Your proxy address is your public Polymarket account address.\n\n")
            signature_type = 1
        else:
            print("\nFor MetaMask/hardware wallets, you need your private key and wallet address.")
            print("WARNING: lukhed auth stores your private key based on your key management settings. This means your " \
            "private key will be stored as plain text on your local machine or private github repo. Ensure  " \
            "you understand thesecurity implications of this before proceeding!\n\n")
            signature_type = 0

        key = input("Input your API key and press enter: ")
        address = input("Input your Polymarket proxy address and press enter: ")
        if signature_type == 0:
            private_key = input("Input your private key and press enter: ")
        else:
            private_key = None

        self._auth_data = {
            "key": key,
            "address": address,
            "signature_type": signature_type,
            "private_key": private_key
        }

        self.kM.force_update_key_data(self._auth_data)
        print("Setup complete!")

    