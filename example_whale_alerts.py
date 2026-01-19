from lukhed_markets.polymarket import Polymarket
import time


# =============================================================================
# STRATEGY 1: Whale Alerts - Monitor Markets for Big Trades (WEBSOCKET)
# =============================================================================
# Use this when you want to know when ANYONE makes a large bet on specific markets
# Real-time, great for catching whale activity as it happens

def whale_alert_example(market_slug, dollar_threshold=2000):
    """Monitor market for trades at or over threshold"""
    
    pm = Polymarket()
    
    """
    Example of custom callback (in this example this is unused wince we will use the default print)
    
    def whale_callback(trade_data):
        size = float(trade_data.get('size', 0))
        price = float(trade_data.get('price', 0))
        value = size * price
        
        print(f"\n{'='*60}")
        print(f"🐋 WHALE ALERT: ${value:,.0f} trade!")
        print(f"{'='*60}")
        print(f"Market: {trade_data.get('market')}")
        print(f"Asset ID: {trade_data.get('asset_id', 'Unknown')}")
        print(f"Side: {trade_data.get('side')}")
        print(f"Size: {size:,.0f} shares @ ${price:.3f}")
        print(f"Time: {trade_data.get('timestamp', 'Unknown')}")
        print(f"{'='*60}\n")
    """
    
    # Monitor specified market for trades over $2k
    print("\n\n")
    ws = pm.monitor_market_for_whales(
        markets=[market_slug],
        min_trade_value=dollar_threshold,  # Use the provided threshold
        callback=None  # Use default print callback (or replace with whale_callback above)
    )
    
    print(f"🐋 Whale alert active! Monitoring for trades over ${dollar_threshold:,}")
    print("Press Ctrl+C to stop\n")
    
    # Keep running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Stopping whale alerts...")


# =============================================================================
# STRATEGY 2: User Tracking - Monitor Specific User's Positions (POLLING)
# =============================================================================
# Use this when you want to track a specific whale/trader across ALL their positions
# Polls every X seconds, detects new/changed/closed positions

def user_tracking_example():
    """Track a specific user's portfolio changes"""
    
    pm = Polymarket()
    
    # Example: Track a top leaderboard trader
    # You can get these addresses from: pm.get_leaderboards()
    USER_ADDRESS = "0x6a72f61820b26b1fe4d956e17b6dc2a1ea3033ee"  # an active all time leader
    
    """
    Example of custom callback function to handle position changes
    def position_callback(address, all_positions, changes):
        print(f"\n{'='*60}")
        print(f"📊 POSITION UPDATE: {address[:10]}...")
        print(f"{'='*60}")
        
        if changes['new']:
            print(f"\n✅ NEW POSITIONS ({len(changes['new'])}):")
            for pos in changes['new'][:3]:  # Show first 3
                print(f"   • {pos.get('outcome')} - Size: {pos.get('size', 0):.0f}")
        
        if changes['changed']:
            print(f"\n📈 CHANGED POSITIONS ({len(changes['changed'])}):")
            for change in changes['changed'][:3]:  # Show first 3
                old = change['old_size']
                new = change['new_size']
                diff = float(new) - float(old)
                direction = "↑" if diff > 0 else "↓"
                print(f"   {direction} {change['outcome']}: {old} → {new} ({diff:+.0f})")
        
        if changes['closed']:
            print(f"\n❌ CLOSED POSITIONS ({len(changes['closed'])}):")
            for pos in changes['closed'][:3]:  # Show first 3
                print(f"   • {pos.get('outcome')} - Was: {pos.get('size', 0):.0f}")
        
        print(f"\nTotal active positions: {len(all_positions)}")
        print(f"{'='*60}\n")
    """
    
    # Monitor user every 30 seconds
    thread = pm.monitor_user_positions(
        address=USER_ADDRESS,
        poll_interval=30,  # Check every 30 seconds
        callback=None  # Use default print callback (or replace with position_callback above)
    )
    
    print(f"📊 Tracking user {USER_ADDRESS[:10]}... positions")
    print("Checking every 30 seconds...")
    print("Press Ctrl+C to stop\n")
    
    # Keep running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Stopping user tracking...")


# =============================================================================
# STRATEGY 3: Multi-Market Whale Monitoring
# =============================================================================
# Monitor multiple high-volume markets simultaneously

def multi_market_whale_example():
    """Monitor top markets for large trades"""
    
    pm = Polymarket()
    
    # Get top markets by volume
    print("Fetching top markets by 24h volume...")
    events = pm.get_events(order_by='volume24hr', ascending=False, get_all_data=False)
    
    # Get slugs for top 5 markets
    top_market_slugs = [event['slug'] for event in events[:5]]
    
    print(f"\nMonitoring top 5 markets:")
    for i, slug in enumerate(top_market_slugs, 1):
        print(f"   {i}. {slug}")
    print()
    
    # Monitor for trades over $5000
    ws = pm.monitor_market_for_whales(
        markets=top_market_slugs,
        min_trade_value=5000,
        callback=lambda trade: print(
            f"🐋 ${float(trade['size'])*float(trade['price']):,.0f} {trade['side']} "
            f"on {trade['outcome']} @ ${float(trade['price']):.3f}"
        )
    )
    
    print("🐋 Monitoring top 5 markets for trades over $5,000")
    print("Press Ctrl+C to stop\n")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Stopping...")


# =============================================================================
# STRATEGY 4: Find and Track Top Whales
# =============================================================================
# Discover top traders and monitor their activity

def discover_and_track_whales():
    """Find top traders and track their positions"""
    
    pm = Polymarket()
    
    print("🔍 Finding top traders...")
    
    # Get monthly leaderboard
    leaders = pm.get_leaderboards(time_period='month', rank_by='profit')
    
    print(f"\n📊 Top 5 Traders This Month:")
    print("-" * 60)
    for i, leader in enumerate(leaders[:5], 1):
        print(f"{i}. {leader['name']}")
        print(f"   Address: {leader['address']}")
        print(f"   Profit: ${leader.get('profit', 0):,.2f}")
        print(f"   Volume: ${leader.get('volume', 0):,.2f}")
        print()
    
    # Track the #1 trader
    top_whale = leaders[0]['address']
    print(f"🎯 Now tracking #{1} trader: {top_whale[:10]}...")
    print()
    
    # Monitor their positions
    thread = pm.monitor_user_positions(
        address=top_whale,
        poll_interval=60,  # Check every minute
        callback=lambda addr, positions, changes: print(
            f"🚨 Top whale activity! "
            f"New: {len(changes['new'])}, "
            f"Changed: {len(changes['changed'])}, "
            f"Closed: {len(changes['closed'])}"
        )
    )
    
    print("Monitoring... Press Ctrl+C to stop\n")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Stopping...")


# =============================================================================
# Run Examples
# =============================================================================

if __name__ == "__main__":
    print("\n" + "="*60)
    print("Polymarket Whale Alert Examples")
    print("="*60)
    print("\nChoose a strategy:")
    print("1. Whale Alerts - Monitor market for big trades (websocket)")
    print("2. User Tracking - Monitor specific user positions (polling)")
    print("3. Multi-Market - Monitor top markets for whales")
    print("4. Discover & Track - Find and track top traders")
    print()
    
    choice = input("Enter choice (1-4) or press Enter for #1: ").strip() or "1"
    
    if choice == "1":
        market_slug = input("Enter market slug to monitor (e.g., from event url, cbb-nd-vtech-2026-01-17): ").strip()
        whale_alert_example(market_slug)
    elif choice == "2":
        user_tracking_example()
    elif choice == "3":
        multi_market_whale_example()
    elif choice == "4":
        discover_and_track_whales()
    else:
        print("Invalid choice, running whale alerts...")
        whale_alert_example()
