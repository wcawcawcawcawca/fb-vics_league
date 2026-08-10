"""
step6_start_score.py
=====================
Composite "Start Score" for streaming decisions: combines pitcher trailing
CMD%/Model WHIP with opponent trailing offensive strength (OPS), fit via
OLS regression against every qualifying start's actual game WHIP this
season. Refit from scratch every pipeline run so it self-updates as the
season progresses -- coefficients are NOT hardcoded.

Methodology (validated 2026-08-10 in chat, see commit message for the
validation run):
- Walk-forward only -- every feature for a given start uses ONLY data
  strictly before that start's date, so there's no lookahead / no
  hindsight leakage into the fit.
- Target: actual game WHIP = (H + BB) / IP for that specific start.
- Pitcher features: CMD% and Model WHIP, trailing 30 days ending the day
  before the start (falls back to season-to-date if the 30-day window has
  zero prior starts; a pitcher's literal first start of the season is
  dropped from the fit -- nothing to predict from). 30 days was chosen
  over the pipeline's original 20-day convention after an explicit
  window-length backtest (10/15/20/25/30/40/60/90/season-to-date all
  tested): R^2 and quintile spread both climb from 10 through 30 days,
  then plateau essentially flat all the way out to a full season. 30 days
  is the shortest window at the top of that plateau -- i.e. the least
  amount of recency traded away for the same predictive power. Below ~20
  days there's too little data per estimate (avg. ~2-3 prior starts);
  above ~30 there's no measurable gain, just staler data diluting recent
  form. This constant is now shared with Steps 2/3/5 via
  pipeline_common.trailing_window_dates() and step2_kondor_staff.build_pool()
  -- all changed together, so "Model WHIP" means the same trailing window
  everywhere in the pipeline's output, not just here.
- Opponent feature: trailing team OPS over the last 15 team games ending
  the day before the start. Trailing runs/game was also tested and
  dropped -- it's ~0.86 correlated with trailing OPS (redundant) and
  individually explains essentially none of the variance in the target.
- Starts with <2 IP are excluded from the FIT only (disaster/injury-
  shortened outings are pure small-sample noise -- e.g. 1 IP, 5 ER --
  and have outsized leverage on a linear fit). They're still scored
  normally wherever this module scores current/live pitchers.

Backtest result at introduction (3,033 fit rows, 20-day window): R^2 = 0.017,
correlation(predicted, actual) = 0.13. Backtest result after the window-
length experiment (same 3,033 fit rows, 30-day window): R^2 = 0.020,
correlation = 0.141, quintile spread (Q5 mean actual WHIP minus Q1) widened
from 0.243 to 0.260. Both are low in absolute terms, and that's expected --
a single MLB start is ~15-25 batters, dominated by randomness no model
can capture. Quintile-bucketed validation showed a clean monotonic
gradient at both window lengths (best-predicted quintile beats worst-
predicted by a real margin), so the model has real, if modest, ability to
separate better matchups from worse ones ON AVERAGE -- it cannot tell you
what any ONE start will do. Re-run quintile_backtest() each season to
confirm this holds as more data accumulates; if it stops separating
cleanly, that's a sign the model needs revisiting, not that streaming
decisions should lean on it harder.

Score (Relative)/Score (Absolute) from Steps 2/3/5 are NOT fed into the
regression as separate inputs -- they're percentile transforms of
CMD%/Model WHIP already in the model, so including them would be
redundant/collinear rather than new signal. They're still carried through
in the output for reference alongside Start Score.

KNOWN LIMITATIONS (real data gaps, not oversights -- do not silently work
around these, flag them):
- No pitcher handedness anywhere in the pipeline, so no vs-LHP/RHP
  opponent splits. Would need a one-time supplementary fetch of team
  rosters (~30 calls) to build a name -> throws lookup, then rebuilding
  opponent batting splits by the handedness of the pitcher they actually
  faced each game.
- No home/away flag captured by the scraper (`teams` is just a 2-element
  list, order not confirmed to mean anything), so no home/away splits.
  The scraper would need a small patch to capture this from ESPN's
  `competitors[].homeAway` field going forward -- can't backfill already-
  scraped historical games without it.
Both are a documented Phase 2, not something this module fakes or skips
silently.
"""
import json
from datetime import datetime, timedelta
from collections import defaultdict

import numpy as np

from pipeline_common import load_unified_json, percentile_rank

MIN_IP_FOR_FIT = 2.0
TRAILING_WINDOW_DAYS = 30
OPP_TRAILING_GAMES = 15
MIN_AVG_IP_GENUINE_STARTER = 4.0


def _parse_int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def _to_date(ymd):
    return datetime.strptime(ymd, '%Y%m%d')


# ---------------------------------------------------------------------------
# Raw extraction
# ---------------------------------------------------------------------------

def extract_starts_and_batting(data):
    """One pass over every finished game: collect (a) each team's
    first-listed pitcher appearance and (b) each team's batting totals for
    that game. Returns (starts, team_game_batting), both lists of dicts,
    ordered by orderedGameIds (true chronological order, doubleheader-safe
    -- see meta.orderedGameIdsNote in the raw JSON)."""
    games = data['games']
    ordered_ids = data['meta']['orderedGameIds']

    starts = []
    team_game_batting = []

    for gid in ordered_ids:
        g = games.get(gid)
        if not g or g.get('gameStatusDiagnostic', {}).get('type') != 'STATUS_FINAL':
            continue
        date = g.get('dateET')
        teams = g.get('teams') or []
        if len(teams) != 2:
            continue
        pitching = g.get('pitching') or {}
        batting = g.get('batting') or {}

        for team in teams:
            opp = teams[1] if teams[0] == team else teams[0]
            pteam = pitching.get(team) or {}
            if not pteam:
                continue
            first_name = next(iter(pteam.keys()), None)
            if not first_name:
                continue
            p = pteam[first_name]
            try:
                ip_raw = float(p.get('IP', '0') or 0)
                whole = int(ip_raw)
                frac = round((ip_raw - whole) * 10)
                ip = whole + frac / 3.0
            except ValueError:
                continue
            if ip <= 0:
                continue
            starts.append({
                'gameId': gid, 'date': date, 'pitcher': first_name, 'team': team, 'opp': opp,
                'IP': ip, 'H': _parse_int(p.get('H')), 'BB': _parse_int(p.get('BB')),
                'K': _parse_int(p.get('K')), 'HR': _parse_int(p.get('HR')),
                'BF': _parse_int(p.get('BF')), 'balls': _parse_int(p.get('balls')),
                'pure': _parse_int(p.get('pure')), 'inplay': _parse_int(p.get('inplay')),
            })

            bteam = batting.get(team) or {}
            tR = tAB = tH = tBB = tHBP = tSF = t1B = t2B = t3B = tHR = 0
            for bstats in bteam.values():
                tR += _parse_int(bstats.get('R'))
                tAB += _parse_int(bstats.get('AB'))
                tH += _parse_int(bstats.get('H'))
                tBB += _parse_int(bstats.get('BB'))
                tHBP += _parse_int(bstats.get('HBP'))
                tSF += _parse_int(bstats.get('SF'))
                t1B += _parse_int(bstats.get('1B'))
                t2B += _parse_int(bstats.get('2B'))
                t3B += _parse_int(bstats.get('3B'))
                tHR += _parse_int(bstats.get('HR'))
            tb = t1B + 2 * t2B + 3 * t3B + 4 * tHR
            team_game_batting.append({
                'gameId': gid, 'date': date, 'team': team,
                'R': tR, 'AB': tAB, 'H': tH, 'BB': tBB, 'HBP': tHBP, 'SF': tSF, 'TB': tb,
            })

    return starts, team_game_batting


def filter_genuine_starters(starts, min_avg_ip=MIN_AVG_IP_GENUINE_STARTER):
    """Same genuine-starter filter as pipeline_common.compute_genuine_starters,
    reimplemented locally since this module works from its own first-listed
    extraction (which also carries opponent info compute_genuine_starters
    doesn't need)."""
    by_pitcher = defaultdict(list)
    for s in starts:
        by_pitcher[s['pitcher']].append(s['IP'])
    genuine = {name for name, ips in by_pitcher.items() if sum(ips) / len(ips) >= min_avg_ip}
    return [s for s in starts if s['pitcher'] in genuine], genuine


# ---------------------------------------------------------------------------
# Walk-forward feature construction
# ---------------------------------------------------------------------------

def pitcher_trailing_stats(by_pitcher_sorted, pitcher, before_date, window_days=TRAILING_WINDOW_DAYS):
    """CMD%/Model WHIP as of the day before before_date, trailing
    window_days, falling back to season-to-date if the window is empty.
    None if there are zero prior appearances at all."""
    window_start = before_date - timedelta(days=window_days)
    prior = [a for a in by_pitcher_sorted[pitcher] if a['_date'] < before_date]
    if not prior:
        return None
    windowed = [a for a in prior if a['_date'] >= window_start]
    pool = windowed if windowed else prior
    balls = sum(a['balls'] for a in pool)
    pure = sum(a['pure'] for a in pool)
    inplay = sum(a['inplay'] for a in pool)
    bf = sum(a['BF'] for a in pool)
    k = sum(a['K'] for a in pool)
    bb = sum(a['BB'] for a in pool)
    hr = sum(a['HR'] for a in pool)
    total_pitches = balls + pure + inplay
    if total_pitches == 0 or bf == 0:
        return None
    purepct = pure / total_pitches
    ballpct = balls / total_pitches
    cmd_pct = (purepct - ballpct) * 100
    kpct, bbpct, hrpct = k / bf, bb / bf, hr / bf
    model_whip = 1.290 - 2.208 * kpct + 4.402 * bbpct + 3.766 * hrpct
    return {'cmd_pct': cmd_pct, 'model_whip': model_whip, 'n_prior_starts': len(pool)}


def opponent_trailing_offense(by_team_sorted, team, before_date, n_games=OPP_TRAILING_GAMES):
    """Trailing OPS and runs/game over the last n_games team games strictly
    before before_date. None if there are zero prior team games."""
    prior = [t for t in by_team_sorted[team] if t['_date'] < before_date]
    if not prior:
        return None
    pool = prior[-n_games:]
    R = sum(t['R'] for t in pool)
    AB = sum(t['AB'] for t in pool)
    H = sum(t['H'] for t in pool)
    BB = sum(t['BB'] for t in pool)
    HBP = sum(t['HBP'] for t in pool)
    SF = sum(t['SF'] for t in pool)
    TB = sum(t['TB'] for t in pool)
    obp_den = AB + BB + HBP + SF
    if obp_den == 0 or AB == 0:
        return None
    obp = (H + BB + HBP) / obp_den
    slg = TB / AB
    return {'opp_trailing_ops': obp + slg, 'opp_trailing_rpg': R / len(pool), 'n_prior_games': len(pool)}


def build_training_rows(data):
    """Full walk-forward dataset: one row per qualifying start with its
    actual result plus trailing features as of the day before. Used both
    to fit the regression and for the quintile backtest."""
    starts, team_game_batting = extract_starts_and_batting(data)
    qualifying, genuine_starters = filter_genuine_starters(starts)

    for s in qualifying:
        s['_date'] = _to_date(s['date'])
    qualifying.sort(key=lambda s: (s['_date'], s['gameId']))

    for t in team_game_batting:
        t['_date'] = _to_date(t['date'])
    team_game_batting.sort(key=lambda t: (t['_date'], t['gameId']))

    by_pitcher = defaultdict(list)
    for s in qualifying:
        by_pitcher[s['pitcher']].append(s)
    by_team = defaultdict(list)
    for t in team_game_batting:
        by_team[t['team']].append(t)

    rows = []
    for s in qualifying:
        pf = pitcher_trailing_stats(by_pitcher, s['pitcher'], s['_date'])
        if pf is None:
            continue
        of = opponent_trailing_offense(by_team, s['opp'], s['_date'])
        if of is None:
            continue
        actual_whip = (s['H'] + s['BB']) / s['IP']
        rows.append({
            'gameId': s['gameId'], 'date': s['date'], 'pitcher': s['pitcher'],
            'team': s['team'], 'opp': s['opp'], 'IP': s['IP'],
            'cmd_pct': pf['cmd_pct'], 'model_whip': pf['model_whip'],
            'n_prior_starts': pf['n_prior_starts'],
            'opp_trailing_ops': of['opp_trailing_ops'],
            'opp_trailing_rpg': of['opp_trailing_rpg'],
            'actual_whip': actual_whip,
        })
    return rows, by_pitcher, by_team, genuine_starters


# ---------------------------------------------------------------------------
# Model fit + backtest
# ---------------------------------------------------------------------------

def fit_start_score_model(rows, min_ip=MIN_IP_FOR_FIT):
    """OLS: actual_whip ~ cmd_pct + model_whip + opp_trailing_ops, fit on
    rows with IP >= min_ip. Returns (coefs_dict, diagnostics_dict)."""
    fit_rows = [r for r in rows if r['IP'] >= min_ip]
    n = len(fit_rows)
    X = np.column_stack([
        np.ones(n),
        [r['cmd_pct'] for r in fit_rows],
        [r['model_whip'] for r in fit_rows],
        [r['opp_trailing_ops'] for r in fit_rows],
    ])
    y = np.array([r['actual_whip'] for r in fit_rows])

    coefs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    y_pred = X @ coefs
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    corr = float(np.corrcoef(y_pred, y)[0, 1]) if n > 1 else 0.0

    coefs_dict = {
        'const': float(coefs[0]), 'cmd_pct': float(coefs[1]),
        'model_whip': float(coefs[2]), 'opp_trailing_ops': float(coefs[3]),
    }
    diagnostics = {
        'n_fit_rows': n, 'n_total_rows': len(rows), 'r_squared': r_squared,
        'correlation': corr, 'min_ip_for_fit': min_ip,
    }
    return coefs_dict, diagnostics


def predict_whip(coefs, cmd_pct, model_whip, opp_trailing_ops):
    return (coefs['const'] + coefs['cmd_pct'] * cmd_pct
            + coefs['model_whip'] * model_whip
            + coefs['opp_trailing_ops'] * opp_trailing_ops)


# ---------------------------------------------------------------------------
# Real-matchup scoring (for Step 5 probables and Step 3's "next start" column)
# ---------------------------------------------------------------------------

# ESPN's boxscore team abbreviations (what by_team is keyed on) sometimes
# differ from the 3-letter codes used by FanGraphs/RotoWire probables grids
# or typed in by hand. Map common variants to the ESPN form here rather
# than in every caller.
TEAM_ABBR_ALIASES = {
    'SFG': 'SF', 'TBR': 'TB', 'KCR': 'KC', 'WSN': 'WSH', 'SDP': 'SD',
    'CWS': 'CHW', 'OAK': 'ATH', 'AZ': 'ARI',
}


def normalize_team_abbr(abbr):
    abbr = (abbr or '').strip().upper()
    return TEAM_ABBR_ALIASES.get(abbr, abbr)


def build_team_offense_index(data):
    """Public helper so Step 5/Step 3 can look up a specific opponent's
    trailing offense without reaching into this module's private
    extraction pipeline. Returns (by_team, max_date) where by_team is
    {team_abbr: [game_row, ...]} sorted chronologically and max_date is
    the latest dateET present in the data (a datetime)."""
    _, team_game_batting = extract_starts_and_batting(data)
    for t in team_game_batting:
        t['_date'] = _to_date(t['date'])
    team_game_batting.sort(key=lambda t: (t['_date'], t['gameId']))
    by_team = defaultdict(list)
    for t in team_game_batting:
        by_team[t['team']].append(t)
    max_date = _to_date(max(t['date'] for t in team_game_batting))
    return by_team, max_date


def matchup_start_score(coefs, cmd_pct, model_whip, opp_abbr, by_team, as_of_date=None):
    """
    Predicted WHIP + Start Score for a SPECIFIC upcoming opponent, instead
    of the neutral league-average placeholder. as_of_date defaults to "use
    every game in by_team" (i.e. the day after the latest date present) --
    pass an explicit datetime if scoring a start further in the future
    where you want the trailing window anchored to today rather than to
    whatever the last scraped date happens to be (in practice these are
    usually within days of each other so it rarely matters).

    Returns None if the opponent abbreviation doesn't resolve to any team
    with trailing data (bad/unrecognized abbreviation, or a team with zero
    games yet) -- callers should show a dash rather than a fabricated
    neutral score in that case.
    """
    abbr = normalize_team_abbr(opp_abbr)
    if abbr not in by_team:
        return None
    if as_of_date is None:
        as_of_date = max(t['_date'] for t in by_team[abbr]) + timedelta(days=1)
    of = opponent_trailing_offense(by_team, abbr, as_of_date)
    if of is None:
        return None
    predicted_whip = predict_whip(coefs, cmd_pct, model_whip, of['opp_trailing_ops'])
    return {
        'predicted_whip': predicted_whip,
        'opp_trailing_ops': of['opp_trailing_ops'],
        'opp_abbr_resolved': abbr,
    }


def quintile_backtest(rows, coefs, min_ip=MIN_IP_FOR_FIT):
    """Bucket fit-eligible rows into quintiles by predicted WHIP and report
    mean/median actual WHIP per bucket -- the honest way to validate this
    given how low R^2 is for any single start (see module docstring)."""
    fit_rows = [dict(r) for r in rows if r['IP'] >= min_ip]
    for r in fit_rows:
        r['predicted_whip'] = predict_whip(coefs, r['cmd_pct'], r['model_whip'], r['opp_trailing_ops'])
    fit_rows.sort(key=lambda r: r['predicted_whip'])
    n = len(fit_rows)
    quintile_size = n // 5
    labels = ['Q1 (best predicted)', 'Q2', 'Q3', 'Q4', 'Q5 (worst predicted)']
    summary = []
    for i, label in enumerate(labels):
        start = i * quintile_size
        end = (i + 1) * quintile_size if i < 4 else n
        bucket = fit_rows[start:end]
        actuals = sorted(r['actual_whip'] for r in bucket)
        summary.append({
            'quintile': label, 'n': len(bucket),
            'mean_predicted': sum(r['predicted_whip'] for r in bucket) / len(bucket),
            'mean_actual': sum(r['actual_whip'] for r in bucket) / len(bucket),
            'median_actual': actuals[len(actuals) // 2],
        })
    return summary


# ---------------------------------------------------------------------------
# Live scoring for current pitchers (Kondor + FA pool)
# ---------------------------------------------------------------------------

def score_current_pitchers(data, roster, pool, fa_pool, coefs, kondor_team_id='2'):
    """
    Start Score for Kondor's qualifying pitchers + the FA pool, using each
    pitcher's CURRENT trailing CMD%/Model WHIP (already computed in
    `pool`/`fa_pool` by Steps 2/3).

    Without a probables grid, there's no real opponent to plug in for a
    future start, so this scores every pitcher against a NEUTRAL opponent
    (league-average trailing OPS as of the latest date in the data) --
    this still differentiates pitchers cleanly on their own skill, it just
    can't reflect "who they actually face this week." When Step 5's real
    matchups are available, combine this formula with the actual
    opponent's trailing OPS instead (predict_whip() takes that as a
    parameter for exactly this purpose) rather than relying on the neutral
    version.
    """
    starts, team_game_batting = extract_starts_and_batting(data)
    for t in team_game_batting:
        t['_date'] = _to_date(t['date'])
    team_game_batting.sort(key=lambda t: (t['_date'], t['gameId']))
    by_team = defaultdict(list)
    for t in team_game_batting:
        by_team[t['team']].append(t)

    max_date = _to_date(max(t['date'] for t in team_game_batting))
    opp_stats = []
    for team in by_team:
        of = opponent_trailing_offense(by_team, team, max_date + timedelta(days=1))
        if of:
            opp_stats.append(of['opp_trailing_ops'])
    league_avg_ops = sum(opp_stats) / len(opp_stats) if opp_stats else 0.72

    combined = dict(fa_pool)
    kondor_names = [pl['name'] for pl in roster[kondor_team_id]['pitchers']]
    for n in kondor_names:
        if n in pool:
            combined[n] = pool[n]

    scored = {}
    for name, d in combined.items():
        cmd_pct = d['CMD'] * 100
        model_whip = d['ModelWHIP']
        predicted_whip = predict_whip(coefs, cmd_pct, model_whip, league_avg_ops)
        scored[name] = {
            'cmd_pct': cmd_pct, 'model_whip': model_whip,
            'score_relative': d.get('ScoreRelative'), 'score_absolute': d.get('ScoreAbsolute'),
            'predicted_whip_neutral_opp': predicted_whip,
            'is_kondor': name in kondor_names,
        }

    vals = [d['predicted_whip_neutral_opp'] for d in scored.values()]
    for name, d in scored.items():
        d['start_score'] = percentile_rank(d['predicted_whip_neutral_opp'], vals, higher_is_better=False)

    return scored, league_avg_ops


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def main(json_path, roster_path='current_roster.json'):
    from step2_kondor_staff import build_pool, score_pool, kondor_staff_table
    from step3_fa_leaderboard import build_fa_pool

    data = load_unified_json(json_path)
    with open(roster_path) as f:
        roster = json.load(f)

    print("Building walk-forward training rows (full-season pass)...")
    rows, by_pitcher, by_team, genuine_starters = build_training_rows(data)
    print(f"  {len(rows)} usable rows after walk-forward feature construction")

    coefs, diagnostics = fit_start_score_model(rows)
    print(f"  Fit on {diagnostics['n_fit_rows']} rows (IP>={diagnostics['min_ip_for_fit']}): "
          f"R^2={diagnostics['r_squared']:.4f}, corr={diagnostics['correlation']:.4f}")

    backtest = quintile_backtest(rows, coefs)
    for b in backtest:
        print(f"  {b['quintile']:22s} n={b['n']:4d}  "
              f"pred={b['mean_predicted']:.3f}  actual={b['mean_actual']:.3f}  "
              f"median_actual={b['median_actual']:.3f}")

    pool, _, _, _, _ = build_pool(data, roster)
    pool, league_pool = score_pool(pool)
    fa_pool = build_fa_pool(pool)
    # kondor_staff_table() is what actually sets ScoreRelative (Kondor-only
    # pool) on the pitchers in `pool` -- score_pool() only sets
    # ScoreAbsolute (league-wide). Call it here purely for that side effect
    # so score_current_pitchers() below can carry ScoreRelative through for
    # Kondor's own pitchers, same as it already does for the FA pool.
    kondor_staff_table(pool, roster)

    scored, league_avg_ops = score_current_pitchers(data, roster, pool, fa_pool, coefs)

    output = {
        'coefficients': coefs,
        'fit_diagnostics': diagnostics,
        'quintile_backtest': backtest,
        'league_avg_trailing_ops': league_avg_ops,
        'current_scores': scored,
    }
    with open('step6_start_score.json', 'w') as f:
        json.dump(output, f, indent=2)

    return output


if __name__ == '__main__':
    import sys
    json_path = sys.argv[1] if len(sys.argv) > 1 else 'pennants_over_easy_unified.json'
    main(json_path)
