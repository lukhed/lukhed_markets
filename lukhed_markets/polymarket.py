from lukhed_basic_utils import timeCommon as tC
from lukhed_basic_utils import requestsCommon as rC
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BookParams
from .polymarket_tags import TAG_MAPPING
import json

class Polymarket:
    """
    This class wraps the polymarket gamma API and adds custom discovery methods for convenience. It also allows access 
    to py-clob-client via self.clob_api.

    clob_api documentation: https://github.com/Polymarket/py-clob-client
    gamma_api documentation: https://docs.polymarket.com/developers/gamma-markets-api/overview
    """
    def __init__(self, api_delay=0.1):
        self.delay = api_delay
        self.clob_api = ClobClient("https://clob.polymarket.com")
        self.gamma_url = 'https://gamma-api.polymarket.com'
        print("gamma api status:", self.get_gamma_status())

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
        
    def _call_gamma_api(self, url, params=None, rate_limit_tuple=None):
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
    
    def _get_all_responses(self, url, limit, params, print_progress=False):
        all_data = []
        offset = 0
        
        while True:
            params['limit'] = limit
            params['offset'] = offset
            
            if print_progress and offset % (limit * 10) == 0:
                print(f"Fetching data with offset {offset} and limit {limit}")
            
            response = self._call_gamma_api(url, params=params)
            
            if response['statusCode'] != 200:
                print(f"Error fetching markets: {response['statusCode']}")
                break
            
            data = response['data']
            if not data:  # No more data, stop pagination
                break
            
            all_data.extend(data)
            
            offset += limit  # Increment offset for next page
    
        return all_data

    def get_gamma_status(self):
        url = 'https://gamma-api.polymarket.com/status'
        response = rC.make_request(url)
        if response.status_code != 200:
            print(f"Error fetching status: {response.status_code}")
            return None
        return response.text


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
            "closed": include_closed if include_closed else None,
            "active": active_only if active_only else None,
            "tag_id": tag_filter
            }
        
        url = 'https://gamma-api.polymarket.com/markets'

        if get_all_data:
            return self._get_all_responses(url, 500, params, True)
        else:
            response = self._call_gamma_api(url, params=params)
            if response['statusCode'] != 200:
                print(f"Error fetching markets: {response['statusCode']}")
                return []
            
            return response['data']
    
    
    ##############################
    # Event Methods
    ##############################
    def get_events(self, tag=None, include_closed=False, active_only=True, get_all_data=True):
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
        Returns
        -------
        list
            List of events
        """
        tag = self._parse_tag(tag)
        params = {
            "limit": 500,  # Max limit per request
            "tag_id": tag,
            "closed": include_closed if include_closed else None,
            "active": active_only if active_only else None
        }
        url = 'https://gamma-api.polymarket.com/events'
        
        if get_all_data:
            return self._get_all_responses(url, 500, params, True)
        else:
            response = self._call_gamma_api(url, params=params)
            if response['statusCode'] != 200:
                print(f"Error fetching events: {response['statusCode']}")
                return []
            return response['data']
        
    def get_event_by_id(self, event_id):
        response = self._call_gamma_api(f'https://gamma-api.polymarket.com/events/{event_id}')
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
        response = self._call_gamma_api(f'https://gamma-api.polymarket.com/events/slug/{event_slug}')
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
            return self._get_all_responses(url, 300, params, True)
        else:
            response = self._call_gamma_api(url, params=params)
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
        response = self._call_gamma_api(f'https://gamma-api.polymarket.com/tags/{tag_id}')
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
        
        response = self._call_gamma_api(f'https://gamma-api.polymarket.com/tags/{tag}/related-tags/tags')
        if response['statusCode'] != 200:
            print(f"Error fetching related tags: {response['statusCode']}")
            return []
        return response['data']
    