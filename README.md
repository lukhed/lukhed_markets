# lukhed_markets

A collection of API wrappers and functions dealing with broad markets.

## Kalshi API Wrapper

A Python wrapper for the Kalshi Elections API that provides easy access to market data and trading functionality.

### Features

- Configurable API rate limiting based on your plan tier (Basic, Advanced, Premier, Prime)
- Authentication handling with PSS signing
- Simple setup process for API credentials
- Comprehensive market data access

### Installation

```python
pip install lukhed-markets
```

### Authentication Setup

1. Create a Kalshi account at https://kalshi.com
2. Generate API keys from your account profile
3. Download your private key file
4. Initialize the Kalshi class with `kalshi_setup=True` to run the guided setup

```python
from lukhed_markets.kalshi import Kalshi

# First time setup
client = Kalshi(kalshi_setup=True)

# Subsequent usage
client = Kalshi()
```

### Available Methods

#### Public Endpoints
- `get_markets()` - Get data about all markets
- `get_market(ticker)` - Get data about a specific market
- `get_events()` - Get data about all events
- `get_event(event_ticker)` - Get data about a specific event
- `get_series(series_ticker)` - Get data about a specific series
- `get_market_candlesticks()` - Get historical candlestick data
- `get_market_orderbook()` - Get orderbook data
- `get_exchange_announcements()` - Get exchange announcements
- `get_exchange_schedule()` - Get exchange schedule
- `get_exchange_status()` - Get exchange status
- `get_milestones()` - Get milestone data

#### Authentication Required Endpoints
- `get_account_balance()` - Get account balance

#### Custom Helpers
- `get_all_available_events()` - Get all available events with automatic pagination
- `get_sp500_year_end_range_markets()` - Get S&P 500 year-end range markets
- `get_nasdaq_year_end_range_markets()` - Get NASDAQ year-end range markets
- `get_bitcoin_yearly_high_markets()` - Get Bitcoin yearly high markets

### API Rate Limits

The wrapper includes built-in rate limiting based on your API plan:
- Basic: 10 read/sec, 5 write/sec
- Advanced: 30 read/sec, 30 write/sec
- Premier: 100 read/sec, 100 write/sec
- Prime: 100 read/sec, 400 write/sec

### Example Usage

```python
from lukhed_markets.kalshi import Kalshi

# Initialize client
client = Kalshi()

# Get market data
markets = client.get_markets(limit=10)

# Get specific market details
market = client.get_market("MARKET-TICKER")

# Get account balance
balance = client.get_account_balance()
