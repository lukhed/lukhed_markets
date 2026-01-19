# lukhed_markets

Python API wrappers and utilities for prediction markets and economic data. 
Includes wrappers for Kalshi, Polymarket, and FRED (Federal Reserve Economic Data).

## Table of Contents

- [Installation](#installation)
- [Features](#features)
- [Kalshi API](#kalshi-api)
- [Polymarket API](#polymarket-api)
- [FRED API](#fred-api)
- [Documentation & Resources](#documentation--resources)

## Installation

```bash
pip install lukhed-markets
```

## Features

- **Kalshi API**: Wrapper for Kalshi prediction markets with custom discovery methods
- **Polymarket API**: Real-time, customizable alerts, user position tracking, and transaction analysis
- **FRED API**: Wrapper for Federal Reserve Economic Data with built-in analysis and plotting capabilities
- **Automatic pagination**: Handles paginated responses seamlessly
- **Rate limiting**: Built-in rate limiting based on API plan tiers
- **Secure authentication**: Integrated key management with local or GitHub storage options

---

## Kalshi API

A Python wrapper for the Kalshi Elections API providing access to prediction market data and trading functionality.

### Quick Start

```python
from lukhed_markets.kalshi import Kalshi

# First time setup (guided authentication)
client = Kalshi(api_delay='basic', key_management='github')

# Subsequent usage
client = Kalshi()
```

### Authentication Setup

1. Create a Kalshi account at https://kalshi.com
2. Generate API keys from your [account profile](https://kalshi.com/account/profile)
3. Download your private key file
4. Run the initialization - the guided setup will prompt you for credentials

### Rate Limiting

The wrapper includes built-in rate limiting based on your API plan:
- **Basic**: 10 read/sec, 5 write/sec
- **Advanced**: 30 read/sec, 30 write/sec
- **Premier**: 100 read/sec, 100 write/sec
- **Prime**: 100 read/sec, 400 write/sec

### Core API Methods

#### Markets
- `get_markets(limit, cursor, event_ticker, series_ticker, ...)` - Get market data with filtering
- `get_market(ticker)` - Get specific market details
- `get_market_candlesticks(series_ticker, ticker, start_ts, end_ts, period_interval)` - Historical price data
- `get_market_orderbook(ticker, depth)` - Current orderbook
- `get_market_spread(ticker, depth)` - Calculate bid-ask spread

#### Events & Series
- `get_events(limit, cursor, status, series_ticker, ...)` - Get event data
- `get_event(event_ticker, with_nested_markets)` - Get specific event
- `get_series(series_ticker)` - Get series information
- `get_all_available_events(status, series_ticker, ...)` - Auto-paginated event retrieval

#### Exchange Information
- `get_exchange_status()` - Current exchange status
- `get_exchange_schedule()` - Exchange schedule
- `get_exchange_announcements()` - Exchange-wide announcements
- `get_milestones(limit, cursor, ...)` - Milestone data

#### Search & Discovery
- `get_tags_for_series_categories()` - Series category tags mapping
- `get_filters_by_sport()` - Sports filtering options

#### Account (Authentication Required)
- `get_account_balance()` - Get account balance

### Custom Discovery Methods

Convenience methods for common market queries:

```python
# Get all S&P 500 year-end range markets
sp500_markets = client.get_sp500_year_end_range_markets(active_only=True)

# Get NASDAQ year-end range markets
nasdaq_markets = client.get_nasdaq_year_end_range_markets(force_year=2026)

# Get Bitcoin yearly high markets
btc_markets = client.get_bitcoin_yearly_high_markets(active_only=True)

# Get markets by category
economics_series = client.get_economics_series()
inflation_series = client.get_inflation_series()
fed_series = client.get_fed_series()
```

### Example Usage

```python
from lukhed_markets.kalshi import Kalshi

# Initialize client
client = Kalshi()

# Get active markets
markets = client.get_markets(limit=100, status='open')

# Get specific market with orderbook
market = client.get_market("INXD-26DEC31-T5000")
orderbook = client.get_market_orderbook("INXD-26DEC31-T5000", depth=5)

# Get historical candlestick data
candles = client.get_market_candlesticks(
    series_ticker="INXD",
    ticker="INXD-26DEC31-T5000",
    start_ts="20260101000000",
    end_ts="20260115000000",
    period_interval="1h"
)

# Get all events with pagination handled automatically
all_events = client.get_all_available_events(status='open')
```

---

## Polymarket API

A Python wrapper for Polymarket's Gamma API (markets, events, tags) and Data API (user activity, positions, leaderboards).

### Quick Start

```python
from lukhed_markets.polymarket import Polymarket

# Initialize (no authentication required for public endpoints)
pm = Polymarket(api_delay=0.1)
```

### Key Features

- **Market & Event Discovery**: Search and filter markets/events with automatic pagination
- **User Activity Tracking**: Monitor positions, trades, and portfolio changes
- **Whale Alerts**: Real-time monitoring for large trades via WebSockets
- **Transaction Analysis**: Parse blockchain transactions to identify traders

### Core API Methods

#### Markets & Events
```python
# Get markets with filtering
markets = pm.get_markets(tag_filter='politics', active_only=True, get_all_data=True)

# Get events
events = pm.get_events(tag='crypto', order_by='volume', ascending=False)

# Get specific event
event = pm.get_event_by_slug('presidential-election-2024')
```

#### User Data
```python
# Get user positions (active only)
positions = pm.get_current_positions_for_user(
    address="0x123...",
    redeemable=False,  # Exclude resolved markets
    get_all_data=True
)

# Get user trading activity
activity = pm.get_user_activity(
    address="0x123...",
    activity_type_list=["TRADE"],
    side="BUY",
    get_all_data=True
)

# Get leaderboard
leaderboard = pm.get_leaderboards(
    category='POLITICS',
    time_period='MONTH',
    rank_by='profit'
)
```

#### Real-time Monitoring
```python
# Monitor markets for large trades (whale alerts)
ws = pm.monitor_market_for_whales(
    markets=["presidential-election-2024"],
    min_trade_value=5000,
    callback=lambda trade: print(f"🐋 ${trade['size']*trade['price']:.0f} trade")
)

# Monitor user positions (polling)
thread = pm.monitor_user_positions(
    address="0x123...",
    poll_interval=60,
    callback=my_callback_function
)
```

### Example Usage

See [example_whale_alerts.py](example_whale_alerts.py) for complete examples including:
- **Strategy 1**: Whale alerts - Monitor markets for large trades via WebSocket
- **Strategy 2**: User position tracking - Monitor specific user portfolios via polling

```python
from lukhed_markets.polymarket import Polymarket

# Initialize
pm = Polymarket()

# Get top holders for a market
holders = pm.get_top_holders_for_market(
    market_condition_id="0xabc...",
    min_balance=100
)

# Get transaction details
trader = pm.get_trader_from_transaction(
    tx_hash="0x123...",
    buy_or_sell="buy"
)
print(f"Trader: {trader['trader']}")
```

---

## FRED API

A Python wrapper for the Federal Reserve Economic Data (FRED) API with built-in data analysis and 
visualization capabilities. Built on top of [fredapi](https://github.com/mortada/fredapi).

### Quick Start

```python
from lukhed_markets.fred import FRED

# First time setup (guided authentication)
fred = FRED(key_management='github')

# Or provide key directly
fred = FRED(provide_key='your-fred-api-key')
```

### Authentication Setup

1. Sign up for a free FRED account at https://fred.stlouisfed.org/docs/api/fred/
2. Get your API key from https://fredaccount.stlouisfed.org/apikeys
3. Run initialization - the guided setup will prompt for your key

### Available Data Series

#### Inflation & Prices
```python
# Get PCE inflation data with YoY rates calculated
pce_data = fred.get_pce_inflation_rate(
    start_date='2020-01-01',
    end_date='2025-12-31',
    date_format='%Y-%m-%d'
)
# Returns DataFrame with columns: ['PCEPI', 'yoy_inflation']
```

#### Employment
```python
# Get manufacturing employment data
employment = fred.get_manufacturing_employees(
    start_date='2020-01-01',
    end_date='2025-12-31'
)
```

#### Government Finance
```python
# Get federal government interest payments to rest of world
interest_payments = fred.federal_governemnt_interest_payments_to_row(
    start_date='2020-01-01',
    end_date='2025-12-31'
)
```

### Plotting & Visualization

```python
# Plot PCE inflation with Fed target and averages
fred.plot_pce_inflation_rate(
    start_date='2015-01-01',
    end_date='2025-12-31',
    include_averages=True,  # Show Fed 2% target and actual average
    show_plot=True,
    save_plots=True  # Saves to 'plots/' directory
)
```

### Direct FRED API Access

```python
# Access underlying fredapi instance for any FRED series
fred.api.get_series('GDP')  # Get any FRED series by ID
fred.api.get_series_info('UNRATE')  # Get series metadata
```

### Example Usage

```python
from lukhed_markets.fred import FRED
import pandas as pd

# Initialize
fred = FRED()

# Get PCE inflation data
inflation = fred.get_pce_inflation_rate(
    start_date='2020-01-01',
    end_date='2025-12-31'
)

# Analyze inflation trends
recent_avg = inflation['yoy_inflation'].tail(12).mean()
print(f"Average inflation (last 12 months): {recent_avg:.2f}%")

# Create visualization
fred.plot_pce_inflation_rate(
    start_date='2015-01-01',
    include_averages=True,
    save_plots=True
)

# Get manufacturing employment trends
employment = fred.get_manufacturing_employees(start_date='2020-01-01')
print(f"Current manufacturing employment: {employment.iloc[-1].values[0]:,.0f}")
```

---

## Documentation & Resources

### API Documentation
- **Kalshi**: https://trading-api.readme.io/reference/
- **Polymarket Gamma API**: https://docs.polymarket.com/developers/gamma-markets-api/overview
- **Polymarket Data API**: https://docs.polymarket.com/developers/data-api/overview
- **Polymarket CLOB**: https://github.com/Polymarket/py-clob-client
- **FRED**: https://fred.stlouisfed.org/docs/api/fred/

### Dependencies
- `lukhed-basic-utils>=1.6.9` - Core utilities for authentication and requests
- `fredapi>=0.5.2` - FRED API client
- `py_clob_client>=0.34.1` - Polymarket CLOB client
- Python 3.10+

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Author

**lukhed**  
Email: lukhed.mail@gmail.com  
GitHub: https://github.com/lukhed/lukhed_markets
