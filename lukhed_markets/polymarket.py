from lukhed_basic_utils import timeCommon as tC
from lukhed_basic_utils import requestsCommon as rC
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BookParams
from .polymarket_tags import TAG_MAPPING

class polymarket:
    def __init__(self, api_delay=0.1):
        self.delay = api_delay
        self.clob_api = ClobClient("https://clob.polymarket.com")
        self.gamma_url = 'https://gamma-api.polymarket.com'
        ok = self.clob_api.get_ok()
        time = self.clob_api.get_server_time()
        print(ok, time)

    def _parse_api_delay(self):
        if self.delay:
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

    def get_markets(self):
        markets = self.clob_api.get_markets()
        self._parse_api_delay()
        return markets
    
    def get_events(self, tag=None, include_closed=False):
        tag = self._parse_tag(tag)
        params = {
            "limit":1000,
            "tag_id":tag,
            "closed": include_closed
            }
        events = rC.request_json('https://gamma-api.polymarket.com/events', params=params)
        self._parse_api_delay()
        return events
    
    def get_tags(self):
        tags = rC.request_json('https://gamma-api.polymarket.com/tags', params={"limit":1000})
        self._parse_api_delay()
        return tags
    
    def get_event_by_id(self, event_id):
        event = rC.request_json(f'https://gamma-api.polymarket.com/events/{event_id}')
        self._parse_api_delay()
        return event
    
    def get_midpoint(self, token_id):
        mid = self.clob_api.get_midpoint(token_id)
        self._parse_api_delay()
        return mid
        

