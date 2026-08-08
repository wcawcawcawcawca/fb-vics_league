"""
step2_kondor_staff.py
======================
Kondor pitching staff table: trailing 20-day, STARTS-ONLY analysis.

Locked columns (do not add/remove/reorder without explicit user request):
  Pitcher, Starts, IP, CMD%, Model WHIP, Actual WHIP, BABIP,
  Score (Relative), Score (Absolute), Abs. Rank
Sorted by Model WHIP, best to worst. NO stoplight shading on this table --
plain/uncolored only (that's what makes it different from Step 3 & 5).

Score (Relative): min(CMD% percentile, Model WHIP percentile) within Kondor's
                   OWN qualifying staff (teammates only).
Score (Absolute): same min-of-two-percentiles formula, but against the
                   league-wide qualifying pool (all qualifying rostered
                   pitchers across all 12 teams + FAs, 2+ starts & 5+ IP).
Abs. Rank: literal rank position within that league-wide pool, shown as
           "N of POOL_SIZE".

Pitchers with no qualifying trailing-20-day data show dashes and are listed
separately with the reason (never appeared, hasn't started recently, doesn't
clear the season-wide genuine-starter IP threshold, etc.) -- don't just drop
them silently.
"""
import json

from pipeline_common import (
    load_unified_json, build_appearances, compute_genuine_starters,
    aggregate_appearances, trailing_window_dates, percentile_rank,
)


LEAGUE_MIN_STARTS = 2
LEAGUE_MIN_IP = 5.0


def build_pool(data, roster, window_days=20):
    """
    Build the trailing-N-day starts-only aggregate for every pitcher who
    qualifies (genuine starter, >=1 start in window), tagged with their
    current roster team (or None for free agents).
    """
    appearances = build_appearances(data)
    genuine_starters = compute_genuine_starters(appearances)
    window_start, max_date = trailing_window_dates(appearances, window_days)

    name_to_team = {}
    for tid, r in roster.items():
        for pl in r.get('pitchers', []):
            name_to_team[pl['name']] = tid

    from collections import defaultdict
    starts_by_name = defaultdict(list)
    for a in appearances:
        if not a['first_listed']:
            continue
        if a['name'] not in genuine_starters:
            continue
        if not (window_start <= a['dateET'] <= max_date):
            continue
        starts_by_name[a['name']].append(a)

    pool = {}
    for name, recs in starts_by_name.items():
        agg = aggregate_appearances(recs)
        team_id = name_to_team.get(name)
        agg['team_id'] = team_id
        agg['name'] = name
        pool[name] = agg

    return pool, window_start, max_date, appearances, genuine_starters


def score_pool(pool):
    """Attach Score (Absolute) and Abs. Rank (league-wide pool) to every
    pitcher in `pool` who qualifies for the league-wide pool."""
    league_pool = {n: p for n, p in pool.items()
                    if p['Starts'] >= LEAGUE_MIN_STARTS and p['IP'] >= LEAGUE_MIN_IP}

    abs_cmd_vals = [p['CMD'] for p in league_pool.values()]
    abs_whip_vals = [p['ModelWHIP'] for p in league_pool.values()]

    for name, data in pool.items():
        if name in league_pool:
            cmd_pct = percentile_rank(data['CMD'], abs_cmd_vals, higher_is_better=True)
            whip_pct = percentile_rank(data['ModelWHIP'], abs_whip_vals, higher_is_better=False)
            data['ScoreAbsolute'] = min(cmd_pct, whip_pct)
        else:
            data['ScoreAbsolute'] = None

    ranked = sorted(league_pool.keys(), key=lambda n: -pool[n]['ScoreAbsolute'])
    pool_size = len(league_pool)
    for i, name in enumerate(ranked):
        pool[name]['AbsRank'] = i + 1
        pool[name]['AbsRankStr'] = f"{i + 1} of {pool_size}"
    for name, data in pool.items():
        data.setdefault('AbsRank', None)
        data.setdefault('AbsRankStr', None)

    return pool, league_pool


def kondor_staff_table(pool, roster, kondor_team_id='2'):
    """
    Returns (rows, no_data_names_with_reason) for the Kondor staff table.
    rows: list of dicts sorted by Model WHIP ascending, with ScoreRelative
          computed within Kondor's own qualifying staff.
    """
    kondor_names = [pl['name'] for pl in roster[kondor_team_id]['pitchers']]
    kondor_pool = {n: pool[n] for n in kondor_names if n in pool}

    cmd_vals = [p['CMD'] for p in kondor_pool.values()]
    whip_vals = [p['ModelWHIP'] for p in kondor_pool.values()]
    for name, d in kondor_pool.items():
        cmd_pct = percentile_rank(d['CMD'], cmd_vals, higher_is_better=True)
        whip_pct = percentile_rank(d['ModelWHIP'], whip_vals, higher_is_better=False)
        d['ScoreRelative'] = min(cmd_pct, whip_pct)

    rows = sorted(kondor_pool.values(), key=lambda d: d['ModelWHIP'])

    no_data = [n for n in kondor_names if n not in pool]
    return rows, no_data


def diagnose_no_data_reason(name, appearances, genuine_starters, window_start, max_date):
    """Human-readable reason a pitcher has no qualifying trailing-window data."""
    if name not in genuine_starters:
        any_recent = [a for a in appearances if a['name'] == name and window_start <= a['dateET'] <= max_date]
        if any_recent:
            return "has appearances in the window but doesn't clear the season-wide genuine-starter IP threshold"
        return "no appearances found this season (not yet up / not rostered in MLB)"
    last = max((a['dateET'] for a in appearances if a['name'] == name), default=None)
    if last is None:
        return "no appearances found this season"
    return f"genuine starter, but last appeared {last} (outside the trailing window -- likely injured/inactive)"


def main(json_path, roster_path='current_roster.json'):
    data = load_unified_json(json_path)
    with open(roster_path) as f:
        roster = json.load(f)

    pool, window_start, max_date, appearances, genuine_starters = build_pool(data, roster)
    pool, league_pool = score_pool(pool)
    rows, no_data = kondor_staff_table(pool, roster)

    print(f"Trailing 20-day window: {window_start} to {max_date}")
    print(f"League-wide qualifying pool size: {len(league_pool)}")
    print("\nKondor staff, sorted by Model WHIP:")
    for d in rows:
        print(f"  {d['name']}: Starts={d['Starts']} IP={d['IP']} CMD%={d['CMD']*100:.1f} "
              f"ModelWHIP={d['ModelWHIP']:.3f} ActualWHIP={d['ActualWHIP']:.3f} "
              f"BABIP={d['BABIP']:.3f} ScoreRel={d['ScoreRelative']:.2f} "
              f"ScoreAbs={d['ScoreAbsolute']:.2f} AbsRank={d['AbsRankStr']}")

    print("\nNo qualifying data:")
    for n in no_data:
        reason = diagnose_no_data_reason(n, appearances, genuine_starters, window_start, max_date)
        print(f"  {n}: {reason}")

    with open('step2_pool.json', 'w') as f:
        json.dump(pool, f, indent=2)

    return rows, no_data, pool


if __name__ == '__main__':
    import sys
    json_path = sys.argv[1] if len(sys.argv) > 1 else 'pennants_over_easy_unified.json'
    main(json_path)
