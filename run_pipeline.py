"""
run_pipeline.py
=================
Orchestrates Steps 1-4 against a freshly uploaded
pennants_over_easy_unified.json. Step 5 needs the FanGraphs probables grid
(fetched live or pasted by the user) so it's run separately -- see
step5_probables.py's docstring.

Usage:
    python run_pipeline.py /path/to/pennants_over_easy_unified.json

Produces, in the current directory:
    current_roster.json      (Step 1)
    step2_pool.json          (Step 2 data -- render the Kondor staff table from this)
    cmd_free_agents.xlsx     (Step 3 -- final deliverable)
    step4_cells.json         (Step 4 data -- render the heatmap from this)

And prints the Step 4 IP reconciliation table, which MUST show all gaps
under the threshold before the heatmap is presented to the user as final.
"""
import sys

import step1_roster
import step2_kondor_staff
import step3_fa_leaderboard
import step4_heatmap
import step6_start_score
from pipeline_common import load_unified_json


def run(json_path):
    print("#" * 70)
    print("STEP 1: Roster reconstruction")
    print("#" * 70)
    data = load_unified_json(json_path)
    roster, flags = step1_roster.main(json_path)

    print("\n" + "#" * 70)
    print("STEP 2: Kondor pitching staff table")
    print("#" * 70)
    rows, no_data, pool = step2_kondor_staff.main(json_path)

    print("\n" + "#" * 70)
    print("STEP 3: Free agent CMD leaderboard")
    print("#" * 70)
    fa_pool = step3_fa_leaderboard.main(json_path)

    print("\n" + "#" * 70)
    print("STEP 4: Monthly WHIP/BABIP heatmap (with mandatory reconciliation check)")
    print("#" * 70)
    cells, gap_table, max_gap, passed = step4_heatmap.main(json_path)

    if not passed:
        print("\n" + "!" * 70)
        print("! STOP: Step 4 reconciliation failed. Do not present the heatmap")
        print("! to the user until this is investigated and resolved.")
        print("!" * 70)

    print("\n" + "#" * 70)
    print("STEP 5: Not run automatically -- needs the FanGraphs probables grid.")
    print("See step5_probables.py for how to supply it.")
    print("#" * 70)

    print("\n" + "#" * 70)
    print("STEP 6: Start Score (composite streaming score, regression-fit + backtested)")
    print("#" * 70)
    step6_result = step6_start_score.main(json_path)

    return {
        'data': data,
        'roster': roster,
        'roster_flags': flags,
        'step2_rows': rows,
        'step2_no_data': no_data,
        'fa_pool': fa_pool,
        'heatmap_cells': cells,
        'heatmap_reconciliation': (gap_table, max_gap, passed),
        'start_score': step6_result,
    }


if __name__ == '__main__':
    json_path = sys.argv[1] if len(sys.argv) > 1 else 'pennants_over_easy_unified.json'
    run(json_path)
