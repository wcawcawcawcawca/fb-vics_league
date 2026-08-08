"""
step5_probables.py
====================
7-day probable starters table. Source: FanGraphs RosterResource Probables
Grid. Live fetch sometimes works, sometimes gets blocked by bot detection --
if it's blocked, ASK THE USER TO PASTE THE GRID rather than presenting
stale/cached data as if it were current.

Covers (a) Kondor's current rostered pitchers and (b) the qualifying FA pool
from Step 3 -- nothing else.

Locked columns: Pitcher, Matchup, CMD%, Model WHIP, Score (Relative),
Score (Absolute), Abs. Rank.

Score (Relative) pool = qualifying FAs UNION Kondor's own qualifying
rostered pitchers (NOT the FA-only pool -- this is different from Step 3).
Score (Absolute) / Abs. Rank reuse the league-wide pool from Steps 2-3.

Grouped by date, header row per date section. THIS IS THE ONLY TABLE THAT
GETS FULL-ROW STOPLIGHT SHADING (Steps 2 and 3 shade differently -- don't
homogenize the formats). Within each date: sort by tier (green -> yellow ->
red -> no-data), then Score (Relative) descending within tier.

Kondor pitchers get a star marker after their name and are integrated into
the same unified ranking/shading as everyone else (not a separate section).
Kondor pitchers with no qualifying trailing-20-day data show dashes and sort
to the bottom of their date group.

Do not annotate pitchers who start twice within the 7-day window -- they
just appear once in each date's section, unmarked.

If the grid doesn't cover the full 7 days, say so explicitly. Never fabricate
missing days.
"""
import json

from pipeline_common import load_unified_json, percentile_rank
from step2_kondor_staff import build_pool, score_pool
from step3_fa_leaderboard import build_fa_pool

TIER_ORDER = {'green': 0, 'yellow': 1, 'red': 2, 'nodata': 3}


def build_combined_pool(pool, fa_pool, roster, kondor_team_id='2'):
    """
    Combined pool for Score (Relative) in Step 5 = qualifying FAs UNION
    Kondor's own qualifying rostered pitchers.
    """
    kondor_names = [pl['name'] for pl in roster[kondor_team_id]['pitchers']]
    kondor_qualifying = {n: pool[n] for n in kondor_names if n in pool}

    combined = dict(fa_pool)
    combined.update(kondor_qualifying)

    cmd_vals = [p['CMD'] for p in combined.values()]
    whip_vals = [p['ModelWHIP'] for p in combined.values()]

    scored = {}
    for name, d in combined.items():
        cmd_pct = percentile_rank(d['CMD'], cmd_vals, higher_is_better=True)
        whip_pct = percentile_rank(d['ModelWHIP'], whip_vals, higher_is_better=False)
        scored[name] = {
            'CMD': d['CMD'], 'ModelWHIP': d['ModelWHIP'],
            'ScoreRelative': min(cmd_pct, whip_pct),
            'ScoreAbsolute': d.get('ScoreAbsolute'),
            'AbsRankStr': d.get('AbsRankStr'),
            'is_kondor': name in kondor_names,
        }

    ranked = sorted(scored.items(), key=lambda kv: -kv[1]['ScoreRelative'])
    n = len(ranked)
    for i, (name, d) in enumerate(ranked):
        frac = i / n
        d['tier'] = 'green' if frac < 1 / 3 else ('yellow' if frac < 2 / 3 else 'red')

    return scored


def parse_probables_grid(raw_text):
    """
    STUB -- fill in per-run. The FanGraphs grid layout varies enough (team
    groupings, accented names, column order) that this is best done as a
    guided manual transcription each run rather than a brittle regex parser.
    Normalize accents (Ureña, Márquez, Pérez, López, etc.) when matching
    against pool names.

    Expected output format:
        {pitcher_name: [(date_label, date_sort_YYYYMMDD, matchup, hand), ...]}
    """
    raise NotImplementedError(
        "Paste/transcribe the FanGraphs grid manually into this structure each run -- "
        "see the docstring for the expected format."
    )


def build_by_date_rows(probables, scored, roster, no_data_kondor_names, kondor_team_id='2'):
    """
    probables: {name: [(date_label, date_sort, matchup, hand), ...]}
    scored: output of build_combined_pool()
    Returns {(date_sort, date_label): [row, ...]} sorted within each date by
    tier then Score (Relative) descending.
    """
    from collections import defaultdict

    kondor_names = set(pl['name'] for pl in roster[kondor_team_id]['pitchers'])
    by_date = defaultdict(list)

    for name, starts in probables.items():
        is_kondor = name in kondor_names
        d = scored.get(name)
        for date_label, date_sort, matchup, hand in starts:
            if d is None:
                row = {'name': name, 'matchup': matchup, 'hand': hand, 'is_kondor': is_kondor,
                       'CMD': None, 'ModelWHIP': None, 'ScoreRelative': None,
                       'ScoreAbsolute': None, 'AbsRankStr': None, 'tier': 'nodata'}
            else:
                row = {'name': name, 'matchup': matchup, 'hand': hand, 'is_kondor': is_kondor,
                       'CMD': d['CMD'], 'ModelWHIP': d['ModelWHIP'],
                       'ScoreRelative': d['ScoreRelative'], 'ScoreAbsolute': d['ScoreAbsolute'],
                       'AbsRankStr': d['AbsRankStr'], 'tier': d['tier']}
            by_date[(date_sort, date_label)].append(row)

    for key in by_date:
        by_date[key].sort(key=lambda r: (TIER_ORDER[r['tier']], -(r['ScoreRelative'] or -1)))

    return dict(by_date)


def main(json_path, roster_path='current_roster.json', probables=None):
    """
    `probables` must be supplied by the caller (see parse_probables_grid
    docstring) -- this step cannot run unattended without the grid data.
    """
    if probables is None:
        raise ValueError(
            "Step 5 requires the FanGraphs probables grid data. Fetch it live, or if "
            "blocked, ask the user to paste it -- then build the `probables` dict per "
            "the format documented in parse_probables_grid() and pass it in."
        )

    data = load_unified_json(json_path)
    with open(roster_path) as f:
        roster = json.load(f)

    pool, window_start, max_date, appearances, genuine_starters = build_pool(data, roster)
    pool, league_pool = score_pool(pool)
    fa_pool = build_fa_pool(pool)
    scored = build_combined_pool(pool, fa_pool, roster)

    kondor_names = [pl['name'] for pl in roster['2']['pitchers']]
    no_data_kondor = [n for n in kondor_names if n not in pool]

    by_date = build_by_date_rows(probables, scored, roster, no_data_kondor)

    for key in sorted(by_date.keys(), key=lambda k: k[0]):
        print(key[1])
        for r in by_date[key]:
            star = ' *' if r['is_kondor'] else ''
            print(f"   {r['name']}{star} {r['matchup']} {r['tier']} {r['ScoreRelative']}")

    with open('step5_by_date.json', 'w') as f:
        json.dump({f"{k[0]}|{k[1]}": v for k, v in by_date.items()}, f, indent=2)

    return by_date


if __name__ == '__main__':
    print(__doc__)
    print("Run this via a driver script that supplies the `probables` dict -- "
          "it cannot run standalone without the FanGraphs grid data.")
