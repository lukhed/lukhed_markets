from lukhed_basic_utils import timeCommon as tC
from lukhed_basic_utils import requestsCommon as rC
from py_clob_client.client import ClobClient
from .polymarket_tags import TAG_MAPPING
import json

class Polymarket:
    """
    This class wraps the polymarket gamma and data APIs and adds custom discovery methods for convenience. 
    It also allows access to py-clob-client via self.clob_api for the clob API.

    clob_api documentation: https://github.com/Polymarket/py-clob-client
    gamma_api documentation: https://docs.polymarket.com/developers/gamma-markets-api/overview
    data_api documentation: https://docs.polymarket.com/developers/data-api/overview
    """
    def __init__(self, api_delay=0.1):
        self.delay = api_delay
        self.clob_api = ClobClient("https://clob.polymarket.com")
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
            start_date = tC.convert_to_unix(start_date, date_format=date_format)
        if end_date:
            end_date = tC.convert_to_unix(end_date, date_format=date_format)

        return start_date, end_date
    
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
                          start_date=None, end_date=None, date_format="%Y-%m-%d"):
        start_date, end_date = self._parse_date_inputs(start_date, end_date, date_format=date_format)
        
        # working timestamp conversion test
        utc_tz = tC.ZoneInfo("UTC")
        utc_dt = tC.datetime.fromtimestamp(1767664039, tz=utc_tz)
        eastern_tz = tC.ZoneInfo("America/New_York")
        eastern_dt = utc_dt.astimezone(eastern_tz)
        
        limit = 5
        params = {
            "user": address,
            "limit": limit,  # Max limit per request
            "type": ','.join(activity_type_list),
            "sortBy": "TIMESTAMP",
            "sortDirection": "DESC",
            "side": side.upper() if side else None
        }
        url = f'https://data-api.polymarket.com/activity'

        if get_all_data:
            return self._call_api_get_all_responses(url, limit, params, True)
        else:
            response = self._call_api(url, params=params)
            if response['statusCode'] != 200:
                print(f"Error fetching events: {response['statusCode']}")
                return []
            return response['data']