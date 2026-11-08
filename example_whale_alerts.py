from lukhed_markets.polymarket import Polymarket
import logging
import time

# Show connection, reconnect and lookup messages from the monitors
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("websocket").setLevel(logging.WARNING)


def wait_until_interrupted(monitor, message="Stopping..."):
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n👋 {message}")
        monitor.stop()


# =============================================================================
# STRATEGY 1: Whale Alerts - Monitor Markets for Big Trades (WEBSOCKET)
# =============================================================================
# Use this when you want to know when ANYONE makes a large bet on specific markets
# Real-time, great for catching whale activity as it happens

def whale_alert_example(market_slug, dollar_threshold=2000):
    """Monitor market for trades at or over threshold"""

    pm = Polymarket()

    """
    Example of a custom callback (unused here: the default callback prints each trade).
    The trade dict is the websocket last_trade_price message plus trade_value, question, outcome,
    and the trader's wallet (trader / trader_name) once the Data API has indexed the trade.

    def whale_callback(trade):
        print(f"🐋 ${trade['trade_value']:,.0f} {trade['side']} {trade['outcome']} on {trade['question']}")
        if trade['trader']:
            print(f"   by {trade['trader_name']} https://polymarket.com/profile/{trade['trader']}")
    """

    print("\n\n")
    monitor = pm.monitor_market_for_whales(
        markets=[market_slug],
        min_trade_value=dollar_threshold,
        callback=None  # Use default print callback (or replace with whale_callback above)
    )

    print(f"🐋 Whale alert active! Monitoring for trades over ${dollar_threshold:,}")
    print("Press Ctrl+C to stop\n")
    wait_until_interrupted(monitor, "Stopping whale alerts...")


# =============================================================================
# STRATEGY 2: User Tracking - Monitor Specific User's Positions (POLLING)
# =============================================================================
# Use this when you want to track a specific whale/trader across ALL their positions
# Polls every X seconds, detects new/changed/closed positions

def user_tracking_example(user_address):
    """Track a specific user's portfolio changes"""

    pm = Polymarket()

    """
    Example of a custom callback. It is called after every poll; changes['initial'] is True on the first.

    def position_callback(address, all_positions, changes):
        if changes['initial']:
            print(f"Tracking {len(all_positions)} open positions for {address[:10]}...")
            return
        for pos in changes['new']:
            print(f"✅ NEW: {pos['outcome']} on {pos['title']} - {pos['current_size']:.0f} shares")
        for change in changes['changed']:
            print(f"📈 {change['outcome']}: {change['old_size']:.0f} → {change['new_size']:.0f}")
        for closed in changes['closed']:
            final = closed['final_position'] or {}
            print(f"❌ CLOSED ({closed['reason']}): {closed['position']['title']} "
                  f"realized P&L {final.get('realized_pnl', 0):+.2f}")
    """

    monitor = pm.monitor_user_positions(
        address=user_address,
        poll_interval=30,  # Check every 30 seconds
        callback=None  # Use default print callback (or replace with position_callback above)
    )

    print(f"📊 Tracking user {user_address[:10]}... positions")
    print("Checking every 30 seconds...")
    print("Press Ctrl+C to stop\n")
    wait_until_interrupted(monitor, "Stopping user tracking...")


# =============================================================================
# STRATEGY 3: Multi-Market Whale Monitoring
# =============================================================================
# Monitor multiple high-volume markets simultaneously

def multi_market_whale_example(dollar_threshold=2000):
    """Monitor top markets for large trades"""

    pm = Polymarket()

    print("Fetching top events by 24h volume...")
    events = pm.get_events(order='volume24hr', ascending=False, max_results=5)
    top_event_slugs = [event['slug'] for event in events]

    print(f"\nMonitoring top {len(top_event_slugs)} events:")
    for i, slug in enumerate(top_event_slugs, 1):
        print(f"   {i}. {slug}")
    print()

    monitor = pm.monitor_market_for_whales(
        markets=top_event_slugs,
        min_trade_value=dollar_threshold,
        callback=lambda trade: print(
            f"🐋 ${trade['trade_value']:,.0f} {trade['side']} on {trade['outcome']} @ ${float(trade['price']):.3f}"
            f" | {trade['question']} | trader: {trade['trader_name'] or trade['trader'] or 'unknown'}"
        )
    )

    print(f"🐋 Monitoring top events for trades over ${dollar_threshold:,}")
    print("Press Ctrl+C to stop\n")
    wait_until_interrupted(monitor)


# =============================================================================
# STRATEGY 4: Find and Track Top Whales
# =============================================================================
# Discover top traders and monitor their activity

def discover_and_track_whales():
    """Find top traders and track their positions"""

    pm = Polymarket()

    print("🔍 Finding top traders...")
    leaders = pm.get_leaderboards(time_period='month', rank_by='profit', limit=5)

    print("\n📊 Top 5 Traders This Month:")
    print("-" * 60)
    for leader in leaders[:5]:
        print(f"{leader['rank']}. {leader.get('user_name') or 'Unknown'}")
        print(f"   Address: {leader['user_id']}")
        print(f"   Profit: ${leader.get('pnl', 0):,.2f}")
        print(f"   Volume: ${leader.get('volume', 0):,.2f}")
        print()

    top_whale = leaders[0]['user_id']
    print(f"🎯 Now tracking #1 trader: {top_whale[:10]}...")
    print()

    monitor = pm.monitor_user_positions(
        address=top_whale,
        poll_interval=30,  # Check every 30 seconds
        callback=None
    )

    print("Monitoring... Press Ctrl+C to stop\n")
    wait_until_interrupted(monitor)


# =============================================================================
# Run Examples
# =============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Polymarket Whale Alert Examples")
    print("=" * 60)
    print("\nChoose a strategy:")
    print("1. Whale Alerts - Monitor market for big trades (websocket)")
    print("2. User Tracking - Monitor specific user positions (polling)")
    print("3. Multi-Market - Monitor top markets for whales")
    print("4. Discover & Track - Find and track top traders")
    print()

    choice = input("Enter choice (1-4) or press Enter for #1: ").strip() or "1"

    if choice == "2":
        user_address = input("Enter user address to monitor (e.g., 0x1234...): ").strip()
        user_tracking_example(user_address)
    elif choice == "3":
        multi_market_whale_example()
    elif choice == "4":
        discover_and_track_whales()
    else:
        if choice != "1":
            print("Invalid choice, running whale alerts...")
        market_slug = input("Enter event or market slug to monitor (e.g., from the event url, "
                            "cbb-nd-vtech-2026-01-17): ").strip()
        whale_alert_example(market_slug)
