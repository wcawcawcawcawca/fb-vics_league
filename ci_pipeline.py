"""
ci_pipeline.py
===============
CI entry point for GitHub Actions. Thin wrapper around run_pipeline.run()
that turns a failed Step 4 IP reconciliation into a non-zero exit code, so
the workflow shows a red X instead of silently committing bad numbers.

Also writes ONE combined summary file (latest_summary.json) at a FIXED path,
so a chat session only ever needs one raw GitHub URL -- given once -- to pull
the latest results, instead of hunting down several separate output files'
URLs by hand every single run. The path never changes; only the content does
on each run, which is exactly what makes it reusable across conversations.

This intentionally does NOT modify run_pipeline.py -- it just calls the
existing `run()` function and inspects/reshapes its return value.
"""
import json
import sys
from datetime import datetime, timezone

from run_pipeline import run
from step4_heatmap import team_standings_order

DATA_PATH = 'data/pennants_over_easy_unified.json'
SUMMARY_PATH = 'latest_summary.json'


def build_summary(result):
    gap_table, max_gap, passed = result['heatmap_reconciliation']

    step2_rows = [
        {
            'name': d['name'], 'starts': d['Starts'], 'ip': d['IP'],
            'cmd_pct': round(d['CMD'] * 100, 1), 'model_whip': round(d['ModelWHIP'], 3),
            'actual_whip': round(d['ActualWHIP'], 3) if d['ActualWHIP'] is not None else None,
            'babip': round(d['BABIP'], 3) if d['BABIP'] is not None else None,
            'score_relative': round(d['ScoreRelative'], 2),
            'score_absolute': round(d['ScoreAbsolute'], 2) if d['ScoreAbsolute'] is not None else None,
            'abs_rank': d['AbsRankStr'],
        }
        for d in result['step2_rows']
    ]

    heatmap_cells = {
        f"{k[0]}|{k[1]}": {'ip': v['IP'], 'whip': round(v['WHIP'], 3) if v['WHIP'] is not None else None,
            'babip': round(v['BABIP'], 3) if v['BABIP'] is not None else None,
            'n_days': v['n_days']}
        for k, v in result['heatmap_cells'].items()
    }

    data = result['data']
    teams = data['meta']['teams']  # {team_id: team_name}, static within a season
    standings_order = team_standings_order(data)  # team_ids sorted by current roto total, best first
    roto = data['periods'][-1]['roto']

    fa_pool_rows = [
        {
            'name': d['name'], 'starts': d['Starts'], 'ip': d['IP'],
            'cmd_pct': round(d['CMD'] * 100, 1), 'model_whip': round(d['ModelWHIP'], 3),
            'actual_whip': round(d['ActualWHIP'], 3) if d['ActualWHIP'] is not None else None,
            'babip': round(d['BABIP'], 3) if d['BABIP'] is not None else None,
            'score_relative': round(d['ScoreRelative'], 2),  # FA-only-pool relative score (matches the xlsx)
            'score_absolute': round(d['ScoreAbsolute'], 2) if d['ScoreAbsolute'] is not None else None,
            'abs_rank': d['AbsRankStr'],
        }
        for d in result['fa_pool'].values()
    ]

    start_score = result['start_score']
    start_score_current = [
        {
            'name': name, 'cmd_pct': round(v['cmd_pct'], 1), 'model_whip': round(v['model_whip'], 3),
            'score_relative': round(v['score_relative'], 2) if v['score_relative'] is not None else None,
            'score_absolute': round(v['score_absolute'], 2) if v['score_absolute'] is not None else None,
            'predicted_whip_neutral_opp': round(v['predicted_whip_neutral_opp'], 3),
            'start_score': round(v['start_score'], 3),
            'is_kondor': v['is_kondor'],
        }
        for name, v in start_score['current_scores'].items()
    ]

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'reconciliation': {
            'passed': passed,
            'max_gap_ip': round(max_gap, 1),
            'gap_table': [
                {'team': name, 'computed_ip': round(c, 1), 'espn_ip': round(e, 1), 'gap': round(g, 1)}
                for name, c, e, g in gap_table
            ],
        },
        'roster_flags': result['roster_flags'],
        'step2_kondor_staff': step2_rows,
        'step2_no_data': result['step2_no_data'],
        'fa_pool_count': len(result['fa_pool']),
        'fa_pool': fa_pool_rows,  # full qualifying FA data, same shape as step2_kondor_staff -- needed for Step 5 scoring
        'heatmap_cells': heatmap_cells,
        'teams': teams,  # {team_id: team_name}
        'standings_order': [
            {'team_id': tid, 'team': teams[tid], 'roto_total': roto[tid]['total']}
            for tid in standings_order
        ],
        'start_score': {
            'coefficients': start_score['coefficients'],
            'fit_diagnostics': start_score['fit_diagnostics'],
            'quintile_backtest': start_score['quintile_backtest'],
            'league_avg_trailing_ops': round(start_score['league_avg_trailing_ops'], 3),
            'current_scores': start_score_current,  # Kondor's qualifying pitchers + FA pool, combined
        },
    }


def main():
    result = run(DATA_PATH)
    gap_table, max_gap, passed = result['heatmap_reconciliation']

    if result['roster_flags']:
        print("\n=== ROSTER RECONSTRUCTION FLAGS (informational) ===")
        for f in result['roster_flags']:
            print("-", f)

    summary = build_summary(result)
    with open(SUMMARY_PATH, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"\nWrote {SUMMARY_PATH}")

    if not passed:
        print(f"\nSTEP 4 RECONCILIATION FAILED: max gap {max_gap:.1f} IP "
              f"exceeds threshold. Failing the build -- see gap table above.")
        sys.exit(1)

    print(f"\nStep 4 reconciliation passed: max gap {max_gap:.1f} IP across all 12 teams.")
    sys.exit(0)


if __name__ == '__main__':
    main()
