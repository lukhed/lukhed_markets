"""
NFL odds from Polymarket, sportsbook style.

Odds are fee-inclusive American odds from the live order book: the price you would actually pay to back
each side right now.
"""
from lukhed_markets.polymarket_nfl import PolymarketNFL
from lukhed_markets.polymarket_sportsbook import odds_to_rows


def fmt_point(market, outcome):
    if outcome['point'] is None:
        return ''
    return f"{outcome['point']:+g}" if market['key'] == 'spreads' else f"{outcome['point']:g}"


def fmt_odds(outcome):
    american = outcome['odds']['american']
    return '  off' if american is None else f"{american:+5d}"


def print_board(nfl, week=None):
    week = week or nfl.get_current_week()
    print(f"\nNFL Week {week} odds (Polymarket)\n" + "=" * 96)
    for game in nfl.get_week_odds(week):
        away, home = game['away_team'], game['home_team']
        status = game['status']
        if game['score'] and status != 'scheduled':
            status += f" {game['score']['away']}-{game['score']['home']} {game['period'] or ''}"
        else:
            status = f"{game['start_time']:%a %m/%d %H:%M} UTC"
        print(f"{away['name']} @ {home['name']}  ({status})")
        for market in game['markets']:
            sides = '   '.join(f"{o['name']} {fmt_point(market, o)} {fmt_odds(o)}" for o in market['outcomes'])
            flag = '' if market['liquid'] else '  (thin)'
            print(f"   {market['key']:<10} {sides}   hold {market['hold']:.1%}{flag}" if market['hold'] is not None
                  else f"   {market['key']:<10} {sides}{flag}")
        print()


def print_game_detail(nfl, team):
    game = nfl.get_games(team=team, status=('scheduled', 'live'))[0]
    print(f"\n{game['title']} - alternate spreads and team totals\n" + "-" * 60)
    odds = nfl.get_odds(game, markets=['spreads', 'team_totals'], lines='all')
    for market in odds['markets']:
        if not market['liquid']:
            continue
        main = '*' if market['is_main'] else ' '
        sides = '   '.join(f"{o['name']} {fmt_point(market, o)} {fmt_odds(o)}" for o in market['outcomes'])
        print(f" {main} {market['key']:<11} {market['subject'] or '':<10} {sides}")

    print(f"\nPlayer props (main lines)\n" + "-" * 60)
    props = nfl.get_props(game, prop_types=['passing_yards', 'rushing_yards', 'receiving_yards', 'anytime_touchdowns'])
    for prop in props['props']:
        if prop['liquid']:
            sides = '   '.join(f"{o['name']} {fmt_point(prop, o)} {fmt_odds(o)}" for o in prop['outcomes'])
            print(f"   {prop['player']:<22} {prop['key']:<20} {sides}")


def print_futures(nfl):
    print("\nChampionship odds\n" + "-" * 60)
    for selection in nfl.get_super_bowl_odds()['selections'][:10]:
        print(f"   {selection['name']:<28} {fmt_odds(selection)}")


def print_player_page(nfl, name):
    """A sportsbook-style player page: every stat's ladder, main line (*) and market-implied median."""
    page = nfl.get_player_props(name)
    game = page['game']
    print(f"\n{page['player']} ({page['team']} vs {page['opponent']}, {game['start_time']:%a %m/%d %H:%M} UTC)")
    print("-" * 72)
    for prop in page['props']:
        median = f"   implied median {prop['implied_median']}" if prop['implied_median'] is not None else ""
        print(f" {prop['type']}{median}")
        for rung in prop['lines']:
            over, under = rung['outcomes']
            line = '' if rung['line'] is None else f"{rung['line']:g}"
            prob = f"{rung['probability']:.0%}" if rung['probability'] is not None else '  - '
            main = '*' if rung['is_main'] else ' '
            thin = '' if rung['liquid'] else '  (thin)'
            print(f"   {main} {line:>6}  {over['name']} {fmt_odds(over)}  {under['name']} {fmt_odds(under)}"
                  f"  fair {prob}{thin}")


def print_props_screen(nfl, prop_type='rushing_yards'):
    """Every player's main line for one prop type this week, liquid lines only."""
    print(f"\n{prop_type} - main lines this week\n" + "-" * 72)
    for game in nfl.get_props_board(prop_types=prop_type):
        for prop in game['props']:
            if prop['liquid']:
                over, under = prop['outcomes']
                print(f"   {prop['player']:<24} {prop['team'] or '':<12} {prop['line']:>6g}"
                      f"   Over {fmt_odds(over)}   Under {fmt_odds(under)}")


if __name__ == "__main__":
    nfl = PolymarketNFL()
    print_board(nfl)
    print_game_detail(nfl, team='KC')
    print_futures(nfl)
    print_player_page(nfl, 'Mahomes')
    print_props_screen(nfl, 'rushing_yards')

    # Everything as a table, e.g. for pandas: pandas.DataFrame(rows)
    rows = odds_to_rows(nfl.get_week_odds())
    print(f"\n{len(rows)} rows, e.g. {rows[0]}")
