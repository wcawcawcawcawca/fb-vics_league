"""
step4_heatmap.py
==================
WHIP/BABIP monthly heatmap, all 12 teams, WHOLE STAFF (including relief
innings -- this is the one step that does NOT apply the genuine-starter
filter; it's about total team pitching contribution, not just starters).

*** CRITICAL METHODOLOGY -- READ BEFORE TOUCHING THIS FILE ***

This step was the source of a real, confirmed bug (twice) and now carries a
mandatory sanity check as a result. Do not simplify this back to "whichever
team currently rosters the pitcher" -- that was tried and is wrong.

Correct attribution for each pitcher-appearance requires BOTH:
  1. DATE-ACCURATE ROSTER: use the periods[] snapshot from that game's own
     dateET (checked across all 12 teams' pitcher lists), never the
     current/latest roster. Attributing a whole season of appearances to a
     pitcher's CURRENT team undercounts/miscounts badly -- confirmed to
     undercount a team's season IP by ~440 innings, because it misses
     innings earned by since-dropped/traded pitchers and misattributes
     historical innings to teams that didn't have that pitcher at the time.
  2. ACTIVE-SLOT FILTER: within that date's snapshot, the pitcher's slot
     must be active === True. Bench/IL innings don't count toward a team's
     cumulative total -- ESPN only credits IP when the pitcher was active
     before the game's first pitch. Skipping this filter (i.e. counting
     ALL rostered pitchers regardless of active status) OVERcounts every
     team's IP by 20-450+ innings depending on roster turnover.

Applying BOTH corrections reconciles every one of the 12 teams' computed IP
to within ~0.2-4.0 IP of the bookmarklet's own season-cumulative snap.IP
value. That reconciliation is not optional -- see `reconcile()` below and
the mandatory gate in `main()`.

This active-slot + date-accurate roster requirement is SPECIFIC TO STEP 4.
Steps 2/3/5 intentionally use current roster without an active-slot filter,
because they're about current staff / current free agents, not a
season-long IP reconciliation.
"""
import json
from collections import defaultdict

from pipeline_common import load_unified_json, build_appearances, month_bucket, MONTH_ORDER

RECONCILE_GAP_THRESHOLD_IP = 5.0  # if any team's gap exceeds this, STOP and flag


def build_date_active_roster_lookup(data):
    """
    date (YYYYMMDD) -> {pitcher_name: team_id}, restricted to pitchers whose
    slot was active === True in that date's snapshot. Periods are daily with
    no gaps in observed data, so nearest-prior-date matching covers the
    whole season safely.
    """
    periods = data['periods']
    teams = data['meta']['teams']
    period_by_date = {p['dateYMD']: p for p in periods}
    sorted_dates = sorted(period_by_date.keys())

    def nearest_period_date(date_et):
        if date_et in period_by_date:
            return date_et
        lo, hi = 0, len(sorted_dates) - 1
        best = None
        while lo <= hi:
            mid = (lo + hi) // 2
            if sorted_dates[mid] <= date_et:
                best = sorted_dates[mid]
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    cache = {}

    def roster_map_for_date(date_et):
        pd = nearest_period_date(date_et)
        if pd is None:
            return {}
        if pd in cache:
            return cache[pd]
        p = period_by_date[pd]
        m = {}
        for tid in teams:
            for pl in p['players'].get(tid, {}).get('pitchers', []):
                if pl.get('name') and pl.get('active', False):
                    m[pl['name']] = tid
        cache[pd] = m
        return m

    return roster_map_for_date


def build_heatmap_cells(data, appearances=None):
    """
    Returns {(team_id, month_bucket): {'IP', 'WHIP', 'BABIP', 'n_days', 'BF'}}
    using date-accurate + active-slot-filtered attribution.
    """
    if appearances is None:
        appearances = build_appearances(data)

    roster_map_for_date = build_date_active_roster_lookup(data)

    agg = defaultdict(lambda: {'outs': 0, 'BB': 0, 'H': 0, 'HR': 0, 'K': 0, 'BF': 0, 'days': set()})
    for a in appearances:
        rmap = roster_map_for_date(a['dateET'])
        tid = rmap.get(a['name'])
        if tid is None:
            continue  # not on any team's ACTIVE roster that day -- correctly excluded
        mb = month_bucket(a['dateET'])
        key = (tid, mb)
        agg[key]['outs'] += a['outs']
        agg[key]['BB'] += a['BB']
        agg[key]['H'] += a['H']
        agg[key]['HR'] += a['HR']
        agg[key]['K'] += a['K']
        agg[key]['BF'] += a['BF']
        agg[key]['days'].add(a['dateET'])

    cells = {}
    for (tid, mb), d in agg.items():
        ip = d['outs'] / 3.0
        whip = (d['BB'] + d['H']) / ip if ip > 0 else None
        babip_denom = d['BF'] - d['K'] - d['BB'] - d['HR']
        babip = (d['H'] - d['HR']) / babip_denom if babip_denom > 0 else None
        cells[(tid, mb)] = {'IP': round(ip, 1), 'WHIP': whip, 'BABIP': babip,
                             'n_days': len(d['days']), 'BF': d['BF']}
    return cells


def reconcile(data, cells):
    """
    MANDATORY sanity check. Compares each team's total computed IP (summed
    across all month cells) against that team's own snap.IP from the latest
    period. Returns (gap_table, max_gap, passed).

    gap_table: list of (team_name, computed_ip, espn_ip, gap) sorted by |gap| desc
    """
    teams = data['meta']['teams']
    snap = data['periods'][-1]['snap']

    gap_table = []
    for tid, name in teams.items():
        computed = sum(v['IP'] for (t, m), v in cells.items() if t == tid)
        espn = snap[tid]['IP']
        gap_table.append((name, computed, espn, computed - espn))

    gap_table.sort(key=lambda row: -abs(row[3]))
    max_gap = max(abs(row[3]) for row in gap_table) if gap_table else 0.0
    passed = max_gap <= RECONCILE_GAP_THRESHOLD_IP
    return gap_table, max_gap, passed


def team_standings_order(data):
    teams = data['meta']['teams']
    roto = data['periods'][-1]['roto']
    return sorted(teams.keys(), key=lambda tid: -roto[tid]['total'])


def flag_small_samples(cells, min_ip=15.0):
    """Cells with very small samples that should be flagged in the caption/UI."""
    return [(k, v) for k, v in cells.items() if v['IP'] < min_ip]


def main(json_path):
    data = load_unified_json(json_path)
    appearances = build_appearances(data)
    cells = build_heatmap_cells(data, appearances)

    gap_table, max_gap, passed = reconcile(data, cells)

    print("=== IP RECONCILIATION CHECK (mandatory before presenting heatmap) ===")
    print(f"{'Team':<28}{'Computed':>10}{'ESPN':>10}{'Gap':>8}")
    for name, computed, espn, gap in gap_table:
        print(f"{name:<28}{computed:>10.1f}{espn:>10.1f}{gap:>8.1f}")
    print(f"\nMax abs gap: {max_gap:.1f} IP (threshold: {RECONCILE_GAP_THRESHOLD_IP})")

    if not passed:
        print("\n*** RECONCILIATION FAILED. Do not present this heatmap as final. ***")
        print("*** Investigate before proceeding -- something in the attribution logic is off. ***")
    else:
        print(f"\nReconciled to within {max_gap:.1f} IP across all 12 teams. OK to present.")

    small = flag_small_samples(cells)
    if small:
        print("\nSmall-sample cells to flag in the UI:")
        for k, v in small:
            print(f"  {k}: {v}")

    with open('step4_cells.json', 'w') as f:
        json.dump({f"{tid}|{mb}": v for (tid, mb), v in cells.items()}, f, indent=2)

    return cells, gap_table, max_gap, passed


if __name__ == '__main__':
    import sys
    json_path = sys.argv[1] if len(sys.argv) > 1 else 'pennants_over_easy_unified.json'
    main(json_path)
