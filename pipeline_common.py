"""
pipeline_common.py
===================
Shared utilities for the "Pennants Over Easy" (league 137080) analytics pipeline.
Every step (step1-step5) imports from this module. Load the unified JSON once
here so all steps see consistent data.

Locked conventions (do not change without updating this file's docstrings AND
re-confirming with the user -- these are cross-checked against ESPN's own
numbers and getting them wrong silently breaks every downstream table):

- Pure%/Ball% denominator: PURE% and BALL% are each that pitch type's share of
  TOTAL PITCHES THROWN (balls + pure + inplay), never batters faced (BF).
  CMD% = Pure% - Ball%.
- K%/BB%/HR% denominator: these ARE correctly denominated by BF. Separate and
  correct usage from Pure%/Ball%.
- Model WHIP = 1.290 - 2.208*K% + 4.402*BB% + 3.766*HR%
  (cross-validated regression, CV R^2 = 0.58 across 172 qualifying MLB starters)
- BABIP approximation = (H - HR) / (BF - K - BB - HR)
  (HBP/SF aren't broken out in the source gamelogs, so they're not excluded)
- Genuine-starter filter: first-listed for their team in a game AND a
  season-wide average IP >= 4.0 across all first-listed appearances. This
  applies to Steps 2, 3, and ad hoc individual-pitcher lookups. It does NOT
  apply to Step 4 (whole-staff, including relief innings).
- Month bucketing: March and April are ALWAYS combined into "Mar-Apr".
- IP notation: baseball fractional (e.g. "5.1" = 5 and 1/3 innings, "5.2" =
  5 and 2/3 innings). Convert via whole + frac/3, NEVER treat the decimal
  literally.
"""
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_unified_json(path):
    """Load the unified scraper JSON. Returns the raw dict."""
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# IP conversion
# ---------------------------------------------------------------------------

def ip_to_outs(ip_str):
    """Convert baseball-notation IP string (e.g. '6.0', '5.1', '5.2') to outs."""
    ip = float(ip_str)
    whole = int(ip)
    frac = round((ip - whole) * 10)  # .1 -> 1 out, .2 -> 2 outs
    return whole * 3 + frac


def outs_to_ip_float(outs):
    """Convert outs back to a decimal IP figure (NOT baseball notation) for math."""
    return outs / 3.0


# ---------------------------------------------------------------------------
# Pitcher appearances
# ---------------------------------------------------------------------------

def build_appearances(data):
    """
    Flatten every pitcher's every game into one row per (pitcher, game).

    Each row includes 'first_listed' (True if this pitcher was the first key
    in their team's pitching dict for that game -- i.e. a start), and all raw
    box-score counting stats plus pitch-type counts.

    Returns a list of dicts.
    """
    games = data['games']
    ordered_game_ids = data['meta']['orderedGameIds']

    appearances = []
    for gid in ordered_game_ids:
        g = games.get(gid)
        if not g:
            continue
        date_et = g.get('dateET')
        pitching = g.get('pitching', {})
        for team_abbr, pitchers in pitching.items():
            names = list(pitchers.keys())  # dict preserves insertion order
            for idx, name in enumerate(names):
                rec = pitchers[name]
                try:
                    ip = float(rec.get('IP', '0') or 0)
                except ValueError:
                    ip = 0.0
                appearances.append({
                    'gameId': gid,
                    'dateET': date_et,
                    'team': team_abbr,
                    'name': name,
                    'first_listed': (idx == 0),
                    'IP': ip,
                    'outs': ip_to_outs(rec.get('IP', '0') or '0'),
                    'ER': int(rec.get('ER', 0) or 0),
                    'BB': int(rec.get('BB', 0) or 0),
                    'K': int(rec.get('K', 0) or 0),
                    'HR': int(rec.get('HR', 0) or 0),
                    'H': int(rec.get('H', 0) or 0),
                    'BF': int(rec.get('BF', 0) or 0),
                    'balls': int(rec.get('balls', 0) or 0),
                    'pure': int(rec.get('pure', 0) or 0),
                    'inplay': int(rec.get('inplay', 0) or 0),
                })
    return appearances


def compute_genuine_starters(appearances, min_avg_ip=4.0):
    """
    Genuine-starter filter: first-listed for their team AND a season-wide
    average IP >= min_avg_ip across all first-listed appearances.

    Returns a set of pitcher names.
    """
    first_listed_by_name = defaultdict(list)
    for a in appearances:
        if a['first_listed']:
            first_listed_by_name[a['name']].append(a['IP'])

    genuine = set()
    for name, ips in first_listed_by_name.items():
        if (sum(ips) / len(ips)) >= min_avg_ip:
            genuine.add(name)
    return genuine


# ---------------------------------------------------------------------------
# Aggregation math (used by Steps 2, 3, 5)
# ---------------------------------------------------------------------------

def aggregate_appearances(recs):
    """
    Aggregate a list of appearance dicts (same pitcher, multiple games) into
    the derived-stat dict used throughout Steps 2/3/5.
    """
    outs = sum(r['outs'] for r in recs)
    ip = outs / 3.0
    ER = sum(r['ER'] for r in recs)
    BB = sum(r['BB'] for r in recs)
    K = sum(r['K'] for r in recs)
    HR = sum(r['HR'] for r in recs)
    H = sum(r['H'] for r in recs)
    BF = sum(r['BF'] for r in recs)
    balls = sum(r['balls'] for r in recs)
    pure = sum(r['pure'] for r in recs)
    inplay = sum(r['inplay'] for r in recs)
    total_pitches = balls + pure + inplay
    starts = len(recs)

    Kpct = K / BF if BF else 0
    BBpct = BB / BF if BF else 0
    HRpct = HR / BF if BF else 0
    Purepct = pure / total_pitches if total_pitches else 0
    Ballpct = balls / total_pitches if total_pitches else 0
    CMD = Purepct - Ballpct
    ModelWHIP = 1.290 - 2.208 * Kpct + 4.402 * BBpct + 3.766 * HRpct
    ActualWHIP = (BB + H) / ip if ip else None
    babip_denom = BF - K - BB - HR
    BABIP = (H - HR) / babip_denom if babip_denom > 0 else None

    return {
        'Starts': starts, 'IP': round(ip, 1), 'ER': ER, 'BB': BB, 'K': K,
        'HR': HR, 'H': H, 'BF': BF, 'balls': balls, 'pure': pure,
        'inplay': inplay, 'total_pitches': total_pitches,
        'Kpct': Kpct, 'BBpct': BBpct, 'HRpct': HRpct,
        'Purepct': Purepct, 'Ballpct': Ballpct, 'CMD': CMD,
        'ModelWHIP': ModelWHIP, 'ActualWHIP': ActualWHIP, 'BABIP': BABIP,
    }


def trailing_window_dates(appearances, window_days=20):
    """Return (window_start_ymd, max_date_ymd) for the trailing N-day window,
    anchored on the most recent dateET present in the appearances list."""
    max_date = max(a['dateET'] for a in appearances)
    max_dt = datetime.strptime(max_date, '%Y%m%d')
    window_start_dt = max_dt - timedelta(days=window_days - 1)  # inclusive
    return window_start_dt.strftime('%Y%m%d'), max_date


def percentile_rank(value, values, higher_is_better=True):
    """
    Percentile rank in [0, 1] where 1.0 = best in the pool.
    Ties share the same (non-strict) rank.
    """
    n = len(values)
    if n <= 1:
        return 1.0
    if higher_is_better:
        better_or_eq = sum(1 for v in values if v <= value)
    else:
        better_or_eq = sum(1 for v in values if v >= value)
    return (better_or_eq - 1) / (n - 1)


def month_bucket(date_et):
    """YYYYMMDD -> month label, with March+April always combined into 'Mar-Apr'."""
    mm = date_et[4:6]
    names = {'01': 'Jan', '02': 'Feb', '03': 'Mar', '04': 'Apr', '05': 'May',
             '06': 'Jun', '07': 'Jul', '08': 'Aug', '09': 'Sep', '10': 'Oct',
             '11': 'Nov', '12': 'Dec'}
    if mm in ('03', '04'):
        return 'Mar-Apr'
    return names[mm]


MONTH_ORDER = ['Mar-Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct']
