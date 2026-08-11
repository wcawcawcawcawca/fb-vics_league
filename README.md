# Pennants Over Easy analytics pipeline

This is the actual, tested code behind the 6-step pipeline (roster
reconstruction, Kondor staff table, FA leaderboard, monthly heatmap, 7-day
probables, Start Score model) for league 137080 ("Pennants Over Easy"),
team 2 ("Three Days of the Kondor").

## Why this exists — and the rule that matters most

Previously, the methodology and *formatting* lived only as prose
descriptions that got re-implemented from scratch each session. That's how
real bugs got reintroduced, twice: Step 4's team-attribution logic was
correctly *described* in writing but got rebuilt incorrectly anyway, and on
2026-08-11 both `cmd_free_agents.xlsx` and the Step 5 probables table were
rebuilt in the OLD format because a memory summary was trusted instead of
this code — even though `step3_fa_leaderboard.py` already had the correct
`write_xlsx()` committed the whole time.

**The rule: every step that produces user-facing output (a table, an xlsx,
a heatmap) has a `render_html()` or `write_xlsx()` function in its module.
Fetch the file fresh, read it, and call that function directly. Never
hand-build the output from a data JSON plus a memory/chat-summary
description of what the format "should" look like — that is exactly how
both 2026-08-11 regressions happened.** If the methodology or formatting
needs to change, change it here (with tests against the reconciliation
check in step4 and a rendered-output diff before/after), not by
re-explaining it in chat.

**Upload this whole folder to the Project's files.** In any future
conversation in this Project, ask Claude to `view` these files before
rebuilding anything.

## Files

| File | Purpose |
|---|---|
| `pipeline_common.py` | Shared data loading, IP conversion, appearance flattening, genuine-starter filter, Model WHIP / BABIP / CMD% math, percentile ranking, 30-day trailing window constant. |
| `step1_roster.py` | Roster reconstruction. Handles the empty-snapshot glitch, blank artifact entries, and same-day-add deduplication that real data has actually hit. |
| `step2_kondor_staff.py` | Kondor pitching staff table (trailing 30-day, starts-only, NO shading). `render_html(rows, no_data, ...)` produces the locked plain table -- call it, don't hand-type it. |
| `step3_fa_leaderboard.py` | Builds `cmd_free_agents.xlsx` via `write_xlsx()`: Rank/Pitcher/SS/Date/Opp/Starts/IP/Pure%/Ball%/CMD%/HR%/m_whip/rl_whip/BABIP/rel_score/abs_score/abs_rank, first-initial names, cell-level shading by rank-thirds. |
| `step4_heatmap.py` | Monthly WHIP/BABIP heatmap. **Contains the critical date-accurate + active-slot attribution fix and the mandatory IP reconciliation gate.** `render_html(cells, standings_order, team_names)` produces the locked teal-to-coral grid. Read the module docstring before changing anything here. |
| `step5_probables.py` | 7-day probables table. Needs the FanGraphs grid supplied by the caller each run (live fetch or user paste) -- can't run unattended. `render_html(by_date, dates_order)` produces the locked swatch-column format (green/yellow/red = `#5FCB6C`/`#F2C744`/`#E8697D`, "Strong/Middling/Weak" legend, Start Score column right after Pitcher). |
| `step6_start_score.py` | Start Score model: `actual_whip ~ cmd_pct + model_whip + opp_trailing_ops`, refit fresh every run, walk-forward/no-lookahead. `matchup_start_score()` needs the RAW unified JSON (`build_team_offense_index(data)`) -- this is why Start Score can't be computed from `latest_summary.json`/`step3_fa_pool.json` alone; fetch `data/pennants_over_easy_unified.json.gz` too. |
| `run_pipeline.py` | Orchestrates Steps 1-4 and 6 in order and prints the reconciliation table. Step 5 is run separately once the FanGraphs grid is available. |

## Running it

```bash
pip install openpyxl --break-system-packages
python3 run_pipeline.py /path/to/pennants_over_easy_unified.json
```

Produces in the working directory:
- `current_roster.json` -- Step 1 output, read by everything downstream
- `step2_pool.json` -- Step 2 data; call `step2_kondor_staff.render_html(rows, no_data, ...)` on it
- `cmd_free_agents.xlsx` -- Step 3, final deliverable, produced directly by `write_xlsx()`
- `step4_cells.json` -- Step 4 data; call `step4_heatmap.render_html(cells, standings_order, team_names)` on it **after** confirming every team's reconciliation gap is under 5 IP
- `step6_start_score.json` -- Step 6 coefficients + neutral-opponent scores

Step 5 needs to be run separately once you have the FanGraphs grid text --
build the `probables` dict per `step5_probables.py`'s docstring, run
`build_by_date_rows()`, then `render_html()` on the result.

## The bugs this code fixes, for context

1. **Roster reconstruction on a glitched snapshot.** An early upload had an
   empty roster for two teams due to a scraper hiccup, not because the
   teams actually had no players. `step1_roster.py` detects this and walks
   back to the last good snapshot for that team only.

2. **Step 4 team-IP attribution.** Two related mistakes, both fixed and
   guarded by `reconcile()`: current-team attribution instead of
   date-accurate roster (undercounted IP by hundreds of innings), and
   missing the `active === True` filter (overcounted by including bench/IL
   innings ESPN doesn't credit). Both fixes together reconcile computed IP
   to within ~0.2-4.0 IP of the bookmarklet's own tracked total for all 12
   teams. `step4_heatmap.py` will not silently emit a heatmap if a gap
   exceeds 5 IP -- it prints the gap table and stops.

3. **Format regression from trusting memory over code (2026-08-11).** Both
   `cmd_free_agents.xlsx` and the Step 5 probables table were rebuilt in a
   stale format because a chat memory summary was used instead of reading
   `step3_fa_leaderboard.py` / `step5_probables.py` directly. Fixed by (a)
   adding `render_html()` to every step that was missing one, and (b) this
   README section making the "always read + call the function" rule
   impossible to miss.
