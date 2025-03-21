from lukhed_basic_utils import osCommon as osC
from lukhed_basic_utils import fileCommon as fC
from lukhed_basic_utils import requestsCommon as rC
from lukhed_basic_utils import timeCommon as tC
from lukhed_basic_utils import listWorkCommon as lC
from lukhed_basic_utils.githubCommon import KeyManager
from typing import Optional

class Kalshi:
    def __init__(self, elections_mode=False, demo_mode=False, api_delay=True, key_management='github', 
                 kalshi_setup=False):
        
        # API
        self.key_management = key_management.lower()
        self.delay = 0.5 if api_delay else 0

        # Setup
        if kalshi_setup:
            self._kalshi_api_setup()

        # Access Data
        self.kM = None                              # type: Optional[KeyManager]
        self._private_key = None
        self._pass = None
        self._email = None
        self.key_management = key_management.lower()
        self._token_file_path = osC.create_file_path_string(['lukhedConfig', 'localTokenFile.json'])
        self._check_create_km()

        self._check_exchange_status()


    def _call_kalshi_non_auth(self, url, params=None):
        tC.sleep(self.delay)
        return rC.request_json(url, params=params)
    
    def _check_exchange_status(self):
        url = 'https://api.elections.kalshi.com/trade-api/v2/exchange/status'
        r = self._call_kalshi_non_auth(url)
        print(r)

    def _check_create_km(self):
        if self.kM is None:
            # get the key data previously setup
            self.kM = KeyManager('kalshiApi', config_file_preference=self.key_management)
            self._private_key = self.kM.key_data['privateKey']
            self._pass = self.kM.key_data['password']
            self._email = self.kM.key_data['email']

    def _build_key_file(self):
        full_key_data = {
            "privateKey": self._private_key,
            "email": self._email,   
            "password": self._pass
        }
        return full_key_data

    def _kalshi_api_setup(self):
        print("This is the lukhed setup for Kalshi API wrapper.\nIf you haven't already, you first need to setup a"
              " Kalshi account (free) and generate api keys.\nThis wrapper utilizes the official kalshi python package"
              " to authenticate via email and account password.\nYour data for authentication is stored locally or on "
              "your own private github account depending on your instantiation method.\n\n"
              "To continue, you need the following from Kalshi:\n"
                "1. Private key\n"
                "2. Account Email\n"
                "3. Account Password\n"
                "If you don't know how to get these, you can find instructions here:\n"
                "https://trading-api.readme.io/reference/api-keys")
            
        if input("\n\nAre you ready to continue (y/n)?") == 'n':
            print("OK, come back when you have setup your developer account")
            quit()

        self._private_key = input("Paste just the private key content from your kalshi key file:\n").replace(" ", "")
        self._email = input("Paste your account email here:\n").replace(" ", "")
        self._pass = input("Paste your account password here:\n").replace(" ", "")

        # write the new token to github
        tC.sleep(1)
        key_data = self._build_key_file()

        print("\n\nThe Kalshi portion is complete! Now setting up key management with lukhed library...")
        self.kM = KeyManager('kalshiApi', config_file_preference=self.key_management, 
                            provide_key_data=key_data)


    @staticmethod
    def calculate_bet_yes_no_trade(trade_data):
        side_take = trade_data['taker_side']
        price = trade_data['yes_price']/100 if side_take == 'yes' else trade_data['no_price']/100
        contracts = trade_data['count']

        bet = contracts * price
        return bet

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