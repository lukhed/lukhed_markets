# Monitoring Polymarket Activity

This guide explains how to monitor Polymarket trading activity using the `lukhed_markets` library. There are two main monitoring strategies depending on your use case.

## Overview

The library provides **no-authentication-required** monitoring tools for:
1. **Whale Alerts** - Monitor specific markets for large trades (real-time websocket)
2. **User Tracking** - Monitor specific users' position changes (periodic polling)

Choose your strategy based on what you want to track:
- **Track big bets on specific markets?** → Use whale alerts (websocket)
- **Track a specific trader's activity?** → Use user position monitoring (polling)

---

## Strategy 1: Whale Alerts (Monitor Markets)

### When to Use
- You want to catch large trades on specific markets as they happen
- You're interested in WHO is making big bets on markets you care about
- You want real-time alerts when whales move

### How It Works
Connects to Polymarket's public websocket and filters trade messages by size or dollar value. When a trade exceeds your threshold, your callback is triggered instantly.

### Basic Example

```python
from lukhed_markets.polymarket import Polymarket
import time

pm = Polymarket()

# Monitor Trump market for trades over $10,000
ws = pm.monitor_market_for_whales(
    markets=["will-donald-trump-be-elected-president-in-2024"],
    min_trade_value=10000,  # $10k minimum
    callback=lambda trade: print(f"🐋 Whale alert! ${float(trade['size'])*float(trade['price']):,.0f}")
)

print("Monitoring... Press Ctrl+C to stop")
while True:
    time.sleep(1)
```

### Method Signature

```python
def monitor_market_for_whales(self, markets=None, asset_ids=None, 
                              min_trade_size=1000, min_trade_value=None, 
                              callback=None)
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `markets` | list | Yes* | List of market slugs or condition IDs to monitor |
| `asset_ids` | list | Yes* | List of asset IDs (token IDs) to monitor |
| `min_trade_size` | float | No | Minimum shares for alert (default: 1000) |
| `min_trade_value` | float | No | Minimum dollar value (overrides min_trade_size if provided) |
| `callback` | function | No | Function called with `(trade_data)` when whale detected |

*Provide either `markets` or `asset_ids`

### Trade Data Structure

```python
{
    'asset_id': str,          # Token ID
    'event_type': 'trade',
    'market': str,            # Condition ID
    'outcome': str,           # 'Yes' or 'No'
    'price': str,             # Price (e.g., "0.52")
    'side': str,              # 'BUY' or 'SELL'
    'size': str,              # Number of shares
    'status': str,            # 'MATCHED', 'MINED', 'CONFIRMED'
    'timestamp': str,
    'trade_owner': str        # Wallet address of trader
}
```

### Examples

**Monitor multiple markets:**
```python
ws = pm.monitor_market_for_whales(
    markets=[
        "will-donald-trump-be-elected-president-in-2024",
        "will-bitcoin-hit-100k-in-2024"
    ],
    min_trade_value=5000
)
```

**Filter by share size instead of value:**
```python
ws = pm.monitor_market_for_whales(
    markets=["bitcoin-market"],
    min_trade_size=10000  # 10k shares minimum
)
```

---

## Strategy 2: User Tracking (Monitor Positions)

### When to Use
- You want to track a specific whale/trader across ALL their positions
- You want to know when they enter or exit positions
- You want to see their portfolio changes over time

### How It Works
Polls the REST API every X seconds to check the user's current positions. Detects and reports new positions, changed positions (size increases/decreases), and closed positions.

### Basic Example

```python
from lukhed_markets import Polymarket
import time

pm = Polymarket()

# Track a specific user's positions
thread = pm.monitor_user_positions(
    address="0x0a9a7d6ae576a8f694656d683a7fab5ebf854129",
    poll_interval=30,  # Check every 30 seconds
    callback=lambda addr, positions, changes: print(
        f"📊 User activity: {len(changes['new'])} new, "
        f"{len(changes['changed'])} changed, {len(changes['closed'])} closed"
    )
)

print("Tracking user... Press Ctrl+C to stop")
while True:
    time.sleep(1)
```

### Method Signature

```python
def monitor_user_positions(self, address, poll_interval=60, callback=None)
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `address` | str | Yes | Public wallet address to monitor (0x-prefixed) |
| `poll_interval` | int | No | Seconds between checks (default: 60) |
| `callback` | function | No | Function called with `(address, positions, changes)` |

### Changes Structure

```python
{
    'new': [...]       # List of new positions
    'changed': [...]   # List of positions with size changes
    'closed': [...]    # List of closed positions
}
```

Each changed position includes:
```python
{
    'market': str,
    'outcome': str,
    'old_size': str,
    'new_size': str,
    'position': {...}  # Full position object
}
```

### Examples

**Track with detailed reporting:**
```python
def detailed_callback(address, all_positions, changes):
    if changes['new']:
        print(f"✅ Opened {len(changes['new'])} new position(s)")
        for pos in changes['new']:
            print(f"   • {pos['outcome']} - {pos['size']} shares")
    
    if changes['changed']:
        print(f"📈 Changed {len(changes['changed'])} position(s)")
        for change in changes['changed']:
            diff = float(change['new_size']) - float(change['old_size'])
            print(f"   • {change['outcome']}: {diff:+.0f} shares")

thread = pm.monitor_user_positions(
    address="0x123...",
    poll_interval=60,
    callback=detailed_callback
)
```

---

## Complete Example File

### `example_whale_alerts.py`
Comprehensive examples demonstrating all monitoring strategies:
- **Strategy 1**: Monitor single market for big bets (whale alerts)
- **Strategy 2**: Track specific user's portfolio (position tracking)
- **Strategy 3**: Monitor multiple top markets simultaneously
- **Strategy 4**: Discover top traders and track them automatically

Run it:
```bash
python example_whale_alerts.py
```

You'll be prompted to choose which strategy to run.

---

## Finding Market Slugs

Market slugs are in the Polymarket URL:
- URL: `https://polymarket.com/event/will-donald-trump-be-elected-president-in-2024`
- Slug: `will-donald-trump-be-elected-president-in-2024`

Or use the API:
```python
pm = Polymarket()
markets = pm.get_markets(get_all_data=False)
for market in markets[:10]:
    print(f"Slug: {market.get('slug', 'N/A')}")
```

## Finding User Addresses

Get top traders:
```python
leaders = pm.get_leaderboards(time_period='month', rank_by='profit')
for i, leader in enumerate(leaders[:10], 1):
    print(f"{i}. {leader['name']} - {leader['address']}")
```

Or check a market's top holders:
```python
event = pm.get_event_by_slug("trump-2024")
market_id = event['markets'][0]['conditionId']
top_holders = pm.get_top_holders_for_market(market_id)
```

---

## Key Differences Between Strategies

| Feature | Whale Alerts (Websocket) | User Tracking (Polling) |
|---------|--------------------------|-------------------------|
| **Speed** | Real-time (milliseconds) | Periodic (30-60s typical) |
| **What it tracks** | Specific markets | Specific users |
| **Best for** | Catching big bets as they happen | Portfolio tracking over time |
| **Efficiency** | High (only specified markets) | High (only one user's data) |
| **Data received** | Every trade on monitored markets | Position snapshots |

---

## Tips and Best Practices

1. **Start Small**: Test with 1-2 markets or users before scaling up
2. **Adjust Thresholds**: `min_trade_value` of $10k+ works well for whale hunting
3. **Poll Interval**: 30-60 seconds is usually sufficient for user tracking
4. **Keep Script Running**: Both methods run in background threads but need the main script alive
5. **Handle Interrupts**: Use try/except KeyboardInterrupt for clean exits

---

## Troubleshooting

**No alerts appearing (whale monitoring)?**
- Verify market slugs are correct
- Lower your `min_trade_value` threshold temporarily to test
- Check that the market is actively trading

**No changes detected (user monitoring)?**
- Confirm the address is correct (0x-prefixed, 40 hex chars)
- Check if user is actually trading (use `get_user_activity()`)
- Increase `poll_interval` if hitting rate limits

**Connection drops?**
- Websockets include auto-ping to maintain connection
- For production, add reconnection logic
- Consider error handling in your callbacks

---

## Requirements

```bash
pip install websocket-client
```

No authentication required for any monitoring features!
