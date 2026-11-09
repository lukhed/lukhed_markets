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
- **Polymarket API**: Market discovery, user positions and trades, real-time whale alerts and position tracking
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

A Python wrapper for Polymarket's Gamma API (markets, events, tags, comments) and Data API v2 (users,
positions, trades, holders, leaderboards), with real-time whale alerts and position tracking. Public data
needs no authentication.

> **0.4.0 is a breaking release.** Polymarket retired Data API v1 on Nov 2, 2026 and the legacy
> `py-clob-client` on Apr 28, 2026. See [Upgrading from 0.3](#upgrading-from-03) below.

### Quick Start

```python
import logging
from lukhed_markets.polymarket import Polymarket, PolymarketAPIError

logging.basicConfig(level=logging.INFO)   # optional: show progress and monitor messages

pm = Polymarket(api_delay=0.1)            # api_delay = minimum seconds between requests
```

### Key Features

- **Market & Event Discovery**: Search and filter markets/events with automatic cursor pagination
- **User Data**: Positions (open, closed, redeemable), activity, trades and leaderboards
- **Whale Alerts**: Real-time large-trade monitoring over the public websocket, with the trader's wallet
- **Reliable by default**: Retries rate limits (honoring `Retry-After`) and server errors, reconnects
  websockets, and raises `PolymarketAPIError` instead of silently returning empty results

### Core API Methods

#### Markets & Events
```python
# Markets (tag can be a tag id or slug, e.g. 'politics')
markets = pm.get_markets(tag_filter='politics', max_results=200)

# Top events by 24h volume
events = pm.get_events(order='volume24hr', ascending=False, max_results=10)

# Specific event or market (None if it doesn't exist)
event = pm.get_event_by_slug('fed-decision-in-january')
market = pm.get_market_by_slug('xi-jinping-out-before-2027')
```

#### User Data
```python
# Open positions (status can also be CLOSED, REDEEMABLE, REDEEMABLE_LOST or MERGEABLE)
positions = pm.get_current_positions_for_user(address="0x123...", get_all_data=True)

# Trading activity
activity = pm.get_user_activity(address="0x123...", activity_type_list=["TRADE"], side="BUY")

# Large trades in a market, with each trader's wallet
trades = pm.get_trades(condition_id="0xabc...", min_trade_value=5000, taker_only=True)

# Leaderboard, or one user's standing
leaderboard = pm.get_leaderboards(category='POLITICS', time_period='MONTH', rank_by='profit')
standing = pm.get_leaderboards(single_user_check="0x123...")

# Top holders of a market
holders = pm.get_top_holders_for_market(market_condition_id="0xabc...", min_balance=100)
```

#### Real-time Monitoring
```python
# Whale alerts: event slugs, market slugs or condition ids
monitor = pm.monitor_market_for_whales(
    markets=["fed-decision-in-january"],
    min_trade_value=5000,
    callback=lambda t: print(f"🐋 ${t['trade_value']:,.0f} {t['side']} {t['outcome']} by {t['trader']}")
)

# Position tracking (polling); callback receives (address, positions, changes)
tracker = pm.monitor_user_positions(address="0x123...", poll_interval=60)

monitor.stop()
tracker.stop()
```

See [example_whale_alerts.py](example_whale_alerts.py) for complete examples.

#### Errors
```python
try:
    positions = pm.get_current_positions_for_user("0x123...")
except PolymarketAPIError as e:
    print(e.status_code, e)
```

### Authenticated trading

`PolymarketAuth` adds a trading client from Polymarket's unified SDK as `pm.api`. It needs Python 3.11+:

```bash
pip install "lukhed-markets[polymarket-trading]"
```

```python
from lukhed_markets.polymarket import PolymarketAuth

pm = PolymarketAuth()   # first run in a terminal starts a guided setup
pm.api                  # polymarket.SecureClient: see https://docs.polymarket.com/trading/quickstart
```

Credentials (wallet private key and Polymarket wallet address) are stored with lukhed key management, or
passed directly with `PolymarketAuth(auth_data={'private_key': ..., 'wallet': ...})`. Credentials saved
by 0.3 are picked up automatically. Note that Polymarket now trades in pUSD; API-only traders must wrap
USDC.e into pUSD (see the [V2 migration guide](https://docs.polymarket.com/v2-migration)).

### Upgrading from 0.3

- **Data API v2 field names are snake_case**: e.g. `proxyWallet` → `proxy_wallet`, `size` →
  `current_size`, `avgPrice` → `avg_price`, `currentValue` → `current_value`, `conditionId` →
  `condition_id`. Leaderboard entries use `user_id`, `user_name`, `pnl`, `volume`.
- **Errors raise `PolymarketAPIError`** instead of printing and returning `[]` / `None`.
- **`get_current_positions_for_user`**: `market` → `condition_id`; `redeemable` / `mergeable` →
  `status`; sort fields are now CURRENT_VALUE, PRICE, TOKENS, UNREALIZED_PNL, REALIZED_PNL, TOTAL_PNL,
  TIMESTAMP.
- **`get_leaderboards(single_user_check=...)`** returns the user's standing dict; username lookups are
  no longer supported by the API.
- **`get_trader_from_transaction(tx_hash, condition_id)`** now uses the Data API (the public Polygon RPC
  it relied on is gone), so it needs the market's condition id. `web3` is no longer a dependency.
- **Monitors**: `monitor_market_for_whales` returns a `WhaleMonitor` and `monitor_user_positions` a
  `PositionMonitor` (a `threading.Thread`); both have `.stop()`. Position-change callbacks always get a
  dict with `initial`, `new`, `changed` and `closed`.
- **`list_comments`** accepts Event or Series (markets have no comment threads of their own).
- **`Polymarket()`** no longer makes network calls or prints on construction (`check_status=True` to
  opt in); progress goes through `logging`.
- **`PolymarketAuth`** uses the unified SDK (`pm.api` is a `polymarket.SecureClient`, not a
  `ClobClient`) and never prompts when run non-interactively.

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
- **Polymarket Gamma API**: https://docs.polymarket.com/market-data/overview
- **Polymarket Data API v2**: https://docs.polymarket.com/api-reference/data-api/overview
- **Polymarket unified SDK**: https://docs.polymarket.com/migrate/clob-sdk-to-unified-sdk
- **FRED**: https://fred.stlouisfed.org/docs/api/fred/

### Dependencies
- `lukhed-basic-utils>=1.6.9` - Core utilities for authentication and requests
- `fredapi>=0.5.2` - FRED API client
- `polymarket-client>=0.17.0` - Polymarket unified SDK (optional, `[polymarket-trading]` extra)
- Python 3.10+

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Author

**lukhed**  
Email: lukhed.mail@gmail.com  
GitHub: https://github.com/lukhed/lukhed_markets
