# Pennants Over Easy analytics pipeline

This is the actual, tested code behind the 5-step pipeline (roster
reconstruction, Kondor staff table, FA leaderboard, monthly heatmap, 7-day
probables) for league 137080 ("Pennants Over Easy"), team 2 ("Three Days of
the Kondor").

## Why this exists

Previously, the methodology lived only as prose instructions that got
re-implemented from scratch each session. That's how a real bug got
reintroduced: Step 4's team-attribution logic was correctly *described* in
writing but got rebuilt incorrectly anyway. Checked-in code doesn't have that
failure mode — if these files don't change, the output doesn't change.

**Upload this whole folder to the Project's files.** In any future
conversation in this Project, ask Claude to `view` these files before
rebuilding anything, and to run them directly rather than re-deriving the
logic. If the methodology needs to change, change it here (with tests
against the reconciliation check in step4), not by re-explaining it in chat.

## Files

| File | Purpose |
|---|---|
| `pipeline_common.py` | Shared data loading, IP conversion, appearance flattening, genuine-starter filter, Model WHIP / BABIP / CMD% math, percentile ranking. All the locked formulas live here with docstrings explaining *why*. |
| `step1_roster.py` | Roster reconstruction. Handles the empty-snapshot glitch, blank artifact entries, and same-day-add deduplication that real data has actually hit. |
| `step2_kondor_staff.py` | Kondor pitching staff table (trailing 20-day, starts-only, no shading). |
| `step3_fa_leaderboard.py` | Builds `cmd_free_agents.xlsx`, the FA CMD leaderboard, with cell-level stoplight shading. |
| `step4_heatmap.py` | Monthly WHIP/BABIP heatmap. **Contains the critical date-accurate + active-slot attribution fix and the mandatory IP reconciliation gate.** Read the module docstring before changing anything here. |
| `step5_probables.py` | 7-day probables table logic. Needs the FanGraphs grid supplied by the caller each run (live fetch or user paste) — can't run unattended. |
| `run_pipeline.py` | Orchestrates Steps 1–4 in order and prints the reconciliation table. |

## Running it

```bash
pip install openpyxl --break-system-packages
python3 run_pipeline.py /path/to/pennants_over_easy_unified.json
```

Produces in the working directory:
- `current_roster.json` — Step 1 output, read by everything downstream
- `step2_pool.json` — Step 2 data (render the Kondor table from this)
- `cmd_free_agents.xlsx` — Step 3, final deliverable
- `step4_cells.json` — Step 4 data (render the heatmap from this) **plus a
  printed reconciliation table that must show every team's gap under 5 IP
  before the heatmap is presented as final**

Step 5 needs to be run separately once you have the FanGraphs grid text —
see `step5_probables.py`'s docstring for the expected input format.

## The two bugs this code fixes, for context

1. **Roster reconstruction on a glitched snapshot.** Aug 7's upload had an
   empty roster for two teams due to a scraper hiccup, not because the
   teams actually had no players. `step1_roster.py` detects this (empty
   snapshot for a specific team while others are fine) and walks back to
   the last good snapshot for that team only, rather than either crashing
   or silently producing an empty roster.

2. **Step 4 team-IP attribution.** Two related mistakes, both now fixed and
   guarded by `reconcile()`:
   - Attributing a pitcher's whole season to their *current* team instead
     of whoever rostered them on each specific date — undercounted IP by
     hundreds of innings.
   - Not filtering to `active === True` on that date — overcounted IP by
     including bench/IL appearances that ESPN itself doesn't credit.

   Both fixes together reconcile computed IP to within ~0.2–4.0 IP of the
   bookmarklet's own tracked total, for all 12 teams. `step4_heatmap.py`
   will not silently emit a heatmap if a future data change reintroduces a
   gap over 5 IP — it prints the gap table and stops.
