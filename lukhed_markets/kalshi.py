from lukhed_basic_utils import osCommon as osC
from lukhed_basic_utils import requestsCommon as rC
from lukhed_basic_utils import timeCommon as tC
from lukhed_basic_utils import listWorkCommon as lC
from lukhed_basic_utils import fileCommon as fC
from lukhed_basic_utils.classCommon import LukhedAuth
from typing import Optional
import base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends import default_backend
import datetime

class Kalshi(LukhedAuth):
    def __init__(self, api_delay='basic', key_management='github'):
        """
        Kalshi API Wrapper with authentication handling.

        Parameters
        ----------
        api_delay : str, optional
            The type of account you have with Kalshi: basic, advanced, premier, or prime, by default 'basic'
            This determines the rate limits (delays) for API calls.
        key_management : str, optional
            Options for storing your authentication data. 'local' to store your auth on your local hardware. 
            'github' to store it in a private GitHub repository (you will need a GitHub account and GitHub token),
            by default 'github'
        """
        super().__init__('kalshiApi', key_management=key_management)
        
        if self._auth_data is None:
            print("No existing Kalshi API key data found, starting setup...")
            self._kalshi_api_setup()

        self._check_dl_private_key_file()


        self.read_delay = None
        self.write_delay = None
        self._set_api_delays(api_delay)
        self.base_url = 'https://api.elections.kalshi.com'

        self._check_exchange_status()

    def _check_dl_private_key_file(self):
        """
        Kalshi uses a private key in addition to api key. This ensures it is downloaded appropriately based on 
        prior setups.
        """
        key_file_name = self._auth_data['privateKeyFileName']
        fp = osC.append_to_dir(self.kM._default_local_config, key_file_name)
        if osC.check_if_file_exists(fp):
            pass
        else:
            key_data = self.kM.retrieve_file_content(key_file_name).decode('utf-8')
            fC.write_content_to_file(fp, key_data)

    def _set_api_delays(self, plan):
        plan = plan.lower()
        # API Rate Limits
        if plan == 'basic':
            self.read_delay = 0.1    # 10 requests per second
            self.write_delay = 0.2   # 5 requests per second
        elif plan == 'advanced':
            self.read_delay = 0.033  # 30 requests per second
            self.write_delay = 0.033 # 30 requests per second
        elif plan == 'premier':
            self.read_delay = 0.01   # 100 requests per second
            self.write_delay = 0.01  # 100 requests per second
        elif plan == 'prime':
            self.read_delay = 0.01   # 100 requests per second
            self.write_delay = 0.0025 # 400 requests per second
        else:
            self.read_delay = 0.1    # default to basic tier
            self.write_delay = 0.2   # default to basic tier
    
    def _call_kalshi_non_auth(self, url, params=None):
        tC.sleep(self.read_delay)
        return rC.request_json(url, params=params)
    
    def _sign_pss_text(self, text: str) -> str:
        message = text.encode('utf-8')
        
        try:
            signature = self._private_key.sign(
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH
                ),
                hashes.SHA256()
            )
            return base64.b64encode(signature).decode('utf-8')
        except InvalidSignature as e:
            raise ValueError("RSA sign PSS failed") from e

    def _call_kalshi_auth(self, method: str, path: str, params=None):
        tC.sleep(self.read_delay)
        
        # Get current timestamp in milliseconds
        timestamp = int(datetime.datetime.now().timestamp() * 1000)
        timestamp_str = str(timestamp)
        
        # Create message string and sign it
        msg_string = timestamp_str + method + path
        sig = self._sign_pss_text(msg_string)
        
        # Prepare headers
        headers = {
            'KALSHI-ACCESS-KEY': self._key,
            'KALSHI-ACCESS-SIGNATURE': sig,
            'KALSHI-ACCESS-TIMESTAMP': timestamp_str
        }
        
        # Make request
        url = self.base_url + path
        
        return rC.request_json(url, headers=headers, params=params)

    def _check_exchange_status(self):
        r = self.get_exchange_status()
        print(r)
    
    def _kalshi_api_setup(self):
        print("\n\n***********************************\n" \
        "This is the lukhed setup for Kalshi API wrapper.\nIf you haven't already, you first need to setup a"
              f" Kalshi account (free) and generate api keys.\nThe data you provide in this setup will be stored based "
              f"on your key management parameter ({self._key_management}).\n\n"
              "To continue, you need the following from Kalshi:\n"
                "1. Key identifier (can be found on your key page here: https://kalshi.com/account/profile)\n"
                "2. Private key file downloaded from Kalshi upon creation of key\n"
                
                "If you don't know how to get these, you can find instructions here:\n"
                "https://trading-api.readme.io/reference/api-keys")
            
        if input("\n\nAre you ready to continue (y/n)?") == 'n':
            print("OK, come back when you have setup your developer account")
            quit()

        identifier_key = input("Paste your key identifier here (found in Kalshi API keys secion "
                               "https://kalshi.com/account/profile):\n").replace(" ", "")
        
        key_fn = input(f"Place your private key file downloaded from Kalshi into the following directory:\n"
                       f"{self.kM.github_config_dir} and write the full name of your private key file "
                       " here (e.g., key.txt):\n")
        
        private_key_path = osC.create_file_path_string(['lukhedConfig', key_fn])
        if osC.check_if_file_exists(private_key_path):
            pass
        else:
            input(f"\n\nERROR: The file path {private_key_path} does not exist. Please make sure you have "
                  f"placed {key_fn} in the lukhedConfig folder.\n\n"
                  "Press enter to try again.")
            if osC.check_if_file_exists(private_key_path):
                pass
            else:
                print("File still not found, exiting setup.")
                quit()

        print("Setting up Kalshi API key data...")
        self._auth_data = {
            "key": identifier_key,
            "privateKeyFileName": key_fn,
        }
        self.kM.force_update_key_data(self._auth_data)
        tC.sleep(1)
        private_key_content = fC.read_file_content(private_key_path)
        self.kM.create_update_file(key_fn, private_key_content, 'created with lukhed basic utils for Kalshi API')
        print("Setup complete!")
        


        print("\n\nThe Kalshi portion is complete! Now setting up key management with lukhed library...")
        
    def _parse_active_only_markets(self, markets, active_only):
        if active_only:
            return [x for x in markets if x['status'] == 'active']
        else:
            return markets

    @staticmethod
    def calculate_bet_yes_no_trade(trade_data):
        side_take = trade_data['taker_side']
        price = trade_data['yes_price']/100 if side_take == 'yes' else trade_data['no_price']/100
        contracts = trade_data['count']

        bet = contracts * price
        return bet
    
    #################################
    # Naive Wrapper Functions
    #################################
    def get_markets(self, limit=1000, cursor=None, event_ticker=None, series_ticker=None, max_close_ts=None, 
                    min_close_ts=None, status=None, tickers=None, return_raw_data=False):
        """
        Endpoint for getting data about all markets
        https://trading-api.readme.io/reference/getmarkets-1

        Parameters
        ----------
        limit : int, optional
            1 to 1000, Parameter to specify the number of results per page. Defaults to 1000 (max).
        cursor : str, optional
            The Cursor represents a pointer to the next page of records in the pagination. So this optional parameter, 
            when filled, should be filled with the cursor string returned in a previous request to this end-point.
            Filling this would basically tell the api to get the next page containing the number of records passed on 
            the limit parameter. On the other side not filling it tells the api you want to get the first page 
            for another query. The cursor does not store any filters, so if any filter parameters like tickers, max_ts 
            or min_ts were passed in the original query they must be passed again.
        event_ticker : str, optional
            Event ticker to retrieve markets for.
        series_ticker : str, optional
            Series ticker to retrieve contracts for.
        max_close_ts : int, optional
            Restricts the markets to those that are closing in or before this timestamp.
        min_close_ts : int, optional
            Restricts the markets to those that are closing in or after this timestamp.
        status : str, optional
            Restricts the markets to those with certain statuses, as a comma separated list. The following values are 
            accepted: unopened, open, closed, settled.
        tickers : str, optional
            Restricts the markets to those with certain tickers, as a comma separated list.
        return_raw_data : bool, optional
            If True, return the raw data from the API. Defaults to False.
        """

        url = 'https://api.elections.kalshi.com/trade-api/v2/markets'
        params = {
            'limit': limit,
            'cursor': cursor,
            'event_ticker': event_ticker,
            'series_ticker': series_ticker,
            'max_close_ts': max_close_ts,
            'min_close_ts': min_close_ts,
            'status': status,
            'tickers': tickers
        }

        r = self._call_kalshi_non_auth(url, params=params)
        if return_raw_data:
            return r
        else:
            final_data = []
            for data in r['markets']:
                pretty_dict = {
                    'title': data['title'],
                    'ticker': data['ticker'],
                    'status': data['status'],
                    'open_time': data['open_time'],
                    'close_time': data['close_time'],
                    'no_bid': data['no_bid'],
                    'yes_bid': data['yes_bid'],
                    'no_ask': data['no_ask'],
                    'yes_ask': data['yes_ask']
                }
                final_data.append(pretty_dict)
            return final_data
        
    def get_market(self, ticker):
        """
        Endpoint for getting data about a specific market
        https://trading-api.readme.io/reference/getmarket-1

        Parameters
        ----------
        ticker : str
            Market ticker for the market being retrieved.
        
        Returns
        -------
        dict
            Data about the specific market
        """
        url = f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}'
        r = self._call_kalshi_non_auth(url)
        return r

    def get_events(self, limit=100 ,cursor=None, status=None, series_ticker=None, with_nested_markets=False):
        """
        Endpoint for getting data about all events
        https://trading-api.readme.io/reference/getevents-1

        Parameters
        ----------
        limit : int, optional
            1 to 200, Parameter to specify the number of results per page. Defaults to 100.
        cursor : str, optional
            The Cursor represents a pointer to the next page of records in the pagination. So this optional parameter, 
            when filled, should be filled with the cursor string returned in a previous request to this end-point.
            Filling this would basically tell the api to get the next page containing the number of records passed on 
            the limit parameter. On the other side not filling it tells the api you want to get the first page 
            for another query. The cursor does not store any filters, so if any filter parameters like series_ticker 
            was passed in the original query they must be passed again.
        status : str, optional
            Restricts the events to those with certain statuses, as a comma separated list. The following values are 
            accepted: unopened, open, closed, settled.
        series_ticker : str, optional
            Series ticker to retrieve contracts for, by default None
        with_nested_markets : bool, optional
            If the markets belonging to the events should be added in the response as a nested field in this event. 
            by default False
        """

        url = "https://api.elections.kalshi.com/trade-api/v2/events"
        params = {
            'limit': limit,
            'cursor': cursor,
            'status': status,
            'series_ticker': series_ticker,
            'with_nested_markets': with_nested_markets
        }

        r = self._call_kalshi_non_auth(url, params=params)
        return r
    
    def get_event(self, event_ticker, with_nested_markets=False):
        """
        Endpoint for getting data about an event by its ticker
        https://trading-api.readme.io/reference/getevent-1

        Parameters
        ----------
        event_ticker : str
            Should be filled with the ticker of the event.
        with_nested_markets : bool, optional
            If the markets belonging to the events should be added in the response as a nested field in this event. 
            Defaults to False.
        
        Returns
        -------
        dict
            Data about the specific event
        """
        url = f'https://api.elections.kalshi.com/trade-api/v2/events/{event_ticker}'
        params = {
            'with_nested_markets': with_nested_markets
        }
        r = self._call_kalshi_non_auth(url, params=params)
        return r

    def get_series(self, series_ticker):
        """
        Endpoint for getting data about a series by its ticker
        https://trading-api.readme.io/reference/getseries-1

        Parameters
        ----------
        series_ticker : str
            Should be filled with the ticker of the series.
        
        Returns
        -------
        dict
            Data about the specific series
        """
        url = f'https://api.elections.kalshi.com/trade-api/v2/series/{series_ticker}'
        r = self._call_kalshi_non_auth(url)
        return r

    def get_account_balance(self):
        """
        Get the account balance.

        Returns
        -------
        dict
            Account balance data.
        """
        path = '/trade-api/v2/portfolio/balance'
        r = self._call_kalshi_auth('GET', path, params=None)
        return r
    
    def get_market_candlesticks(self, series_ticker, ticker, start_ts, end_ts, period_interval, 
                                ts_format="%Y%m%d%H%M%S", ts_timezone="US/Eastern"):
        """
        Endpoint for getting the historical candlesticks for a market
        https://trading-api.readme.io/reference/getmarketcandlesticks-1

        Parameters
        ----------
        series_ticker : str
            Unique identifier for the series.
        ticker : str
            Unique identifier for the market.
        start_ts : str
            Restricts the candlesticks to those covering time periods that end on or after this timestamp.
        end_ts : str
            Restricts the candlesticks to those covering time periods that end on or before this timestamp.
                Must be within 5000 period_intervals after start_ts.
        period_interval : str()
            Specifies the length of each candlestick period, '1m', '1h', or '1d'.
        ts_format : str, optional
            Format of the timestamp, by default "%Y%m%d%H%M%S"
        ts_timezone : str, optional
            Timezone of the timestamp (any valid timezone string supported by zoneinfo), by default "US/Eastern"
            
        Returns
        -------
        dict
            Historical candlestick data for the specified market
        """
        url = f'https://api.elections.kalshi.com/trade-api/v2/series/{series_ticker}/markets/{ticker}/candlesticks'
        
        if period_interval == '1m':
            period_interval = 1
        elif period_interval == '1h':
            period_interval = 60
        elif period_interval == '1d':
            period_interval = 1440
        else:
            raise ValueError('Invalid period_interval. Must be "1m", "1h", or "1d".')
        
        start_ts = tC.convert_to_unix(start_ts, ts_format, ts_timezone)
        end_ts = tC.convert_to_unix(end_ts, ts_format, ts_timezone)
        params = {
            'start_ts': start_ts,
            'end_ts': end_ts,
            'period_interval': period_interval
        }
        r = self._call_kalshi_non_auth(url, params=params)
        return r

    def get_market_orderbook(self, ticker, depth=None):
        """
        Endpoint for getting the orderbook for a market
        https://trading-api.readme.io/reference/getmarketorderbook-1

        Parameters
        ----------
        ticker : str
            Market ticker.
        depth : int, optional
            Depth specifies the maximum number of orderbook price levels you want to see for either side.
            Only the highest (most relevant) price level are kept.
        
        Returns
        -------
        dict
            Orderbook data for the specified market
        """
        url = f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}/orderbook'
        params = {}
        if depth is not None:
            params['depth'] = depth
            
        r = self._call_kalshi_non_auth(url, params=params)
        return r

    def get_market_spread(self, ticker, depth=None):
        """
        Calculate the bid-ask spread for a market using the order book.

        Parameters
        ----------
        ticker : str
            Market ticker.
        depth : int, optional
            Depth of the order book to consider.

        Returns
        -------
        dict
            Spread information: {'yes_spread': float, 'no_spread': float, 'best_yes_bid': int, 'best_yes_ask': int, 'best_no_bid': int, 'best_no_ask': int}
        """
        orderbook = self.get_market_orderbook(ticker, depth=depth)
        
        yes_orders = orderbook['orderbook']['yes']
        no_orders = orderbook['orderbook']['no']
        
        if not yes_orders or not no_orders:
            return {'yes_spread': None, 'no_spread': None, 'best_yes_bid': None, 'best_yes_ask': None, 'best_no_bid': None, 'best_no_ask': None}
        
        # Best YES bid: Highest price in the yes array (best to sell yes)
        best_yes_bid = max(order['price'] for order in yes_orders)
        
        # Best YES ask: 100 - (Highest price in the no array)  [highest NO bid]
        best_no_bid = max(order['price'] for order in no_orders)
        best_yes_ask = 100 - best_no_bid
        
        yes_spread = best_yes_ask - best_yes_bid
        
        # Best NO bid: Highest price in the no array
        best_no_bid = best_no_bid
        
        # Best NO ask: 100 - (Highest price in the yes array)  [highest YES bid]
        best_no_ask = 100 - best_yes_bid
        
        no_spread = best_no_ask - best_no_bid
        
        return {
            'yes_spread': yes_spread,
            'no_spread': no_spread,
            'best_yes_bid': best_yes_bid,
            'best_yes_ask': best_yes_ask,
            'best_no_bid': best_no_bid,
            'best_no_ask': best_no_ask
        }

    def get_exchange_announcements(self):
        """
        Endpoint for getting all exchange-wide announcements
        https://trading-api.readme.io/reference/getexchangeannouncements-1

        Returns
        -------
        dict
            All exchange-wide announcements
        """
        url = 'https://api.elections.kalshi.com/trade-api/v2/exchange/announcements'
        r = self._call_kalshi_non_auth(url)
        return r

    def get_exchange_schedule(self):
        """
        Endpoint for getting the exchange schedule
        https://trading-api.readme.io/reference/getexchangeschedule-1

        Returns
        -------
        dict
            The exchange schedule information
        """
        url = 'https://api.elections.kalshi.com/trade-api/v2/exchange/schedule'
        r = self._call_kalshi_non_auth(url)
        return r
    
    def get_exchange_status(self):
        """
        Endpoint for getting the exchange status
        https://trading-api.readme.io/reference/getexchangestatus-1

        Returns
        -------
        dict
            Current status of the exchange
        """
        url = 'https://api.elections.kalshi.com/trade-api/v2/exchange/status'
        r = self._call_kalshi_non_auth(url)
        return r

    def get_milestones(self, limit=100, cursor=None, minimum_start_date=None, category=None, 
                      type=None, related_event_ticker=None):
        """
        Endpoint for getting data about milestones with optional filtering
        https://trading-api.readme.io/reference/getmilestones-1

        Parameters
        ----------
        limit : int, optional
            Number of items to return per page (1 to 500), defaults to 100
        cursor : str, optional
            Cursor for pagination
        minimum_start_date : str, optional
            Minimum start date to filter milestones (date-time format)
        category : str, optional
            Filter by category
        type : str, optional
            Filter by type
        related_event_ticker : str, optional
            Filter by related event ticker
        
        Returns
        -------
        dict
            Data about milestones matching the filter criteria
        """
        url = 'https://api.elections.kalshi.com/trade-api/v2/milestones/'
        params = {
            'limit': limit
        }
        
        if cursor:
            params['cursor'] = cursor
        if minimum_start_date:
            params['minimum_start_date'] = minimum_start_date
        if category:
            params['category'] = category
        if type:
            params['type'] = type
        if related_event_ticker:
            params['related_event_ticker'] = related_event_ticker
            
        r = self._call_kalshi_non_auth(url, params=params)
        return r
    
    def get_milestone(self, milestone_id):
        """
        Endpoint for getting data about a specific milestone by its ID
        https://trading-api.readme.io/reference/getmilestone-1

        Parameters
        ----------
        milestone_id : str
            Unique identifier for the milestone

        Returns
        -------
        dict
            Data about the specific milestone
        """
        url = f'https://api.elections.kalshi.com/trade-api/v2/milestones/{milestone_id}'
        r = self._call_kalshi_non_auth(url)
        return r
    
    def get_tags_for_series_categories(self):
        """
        This endpoint returns a mapping of series categories to their associated tags, which can be used for 
        filtering and search functionality.
        https://docs.kalshi.com/api-reference/search/get-tags-for-series-categories


        Returns
        -------
        _type_
            _description_
        """

        url = f'https://api.elections.kalshi.com/trade-api/v2/search/tags_by_categories'
        r = self._call_kalshi_non_auth(url)
        return r["tags_by_categories"]
    
    def get_filters_by_sport(self):
        """
        This endpoint returns filtering options available for each sport, including scopes and competitions. 
        It also provides an ordered list of sports for display purposes.
        https://docs.kalshi.com/api-reference/search/get-filters-by-sport

        Returns
        -------
        dict
            Mapping of sports to their associated filters
        """

        url = f'https://api.elections.kalshi.com/trade-api/v2/search/filters_by_sport'
        r = self._call_kalshi_non_auth(url)
        return r

    #################################
    # Custom Wrapper Functions
    #################################
    def get_all_available_events(self, status='open', series_ticker=None, with_nested_markets=False, 
                                 sub_title_filter=None):
        """
        Get all available Kalshi events by handling pagination automatically.
        
        Parameters
        ----------
        status : str, optional
            Filter events by status (unopened, open, closed, settled), default open
        series_ticker : str, optional
            Series ticker to retrieve contracts for
        with_nested_markets : bool, optional
            Include nested markets in response
            
        Returns
        -------
        list
            List of all available events
        """
        all_events = []
        cursor = None
        limit = 200  # Maximum allowed by API
        
        while True:
            # Get batch of events
            response = self.get_events(
                limit=limit,
                cursor=cursor,
                status=status,
                series_ticker=series_ticker,
                with_nested_markets=with_nested_markets
            )
            
            # Add events to master list
            if 'events' in response:
                all_events.extend(response['events'])
            
            # Check if there are more events to fetch
            if 'cursor' not in response or not response['cursor']:
                break
            
            print('collecting 200 more events...')
            cursor = response['cursor']
            sanity_check = lC.return_unique_values([event['event_ticker'] for event in all_events])
            if len(sanity_check) != len(all_events):
                print('Duplicate tickers found in all_events!')
                break

        if sub_title_filter is not None:
            all_events = [event for event in all_events if sub_title_filter.lower() in event['sub_title'].lower()]
        
        return all_events


    #################################
    # Custom Series
    #################################
    def get_economics_series(self):
        url = 'https://api.elections.kalshi.com/trade-api/v2/series?category=Economics'
        r = self._call_kalshi_non_auth(url)
        return r['series']
    
    def get_inflation_series(self):
        url = 'https://api.elections.kalshi.com/trade-api/v2/series?tags=Inflation'
        r = self._call_kalshi_non_auth(url)
        return r['series']
    
    def get_fed_series(self):
        url = 'https://api.elections.kalshi.com/trade-api/v2/series?tags=Fed'
        r = self._call_kalshi_non_auth(url)
        return r['series']
    
    def get_nasdaq_series(self):
        url = 'https://api.elections.kalshi.com/trade-api/v2/series?tags=Nasdaq'
        r = self._call_kalshi_non_auth(url)
        return r['series']
    
    def get_sp500_series(self):
        url = 'https://api.elections.kalshi.com/trade-api/v2/series?tags=S%26P'
        r = self._call_kalshi_non_auth(url)
        return r['series']
    
    def get_treasuries_series(self):
        url = 'https://api.elections.kalshi.com/trade-api/v2/series?tags=Treasuries'
        r = self._call_kalshi_non_auth(url)
        return r['series']
    
    def get_wti_series(self):
        url = 'https://api.elections.kalshi.com/trade-api/v2/series?tags=WTI'
        r = self._call_kalshi_non_auth(url)
        return r['series']
    
    def get_btc_series(self):
        url = 'https://api.elections.kalshi.com/trade-api/v2/series?tags=BTC'
        r = self._call_kalshi_non_auth(url)
        return r['series']
    
    #################################
    # Custom Stocks
    #################################
    def get_sp500_year_end_range_markets(self, active_only=False, force_year=None):
        """
        Get all SP500 year end range markets.

        Parameters
        ----------
        active_only : bool, optional
            Only return active markets, by default False
        force_year : int, optional
            Force a specific year for the markets, by default None
        Returns
        -------
        list
            List of SP500 year end range markets.
        """
        year = int(tC.get_current_year()) if force_year is None else force_year
        series = self.get_sp500_series()
        yearly_range_series = [x for x in series if 'yearly range' in x['title'].lower()]
        applicable_events = []
        for series in yearly_range_series:
            ticker = series['ticker']
            events = self.get_events(series_ticker=ticker)
            applicable_events.extend([x for x in events['events'] if 
                                      tC.convert_non_python_format(x['strike_date'])['year'] == 
                                      year])
            
        if len(applicable_events) == 1:
            event_data = self.get_event(applicable_events[0]['event_ticker'], with_nested_markets=True)
        elif len(applicable_events) > 1:
            print("Warning: Multiple applicable events found, using the first one.")
            event_data = self.get_event(applicable_events[0]['event_ticker'], with_nested_markets=True)
        else:
            print("ERROR: No applicable events found for SP500 yearly range markets.")
            return []

        try:
            return event_data['error']
        except KeyError:
            pass

        markets = event_data['event']['markets']
        return self._parse_active_only_markets(markets, active_only)
    
    def get_nasdaq_year_end_range_markets(self, active_only=False, force_year=None):
        """
        Get all Nasdaq year end range markets.

        Parameters
        ----------
        active_only : bool, optional
            Only return active markets, by default False
        force_year : int, optional
            Force a specific year for the markets, by default None

        Returns
        -------
        list
            List of Nasdaq year end range markets.
        """
        year = int(tC.get_current_year()) if force_year is None else force_year
        series = self.get_nasdaq_series()
        yearly_range_series = [x for x in series if 'yearly range' in x['title'].lower()]
        applicable_events = []
        for series in yearly_range_series:
            ticker = series['ticker']
            events = self.get_events(series_ticker=ticker)
            applicable_events.extend([x for x in events['events'] if 
                                      tC.convert_non_python_format(x['strike_date'])['year'] == 
                                      year])
            
        if len(applicable_events) == 1:
            event_data = self.get_event(applicable_events[0]['event_ticker'], with_nested_markets=True)
        elif len(applicable_events) > 1:
            print("Warning: Multiple applicable events found, using the first one.")
            event_data = self.get_event(applicable_events[0]['event_ticker'], with_nested_markets=True)
        else:
            print("ERROR: No applicable events found for Nasdaq yearly range markets.")
            return []

        try:
            return event_data['error']
        except KeyError:
            pass

        markets = event_data['event']['markets']
        return self._parse_active_only_markets(markets, active_only)
        
        
    
    #################################
    # Custom Crypto
    #################################
    def get_bitcoin_yearly_high_markets(self, active_only=False, force_year=None):
        """
        Get all Bitcoin yearly high markets.

        Parameters
        ----------
        active_only : bool, optional
            Only return active markets, by default False
        force_year : int, optional
            Force a specific year for the markets, by default None

        Returns
        -------
        list
            List of Bitcoin yearly max markets.
        """
        series = self.get_btc_series()
        yearly_max_series = [x for x in series if 'how high will bitcoin get this year' in x['title'].lower()]
        applicable_events = []
        for series in yearly_max_series:
            ticker = series['ticker']
            events = self.get_events(series_ticker=ticker)
            applicable_events.extend([x for x in events['events'] if 
                                      'before dec 31, 2026' in x['sub_title'].lower()])
            
        if len(applicable_events) == 1:
            event_data = self.get_event(applicable_events[0]['event_ticker'], with_nested_markets=True)
        elif len(applicable_events) > 1:
            print("Warning: Multiple applicable events found, using the first one.")
            event_data = self.get_event(applicable_events[0]['event_ticker'], with_nested_markets=True)
        else:
            print("ERROR: No applicable events found for Bitcoin year end range markets.")
            return []

        try:
            return event_data['error']
        except KeyError:
            pass

        markets = event_data['event']['markets']
        return self._parse_active_only_markets(markets, active_only)
        
        
    
    #################################
    # Custom Account Info
    #################################

