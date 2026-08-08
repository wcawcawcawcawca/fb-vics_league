"""
step1_roster.py
================
Reconstructs each of the 12 teams' CURRENT roster.

Base rule: current roster = periods[-1] snapshot + all transactions dated on
or after that snapshot's date, applied in chronological order (date + time).
Traded players go to destTeam, not free agency.

Robustness handling (learned from real data, keep these):
  1. EMPTY-SNAPSHOT FALLBACK: if a team's entry in the latest period is empty
     (a scraper glitch -- confirmed to happen to individual teams while
     others are fine), walk backward to the most recent period where that
     team's roster is non-empty and use THAT as the base, applying
     transactions forward from there. Flag this to the user -- don't
     silently guess.
  2. BLANK ARTIFACT ENTRIES: some snapshots contain pitcher slot entries with
     an empty name (unfilled active-slot artifacts from the scrape). Drop
     these before building the roster.
  3. SAME-DAY ADD DEDUPLICATION: if an "added" transaction is dated the same
     day as the base snapshot, the player may already be present in the
     snapshot (because the snapshot was taken after the transaction posted).
     Applying the add again would create a duplicate roster entry. Before
     appending an "added" player, check whether they're already on that
     team's roster; if so, skip and log it as already-reflected.

Run this first; step2-5 all read current_roster.json.
"""
import json
from copy import deepcopy
from datetime import datetime

from pipeline_common import load_unified_json


def resolve_team_name_map(teams):
    """Build a normalized-name -> team_id lookup that tolerates 'The X' prefixes."""
    norm_map = {}
    for k, v in teams.items():
        norm_map[v.lower()] = k
        norm_map[('the ' + v).lower()] = k
        if v.lower().startswith('the '):
            norm_map[v.lower()[4:]] = k
    return norm_map


def parse_tx_datetime(tx):
    """Transaction dates look like 'Sat Aug 8' + '8:00 am'. Strip weekday, parse."""
    d = tx['date']
    t = tx['time']
    parts = d.split(' ', 1)
    md = parts[1] if len(parts) > 1 else d
    return datetime.strptime(f"{md} 2026 {t}", "%b %d %Y %I:%M %p")


def reconstruct_rosters(data, verbose=True):
    """
    Returns (roster, flags, log, unresolved)
      roster: {team_id: {'batters': [...], 'pitchers': [...]}}
      flags: list of str -- discrepancies worth surfacing to the user
      log: list of (datetime, str) -- every move applied
      unresolved: list of (datetime, move_dict, reason) -- moves that couldn't
                  be applied cleanly (usually benign: "already reflected")
    """
    teams = data['meta']['teams']
    norm_map = resolve_team_name_map(teams)

    def resolve_team(name):
        if name is None:
            return None
        key = name.lower().strip()
        if key in norm_map:
            return norm_map[key]
        if key.startswith('the ') and key[4:] in norm_map:
            return norm_map[key[4:]]
        return None

    periods = data['periods']
    last_period = periods[-1]

    # --- Per-team base snapshot, walking backward past empty ones ---
    flags = []
    team_base = {}
    for tid in teams:
        for p in reversed(periods):
            pd = p['players'].get(tid, {})
            if len(pd.get('batters', [])) + len(pd.get('pitchers', [])) > 0:
                team_base[tid] = (p, datetime.strptime(p['dateYMD'], '%Y%m%d'))
                if p is not last_period:
                    flags.append(
                        f"Team {teams[tid]} (id {tid}): latest snapshot "
                        f"({last_period['date']}) was EMPTY for this team -- "
                        f"widened cutoff back to {p['date']} ({p['dateYMD']})."
                    )
                break
        else:
            team_base[tid] = (last_period, datetime.strptime(last_period['dateYMD'], '%Y%m%d'))
            flags.append(f"Team {teams[tid]} (id {tid}): no non-empty snapshot found in entire history.")

    # --- Build base roster per team, dropping blank-name artifact entries ---
    roster = {}
    for tid in teams:
        base_p, _ = team_base[tid]
        pdata = base_p['players'].get(tid, {})
        batters = [p for p in deepcopy(pdata.get('batters', [])) if p.get('name')]
        pitchers_raw = deepcopy(pdata.get('pitchers', []))
        pitchers = [p for p in pitchers_raw if p.get('name')]
        n_blank = len(pitchers_raw) - len(pitchers)
        if n_blank:
            flags.append(f"Team {teams[tid]} (id {tid}): removed {n_blank} blank-name artifact pitcher slots.")
        roster[tid] = {'batters': batters, 'pitchers': pitchers}

    # --- Dedup + sort transactions chronologically ---
    txs = data['transactions']
    parsed = sorted(((parse_tx_datetime(tx), tx) for tx in txs), key=lambda x: x[0])
    seen = set()
    deduped = []
    for dt, tx in parsed:
        for mv in tx.get('moves', []):
            # Key on move content, not just date+time+activityType -- ESPN
            # batches waiver processing so many distinct moves share a timestamp.
            key = (dt.isoformat(), mv.get('raw'))
            if key not in seen:
                seen.add(key)
                deduped.append((dt, mv))
    deduped.sort(key=lambda x: x[0])

    # --- Apply moves ---
    def find_and_remove(team_id, player_name):
        for kind in ('batters', 'pitchers'):
            lst = roster.get(team_id, {}).get(kind, [])
            for i, pl in enumerate(lst):
                if pl['name'] == player_name:
                    return lst.pop(i), kind
        return None, None

    def add_player(team_id, kind, entry):
        roster.setdefault(team_id, {'batters': [], 'pitchers': []})
        roster[team_id].setdefault(kind, [])
        roster[team_id][kind].append(entry)

    def player_on_team(team_id, player_name):
        for kind in ('batters', 'pitchers'):
            for pl in roster.get(team_id, {}).get(kind, []):
                if pl['name'] == player_name:
                    return True
        return False

    log = []
    unresolved = []
    for dt, mv in deduped:
        verb = mv['verb']
        team_id = resolve_team(mv.get('team'))
        player = mv.get('player')
        if team_id is None:
            continue
        base_date = team_base[team_id][1].date()
        if dt.date() < base_date:
            continue  # already reflected in this team's base snapshot

        if verb == 'dropped':
            entry, kind = find_and_remove(team_id, player)
            if entry is None:
                unresolved.append((dt, mv, 'player not found to drop (likely already reflected in base snapshot)'))
            else:
                log.append((dt, f"DROP {player} from {teams[team_id]} ({kind})"))

        elif verb == 'added':
            if player_on_team(team_id, player):
                log.append((dt, f"ADD {player} to {teams[team_id]} -- SKIPPED, already in base snapshot"))
                continue
            pos = mv.get('playerPos', '')
            is_pitcher = any(p in pos for p in ['SP', 'RP', 'P'])
            kind = 'pitchers' if is_pitcher else 'batters'
            entry = {'slot': 'BE', 'name': player, 'team': mv.get('playerTeam'), 'pos': pos, 'active': False}
            if is_pitcher:
                entry['W'] = 0
                entry['SVHD'] = 0
            add_player(team_id, kind, entry)
            log.append((dt, f"ADD {player} to {teams[team_id]} ({kind})"))

        elif verb == 'traded':
            dest_id = resolve_team(mv.get('destTeam'))
            entry, kind = find_and_remove(team_id, player)
            if entry is None:
                unresolved.append((dt, mv, 'player not found to trade'))
            elif dest_id is None:
                unresolved.append((dt, mv, 'unresolved destination team'))
            else:
                add_player(dest_id, kind, entry)
                log.append((dt, f"TRADE {player} from {teams[team_id]} to {teams[dest_id]} ({kind})"))
        else:
            unresolved.append((dt, mv, f'unknown verb: {verb}'))

    if verbose:
        print("=== DISCREPANCY FLAGS ===")
        for f in flags:
            print("-", f)
        print(f"\nApplied {len(log)} moves, {len(unresolved)} unresolved (see below; most are benign)")
        print("\n=== UNRESOLVED (informational) ===")
        for dt, mv, reason in unresolved:
            print(dt, '|', reason, '|', mv.get('raw'))

    return roster, flags, log, unresolved


def main(json_path, out_path='current_roster.json'):
    data = load_unified_json(json_path)
    roster, flags, log, unresolved = reconstruct_rosters(data)
    with open(out_path, 'w') as f:
        json.dump(roster, f, indent=2)

    teams = data['meta']['teams']
    print("\n=== FINAL ROSTER SIZES ===")
    for tid, name in teams.items():
        b = len(roster[tid]['batters'])
        p = len(roster[tid]['pitchers'])
        print(f"  {name}: {b} batters, {p} pitchers")

    return roster, flags


if __name__ == '__main__':
    import sys
    json_path = sys.argv[1] if len(sys.argv) > 1 else 'pennants_over_easy_unified.json'
    main(json_path)
