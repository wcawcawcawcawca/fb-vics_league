"""
step3_fa_leaderboard.py
=========================
Free agent CMD leaderboard -> cmd_free_agents.xlsx

Same trailing-20-day, starts-only window and genuine-starter filter as
Step 2. Qualification: 2+ starts AND 5+ IP in the window, excluding anyone
rostered on any of the 12 teams.

Locked columns (NO ERA, NO K%/BB% -- these were removed from an earlier
draft of this file and must not come back):
  Rank, Pitcher, Starts, IP, Pure%, Ball%, CMD%, HR%, Model WHIP,
  Actual WHIP, BABIP, Score (Relative), Score (Absolute), Rank (Absolute)

Score (Relative) = min(CMD%, Model WHIP) percentiles within the FA-ONLY pool.
                    Drives sort order and cell shading.
Score (Absolute) = same formula against the league-wide qualifying pool.
Rank (Absolute)  = literal rank position with pool size, e.g. "45 of 149".

Stoplight cell shading (NOT full-row) on Pitcher / CMD% / Model WHIP columns
only, using the locked hex colors below. Tiers = thirds by Score (Relative)
rank position (top third green, middle third yellow, bottom third red).

Always writes to the SAME filename (cmd_free_agents.xlsx) so re-running the
pipeline updates the existing preview rather than creating a new file.
"""
import json
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from pipeline_common import load_unified_json, percentile_rank
from step2_kondor_staff import build_pool, score_pool, LEAGUE_MIN_STARTS, LEAGUE_MIN_IP

GREEN = "9BE39B"
YELLOW = "FFEB9C"
RED = "F7A6AC"
HEADER_FILL_HEX = "2A4D3A"


def build_fa_pool(pool):
    """FA-only pool: not on any of the 12 rosters, meets league qualification
    thresholds. Attaches ScoreRelative computed within the FA-only pool."""
    fa_pool = {n: p for n, p in pool.items()
               if p['team_id'] is None and p['Starts'] >= LEAGUE_MIN_STARTS and p['IP'] >= LEAGUE_MIN_IP}

    cmd_vals = [p['CMD'] for p in fa_pool.values()]
    whip_vals = [p['ModelWHIP'] for p in fa_pool.values()]
    for name, d in fa_pool.items():
        cmd_pct = percentile_rank(d['CMD'], cmd_vals, higher_is_better=True)
        whip_pct = percentile_rank(d['ModelWHIP'], whip_vals, higher_is_better=False)
        d['ScoreRelative'] = min(cmd_pct, whip_pct)

    return fa_pool


def write_xlsx(fa_pool, out_path='cmd_free_agents.xlsx'):
    rows = sorted(fa_pool.values(), key=lambda d: -d['ScoreRelative'])
    n = len(rows)

    wb = Workbook()
    ws = wb.active
    ws.title = "Free Agent CMD"

    headers = ["Rank", "Pitcher", "Starts", "IP", "Pure%", "Ball%", "CMD%", "HR%",
               "Model WHIP", "Actual WHIP", "BABIP", "Score (Relative)",
               "Score (Absolute)", "Rank (Absolute)"]
    ws.append(headers)

    header_fill = PatternFill(start_color=HEADER_FILL_HEX, end_color=HEADER_FILL_HEX, fill_type="solid")
    header_font = Font(name="Arial", bold=True, color="FFFFFF")
    normal_font = Font(name="Arial")
    bold_dark_font = Font(name="Arial", bold=True, color="2C2C2A")

    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    for i, d in enumerate(rows):
        r = i + 2
        ws.cell(row=r, column=1, value=i + 1)
        ws.cell(row=r, column=2, value=d['name'])
        ws.cell(row=r, column=3, value=d['Starts'])
        ws.cell(row=r, column=4, value=round(d['IP'], 1))
        ws.cell(row=r, column=5, value=round(d['Purepct'], 4))
        ws.cell(row=r, column=6, value=round(d['Ballpct'], 4))
        ws.cell(row=r, column=7, value=round(d['CMD'], 4))
        ws.cell(row=r, column=8, value=round(d['HRpct'], 4))
        ws.cell(row=r, column=9, value=round(d['ModelWHIP'], 3))
        ws.cell(row=r, column=10, value=round(d['ActualWHIP'], 3) if d['ActualWHIP'] is not None else None)
        ws.cell(row=r, column=11, value=round(d['BABIP'], 3) if d['BABIP'] is not None else None)
        ws.cell(row=r, column=12, value=round(d['ScoreRelative'], 4))
        ws.cell(row=r, column=13, value=round(d['ScoreAbsolute'], 4) if d['ScoreAbsolute'] is not None else None)
        ws.cell(row=r, column=14, value=d['AbsRankStr'])

        frac = i / n
        color = GREEN if frac < 1 / 3 else (YELLOW if frac < 2 / 3 else RED)
        fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
        for col in (2, 7, 9):  # Pitcher, CMD%, Model WHIP ONLY -- not full row
            cell = ws.cell(row=r, column=col)
            cell.fill = fill
            cell.font = bold_dark_font if col == 2 else normal_font

        for col in range(1, 15):
            cell = ws.cell(row=r, column=col)
            if cell.font is None or cell.font.name != "Arial":
                cell.font = normal_font

    for col in (5, 6, 7, 8):
        for r in range(2, n + 2):
            ws.cell(row=r, column=col).number_format = "0.0%"
    for col in (9, 10, 11):
        for r in range(2, n + 2):
            ws.cell(row=r, column=col).number_format = "0.000"
    for col in (12, 13):
        for r in range(2, n + 2):
            ws.cell(row=r, column=col).number_format = "0.00"

    widths = {1: 6, 2: 20, 3: 8, 4: 7, 5: 8, 6: 8, 7: 8, 8: 7, 9: 11,
              10: 11, 11: 8, 12: 15, 13: 15, 14: 13}
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w

    notes_row = n + 3
    notes = [
        "Stoplight shading (Pitcher, CMD%, Model WHIP) reflects Score (Relative): MIN of each pitcher's percentile rank on CMD% (higher=better) and Model WHIP (lower=better) within this free-agent-only pool -- a pitcher must be strong on BOTH to score green. Green = top third, yellow = middle third, red = bottom third, by Score (Relative) rank position.",
        "Score (Absolute) uses the same min-of-two-percentiles formula but computed against the league-wide qualifying pool (all qualifying rostered pitchers across all 12 teams, plus free agents; 2+ starts and 5+ IP in the trailing 20-day window). Rank (Absolute) shows literal rank position within that league-wide pool.",
        "'Starts' are restricted to genuine starting pitchers: first-listed in the box score AND a season-wide average of 4.0+ IP when first-listed.",
        "Pure% and Ball% are each that pitch type's share of total pitches thrown (balls + pure strikes + in-play pitches), not batters faced. CMD% = Pure% - Ball%.",
        "K%, BB%, HR% (Model WHIP inputs) are correctly denominated by batters faced (BF) -- separate, correct usage from Pure%/Ball%.",
        "BABIP approximated as (H-HR)/(BF-BB-K-HR); HBP and sac flies aren't broken out in the source gamelogs.",
        "Model WHIP = 1.290 - 2.208*K% + 4.402*BB% + 3.766*HR%, cross-validated regression, CV R^2 = 0.58. Actual WHIP is real (H+BB)/IP over the same window.",
        "Free agent status computed as of the roster snapshot date plus any subsequent add/drop/trade transactions in the file.",
    ]
    for j, note in enumerate(notes):
        cell = ws.cell(row=notes_row + j, column=2, value=note)
        cell.font = Font(name="Arial", italic=True, size=9, color="5F5E5A")
        cell.alignment = Alignment(wrap_text=True)

    ws.freeze_panes = "A2"
    wb.save(out_path)
    return out_path, n


def main(json_path, roster_path='current_roster.json', out_path='cmd_free_agents.xlsx'):
    data = load_unified_json(json_path)
    with open(roster_path) as f:
        roster = json.load(f)

    pool, window_start, max_date, appearances, genuine_starters = build_pool(data, roster)
    pool, league_pool = score_pool(pool)
    fa_pool = build_fa_pool(pool)

    path, n = write_xlsx(fa_pool, out_path)
    print(f"Wrote {path} with {n} free agents.")

    with open('step3_fa_pool.json', 'w') as f:
        json.dump(fa_pool, f, indent=2)

    return fa_pool


if __name__ == '__main__':
    import sys
    json_path = sys.argv[1] if len(sys.argv) > 1 else 'pennants_over_easy_unified.json'
    main(json_path)
