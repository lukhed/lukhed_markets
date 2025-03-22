from lukhed_basic_utils import osCommon as osC
from lukhed_basic_utils import fileCommon as fC
from lukhed_basic_utils import requestsCommon as rC
from lukhed_basic_utils import timeCommon as tC
from lukhed_basic_utils import listWorkCommon as lC
from lukhed_basic_utils.githubCommon import KeyManager
from typing import Optional
import base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends import default_backend
import datetime

class Kalshi:
    def __init__(self, api_delay='basic', kalshi_setup=False):
        
        
        self.read_delay = None
        self.write_delay = None
        self._set_api_delays(api_delay)
        self.base_url = 'https://api.elections.kalshi.com'

        # Setup
        if kalshi_setup:
            self._kalshi_api_setup()


        # Access Data
        self.kM = None                              # type: Optional[KeyManager]
        self._token_file_path = osC.create_file_path_string(['lukhedConfig', 'localTokenFile.json'])
        self._private_key_path = None
        self._key = None
        self._private_key = None
        self._check_create_km()

        self._check_exchange_status()

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
        url = 'https://api.elections.kalshi.com/trade-api/v2/exchange/status'
        r = self._call_kalshi_non_auth(url)
        print(r)

    def _check_create_km(self):
        if self.kM is None:
            # get the key data previously setup
            self.kM = KeyManager('kalshiApi', config_file_preference='local')
            self._key = self.kM.key_data['key']
            self._private_key_path = self.kM.key_data['privateKeyPath']
            
            with open(self._private_key_path, "rb") as key_file:
                self._private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None,  # or provide a password if your key is encrypted
                    backend=default_backend()
                )

    def _build_key_file(self):
        full_key_data = {
            "key": self._key,
            "privateKeyPath": self._private_key_path,
        }
        return full_key_data
    
    def _kalshi_api_setup(self):
        print("This is the lukhed setup for Kalshi API wrapper.\nIf you haven't already, you first need to setup a"
              " Kalshi account (free) and generate api keys.\nThe data you provide in this setup will be stored on "
              "your local device.\n\n"
              "To continue, you need the following from Kalshi:\n"
                "1. Key identifier (can be found on your key page here: https://kalshi.com/account/profile)\n"
                "2. Private key file downloaded from Kalshi upon creation of key\n"
                
                "If you don't know how to get these, you can find instructions here:\n"
                "https://trading-api.readme.io/reference/api-keys")
            
        if input("\n\nAre you ready to continue (y/n)?") == 'n':
            print("OK, come back when you have setup your developer account")
            quit()

        self._key = input("Paste your key identifier here (found in Kalshi API keys secion "
                          "https://kalshi.com/account/profile):\n").replace(" ", "")
        key_fn = input("Write the name of your private key file downloaded from kalshi upon key creation"
                       " here (e.g., key.txt):\n")
        self._private_key_path = osC.create_file_path_string(['lukhedConfig', key_fn])
        key_data = self._build_key_file()
        tC.sleep(1)
        self.kM = KeyManager('kalshiApi', config_file_preference='local', provide_key_data=key_data, force_setup=True)
        input(f"\n\nFINAL STEP: Copy your private key file here: {self._private_key_path}\n\n"
              "Press enter when you are ready to continue")

        print("\n\nThe Kalshi portion is complete! Now setting up key management with lukhed library...")
        
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
    def get_markets(self, return_raw_data=False):
        url = 'https://api.elections.kalshi.com/trade-api/v2/markets'
        r = self._call_kalshi_non_auth(url, params={'limit': 1000})
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


        
    def get_account_balance(self):
        path = '/trade-api/v2/portfolio/balance'
        r = self._call_kalshi_auth('GET', path, params=None)
        return r