"""
Parse Retrosheet 2024 event files into the raw ingredients for a Leverage Index model.

Retrosheet event files are the play-by-play record of every MLB game, written in a
compact scoring notation. A line looks like:

    play,7,1,ohtas001,32,BCFBBX,D9/L9D.2-H;1-3

    play , inning , half(0=away bats) , batter , count , pitch-sequence , event

This module turns that notation into, for every plate appearance:
  * the game state before the PA  (inning, half, outs, who's on base, score diff)
  * the pitch-by-pitch trajectory (so we can condition on the count)
  * the state after the PA        (new bases/outs, runs that scored)

Nothing here is modelled or assumed -- it is a transcription of what actually
happened in 2024. The modelling happens in build_model.py.

Validation (printed at the end of a run): every game's reconstructed final score
is compared to the official box-score line from Retrosheet's .EB* files. If the
parser mis-handles a notation, the scores diverge and the game is reported.
"""

import re
import os
import glob
import pickle
from collections import Counter, defaultdict

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# ---------------------------------------------------------------------------
# Pitch codes (Retrosheet "pitches" field)
# ---------------------------------------------------------------------------
P_BALL = set("BIPV")       # ball, intentional ball, pitchout, ball (pitcher to mouth)
P_STRIKE = set("CKSQMTLO")  # called, unknown, swinging, swing-on-pitchout, missed bunt,
#                             foul tip, foul bunt, foul tip on bunt  -- all can be strike 3
P_FOUL = set("FR")          # foul, foul on pitchout -- strike only when < 2 strikes
P_INPLAY = set("XY")        # ball put in play
P_HBP = set("H")
# everything else (.123>+*NU) is a marker or a non-pitch and is skipped

# Plate-appearance outcome categories used by the model
CATS = ["K", "BB", "HBP", "1B", "2B", "3B", "HR", "OUT", "OTHER"]


def pitch_trajectory(pitches):
    """Walk a pitch string, yielding (balls, strikes, result) for each real pitch.

    `result` is one of: ball, strike, foul, inplay, hbp.
    Returns (list_of_steps, final_balls, final_strikes).
    """
    steps = []
    b = s = 0
    for ch in pitches:
        if ch in P_BALL:
            steps.append((b, s, "ball"))
            b += 1
        elif ch in P_STRIKE:
            steps.append((b, s, "strike"))
            s += 1
        elif ch in P_FOUL:
            steps.append((b, s, "foul"))
            if s < 2:
                s += 1
        elif ch in P_INPLAY:
            steps.append((b, s, "inplay"))
        elif ch in P_HBP:
            steps.append((b, s, "hbp"))
        # markers / no-pitch: ignore
    return steps


# ---------------------------------------------------------------------------
# Event string parsing
# ---------------------------------------------------------------------------
ANNOT = re.compile(r"[!?#]")
PAREN_RUNNER = re.compile(r"\((B|1|2|3)\)")
ERROR_IN = re.compile(r"E\d")


def split_unparen(s, sep):
    """Split on `sep`, ignoring separators inside parentheses."""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


class ParseError(Exception):
    pass


def parse_play(event, bases, outs):
    """Apply one event to the current state.

    bases: 3-tuple of bools (1B, 2B, 3B occupied)
    Returns (new_bases, outs_made, runs, category, is_pa)
    category is None for non-PA events (steals, wild pitches, ...).
    """
    ev = ANNOT.sub("", event)
    parts = split_unparen(ev, ".")
    play_part = parts[0]
    adv_part = ".".join(parts[1:])

    # --- explicit advances, e.g. "2-H;1X3(85)"
    moves = {}          # runner source -> destination base (1,2,3,4=home)
    out_runners = set()
    if adv_part:
        for a in split_unparen(adv_part, ";"):
            a = a.strip()
            if len(a) < 3 or a[0] not in "B123":
                continue
            src, sym, dst = a[0], a[1], a[2]
            rest = a[3:]
            dest = 4 if dst == "H" else (int(dst) if dst in "123" else None)
            if dest is None:
                continue
            if sym == "X" and not ERROR_IN.search(rest):
                out_runners.add(src)
                moves.pop(src, None)
            elif sym in "-X":
                moves[src] = dest

    # --- the play itself, possibly compound ("K+SB2", "SB2;SB3")
    batter_dest = None      # None = not resolved yet
    batter_out = False
    is_pa = False
    category = None

    tokens = []
    for chunk in split_unparen(play_part, "+"):
        tokens.extend(split_unparen(chunk, ";"))

    for tok in tokens:
        basic = split_unparen(tok, "/")[0]
        if not basic:
            continue

        if basic.startswith("SB"):                       # stolen base
            b = basic[2]
            src = {"2": "1", "3": "2", "H": "3"}.get(b)
            if src and src not in moves and src not in out_runners:
                moves[src] = 4 if b == "H" else int(b)
        elif basic.startswith("CS") or basic.startswith("POCS"):
            b = basic[4] if basic.startswith("POCS") else basic[2]
            src = {"2": "1", "3": "2", "H": "3"}.get(b)
            if src:
                if ERROR_IN.search(basic):               # error -> runner safe, takes the base
                    if src not in moves:
                        moves[src] = 4 if b == "H" else int(b)
                elif src not in moves:
                    out_runners.add(src)
        elif basic.startswith("PO"):                     # pickoff
            b = basic[2] if len(basic) > 2 else ""
            if b in "123" and not ERROR_IN.search(basic):
                if b not in moves:
                    out_runners.add(b)
        elif basic.startswith(("WP", "PB", "BK", "DI", "OA", "FLE", "NP")) or basic == "":
            pass                                          # advances (if any) are explicit
        elif basic.startswith("HP"):
            batter_dest, is_pa, category = 1, True, "HBP"
        elif basic.startswith("IW") or basic == "I" or (basic[0] == "W" and not basic.startswith("WP")):
            batter_dest, is_pa, category = 1, True, "BB"
        elif basic[0] == "K":
            is_pa, category = True, "K"
            batter_out = True                             # unless an advance says otherwise
        elif basic.startswith("DGR"):
            batter_dest, is_pa, category = 2, True, "2B"
        elif basic[0] == "S" and not basic.startswith("SB"):
            batter_dest, is_pa, category = 1, True, "1B"
        elif basic[0] == "D" and not basic.startswith("DI"):
            batter_dest, is_pa, category = 2, True, "2B"
        elif basic[0] == "T":
            batter_dest, is_pa, category = 3, True, "3B"
        elif basic.startswith("HR") or basic == "H":
            batter_dest, is_pa, category = 4, True, "HR"
        elif basic[0] == "E":
            batter_dest, is_pa, category = 1, True, "OTHER"
        elif basic.startswith("FC"):
            batter_dest, is_pa, category = 1, True, "OTHER"
        elif basic[0] == "C":
            batter_dest, is_pa, category = 1, True, "OTHER"   # catcher's interference
        elif basic[0].isdigit():
            is_pa, category = True, "OUT"
            runners = PAREN_RUNNER.findall(basic)
            for r in runners:
                if r == "B":
                    batter_out = True
                elif r not in moves:
                    out_runners.add(r)
            if "B" in runners:
                pass
            elif not runners:
                batter_out = True                          # plain fielded out
            else:
                tail = basic[basic.rfind(")") + 1:]
                if any(c.isdigit() for c in tail):
                    batter_out = True                      # relay to first completes the DP
                else:
                    batter_dest = 1                        # force out elsewhere, batter safe
        else:
            raise ParseError("unhandled basic play: %r" % basic)

    if "B" in moves:            # an explicit B- advance always wins
        batter_dest = moves["B"]
        batter_out = False
    if "B" in out_runners:
        # the batter was retired on the bases (thrown out stretching, dropped 3rd
        # strike, ...). Count that out once, via batter_out, not twice.
        out_runners.discard("B")
        batter_out = True
        batter_dest = None

    # --- forced advances: if the batter takes first, everyone stacked behind moves up
    if batter_dest == 1 and not batter_out:
        for src in ("1", "2", "3"):
            i = int(src) - 1
            if not bases[i] or src in out_runners:
                break
            if src not in moves:
                moves[src] = int(src) + 1
            if moves[src] != int(src) + 1:
                break

    # --- resolve final state
    new_bases = [False, False, False]
    runs = 0
    outs_made = len(out_runners) + (1 if batter_out else 0)

    for src in ("3", "2", "1"):
        i = int(src) - 1
        if not bases[i]:
            if src in moves or src in out_runners:
                raise ParseError("phantom runner on %s" % src)
            continue
        if src in out_runners:
            continue
        dest = moves.get(src, int(src))
        if dest >= 4:
            runs += 1
        else:
            if new_bases[dest - 1]:
                raise ParseError("two runners on base %d" % dest)
            new_bases[dest - 1] = True

    if not batter_out and batter_dest is not None:
        if batter_dest >= 4:
            runs += 1
        else:
            if new_bases[batter_dest - 1]:
                raise ParseError("batter collides on base %d" % batter_dest)
            new_bases[batter_dest - 1] = True

    if outs + outs_made > 3:
        raise ParseError("more than 3 outs")

    return tuple(new_bases), outs_made, runs, category, is_pa


# ---------------------------------------------------------------------------
# Game walk
# ---------------------------------------------------------------------------
def base_code(bases):
    """0..7 code for the base state: bit0=1B, bit1=2B, bit2=3B."""
    return (1 if bases[0] else 0) | (2 if bases[1] else 0) | (4 if bases[2] else 0)


def load_final_scores(paths):
    """game_id -> (away_runs, home_runs) from Retrosheet box-score `line` records."""
    scores = {}
    for path in paths:
        gid = None
        cur = {}
        with open(path, errors="replace") as f:
            for ln in f:
                p = ln.rstrip("\n").split(",")
                if p[0] == "id":
                    if gid and len(cur) == 2:
                        scores[gid] = (cur[0], cur[1])
                    gid, cur = p[1], {}
                elif p[0] == "line":
                    side = int(p[1])
                    cur[side] = sum(int(x) for x in p[2:] if x.strip().lstrip("-").isdigit())
        if gid and len(cur) == 2:
            scores[gid] = (cur[0], cur[1])
    return scores


def parse_season(event_paths, box_paths):
    finals = load_final_scores(box_paths)

    out = {
        # (base_code, outs, category) -> Counter[(new_base_code, new_outs, runs)]
        "trans": defaultdict(Counter),
        # (balls, strikes) -> Counter[result]  where result is ball/strike/foul/hbp/ip:<CAT>
        "pitch": defaultdict(Counter),
        # (balls, strikes) -> Counter[final PA category]   (empirical, for cross-checks)
        "count_pa": defaultdict(Counter),
        # frequency weights for the LI normaliser
        "pa_states": Counter(),      # (inning, half, outs, base_code, diff)
        "pitch_states": Counter(),   # (inning, half, outs, base_code, diff, balls, strikes)
        "cat_totals": Counter(),
        "games": 0,
        "bad_games": [],
        "count_field_checked": 0,
        "count_field_match": 0,
        "rollovers": 0,
        "home_wins": 0,
        # empirical run expectancy: (base_code, outs) -> [runs to end of half, n]
        "re_runs": Counter(),
        "re_n": Counter(),
    }

    for path in event_paths:
        gid = None
        state = None
        plays = None
        for ln in open(path, errors="replace"):
            p = ln.rstrip("\n").split(",")
            if p[0] == "id":
                if gid:
                    _finish(gid, plays, out, finals)
                gid, plays = p[1], []
            elif p[0] in ("play", "radj"):
                plays.append(p)
        if gid:
            _finish(gid, plays, out, finals)
    return out


def _finish(gid, plays, out, finals):
    """Replay one game, recording states. Discard the game if anything is off.

    Transitions are recorded from the state at the START of a plate appearance to
    the state when that PA ends, so anything that happens mid-PA (a steal, a wild
    pitch, a balk) is folded into that PA's transition rather than being ignored.
    """
    bases = (False, False, False)
    outs = 0
    score = [0, 0]          # [away, home]
    half_key = None
    pa_bases, pa_outs, pa_runs, pa_diff = bases, 0, 0, 0
    half_states, half_runs = [], 0        # for empirical run expectancy
    re_runs, re_n = Counter(), Counter()
    rows_trans, rows_pitch, rows_pa_state, rows_pitch_state, rows_count = [], [], [], [], []
    cat_totals = Counter()
    rollovers = 0

    try:
        pending_radj = None
        for p in plays:
            if p[0] == "radj":
                pending_radj = int(p[2])          # extra-innings automatic runner
                continue
            inning, half, count_f, pitches, event = int(p[1]), int(p[2]), p[4], p[5], p[6]
            if event == "NP":
                continue
            if (inning, half) != half_key:
                if half_key is not None and pa_started:
                    rollovers += 1            # half ended mid-PA (e.g. caught stealing)
                half_states, half_runs = [], 0
                half_key, bases, outs = (inning, half), (False, False, False), 0
                pa_bases, pa_outs, pa_runs = bases, 0, 0
                pa_diff = score[half] - score[1 - half]
                pa_started = False
            if pending_radj:
                b = [False, False, False]
                b[pending_radj - 1] = True
                bases = tuple(x or y for x, y in zip(bases, b))
                pa_bases = bases
                pending_radj = None

            new_bases, outs_made, runs, cat, is_pa = parse_play(event, bases, outs)
            pa_started = True
            pa_runs += runs
            score[half] += runs
            runs_before_play = half_runs
            half_runs += runs
            bases, outs = new_bases, outs + outs_made

            if is_pa:
                inn = min(inning, 10)
                d = max(-15, min(15, pa_diff))
                start_bc = base_code(pa_bases)
                rows_pa_state.append((inn, half, pa_outs, start_bc, d))
                half_states.append((start_bc, pa_outs, half_runs - pa_runs))
                rows_trans.append(((start_bc, pa_outs, cat), (base_code(bases), outs, pa_runs)))
                cat_totals[cat] += 1

                steps = pitch_trajectory(pitches)
                if steps:
                    fb, fs, _ = steps[-1]
                    out["count_field_checked"] += 1
                    if count_f.isdigit() and len(count_f) == 2 and (int(count_f[0]), int(count_f[1])) == (fb, fs):
                        out["count_field_match"] += 1
                for (b, s, res) in steps:
                    if b > 3 or s > 2:
                        break
                    key = (b, s)
                    rows_pitch.append((key, "ip:" + cat if res == "inplay" else res))
                    rows_count.append((key, cat))
                    rows_pitch_state.append((inn, half, pa_outs, start_bc, d, b, s))

                # next PA starts from here
                pa_bases, pa_outs, pa_runs = bases, outs, 0
                pa_diff = score[half] - score[1 - half]
                pa_started = False

            if outs >= 3:
                # a completed half-inning: bank runs-to-end-of-inning for RE24
                for (bc_, o_, r_) in half_states:
                    re_runs[(bc_, o_)] += half_runs - r_
                    re_n[(bc_, o_)] += 1
                half_states, half_runs = [], 0
                if pa_started:
                    rollovers += 1
                half_key = None
                bases, outs = (False, False, False), 0
                pa_bases, pa_outs, pa_runs = bases, 0, 0
                pa_started = False
    except ParseError as e:
        out["bad_games"].append((gid, "parse: %s [inn %s ev %s bases %s outs %s]"
                                % (e, p[1], p[6], bases, outs)))
        return

    if gid not in finals:
        out["bad_games"].append((gid, "no box score"))
        return
    if tuple(score) != finals[gid]:
        out["bad_games"].append((gid, "score %s vs official %s" % (tuple(score), finals[gid])))
        return

    out["games"] += 1
    if score[1] > score[0]:
        out["home_wins"] += 1
    out["rollovers"] += rollovers
    for k, v in rows_trans:
        out["trans"][k][v] += 1
    for k, v in rows_pitch:
        out["pitch"][k][v] += 1
    for k, v in rows_count:
        out["count_pa"][k][v] += 1
    for st in rows_pa_state:
        out["pa_states"][st] += 1
    for st in rows_pitch_state:
        out["pitch_states"][st] += 1
    out["cat_totals"].update(cat_totals)
    out["re_runs"].update(re_runs)
    out["re_n"].update(re_n)


def main():
    src = os.environ.get("RS_DIR", os.path.join(DATA, "rs2024"))
    ev = sorted(glob.glob(os.path.join(src, "2024*.EV*")))
    bx = sorted(glob.glob(os.path.join(src, "2024.EB*")))
    if not ev:
        raise SystemExit("no event files in %s (set RS_DIR)" % src)
    print("parsing %d event files ..." % len(ev))
    res = parse_season(ev, bx)

    total_games = res["games"] + len(res["bad_games"])
    print("\n--- parser validation ---")
    print("games replayed and matching the official final score: %d / %d (%.2f%%)"
          % (res["games"], total_games, 100.0 * res["games"] / total_games))
    print("plate appearances: %d" % sum(res["cat_totals"].values()))
    print("half-innings ending mid-PA (excluded from transitions): %d" % res["rollovers"])
    print("derived count == Retrosheet count field: %d / %d (%.3f%%)"
          % (res["count_field_match"], res["count_field_checked"],
             100.0 * res["count_field_match"] / max(1, res["count_field_checked"])))
    if res["bad_games"]:
        print("discarded games (first 15):")
        for g, why in res["bad_games"][:15]:
            print("   ", g, why)

    print("\n--- empirical 2024 run expectancy (runs from state to end of inning) ---")
    names = ["___", "1__", "_2_", "12_", "__3", "1_3", "_23", "123"]
    print("           0 out   1 out   2 out")
    for bc in range(8):
        row = "  %s   " % names[bc]
        for o in range(3):
            n_ = res["re_n"][(bc, o)]
            row += "  %5.3f" % (res["re_runs"][(bc, o)] / n_) if n_ else "     --"
        print(row)

    n = sum(res["cat_totals"].values())
    print("\n--- 2024 league rates per PA (parsed) ---")
    for c in CATS:
        print("  %-6s %7d  %6.2f%%" % (c, res["cat_totals"][c], 100.0 * res["cat_totals"][c] / n))

    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, "parsed2024.pkl"), "wb") as f:
        pickle.dump({k: (dict(v) if isinstance(v, defaultdict) else v) for k, v in res.items()}, f)
    print("\nwrote %s" % os.path.join(DATA, "parsed2024.pkl"))


if __name__ == "__main__":
    main()
