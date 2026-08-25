"""
Build a Leverage Index model from the parsed 2024 season and export it as JSON
for the web app.

WHAT LEVERAGE INDEX IS
----------------------
Tom Tango's Leverage Index asks: how much is this moment capable of swinging the
game? For a game state S,

    LI(S) = E| change in win expectancy over the next plate appearance |
            ------------------------------------------------------------
            the same quantity averaged over every plate appearance in a season

LI = 1.0 is a perfectly average moment; LI = 3 means this spot can move the game
three times as much as a typical one. The denominator is what turns a raw
win-probability swing into an index, and here it is measured directly off 2024
rather than borrowed from a published constant.

WHAT THIS SCRIPT BUILDS
-----------------------
1. A plate-appearance transition model, P(new base/out state, runs | state,
   outcome), taken straight from what happened in 2024 -- no advancement rules
   assumed, so double plays, runners going first-to-third and everything else
   are in there at their real rates.
2. A pitch model, P(ball / strike / foul / in-play-as-X | balls, strikes), also
   empirical, so it captures hitters doing real damage in 3-1 counts and almost
   none in 0-2.
3. A win-expectancy table solved by backward induction over innings with the
   real rules: walk-offs, the home team not batting in the 9th when ahead, and
   the runner-on-second rule in extras.
4. The two normalising constants (per PA and per pitch), weighted by how often
   each state actually came up in 2024.

The app ships (1)-(4) and does the leverage arithmetic live in the browser.
"""

import os
import json
import pickle
from collections import Counter, defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

CATS = ["K", "BB", "HBP", "1B", "2B", "3B", "HR", "OUT", "OTHER"]
NCAT = len(CATS)
I_K, I_BB, I_HBP = CATS.index("K"), CATS.index("BB"), CATS.index("HBP")

DMAX = 15                          # score differentials clamped to +/- 15
NDIFF = 2 * DMAX + 1
NBASE, NOUTS = 8, 3
NCELL = NOUTS * NBASE              # 24 base/out states
MAXRUNS = 4                        # runs on one PA, capped (4 = grand slam)
BASE_NAMES = ["___", "1__", "_2_", "12_", "__3", "1_3", "_23", "123"]
DIFFS = np.arange(-DMAX, DMAX + 1)

COUNTS = [(b, s) for b in range(4) for s in range(3)]


def cell(outs, base):
    return outs * NBASE + base


# ---------------------------------------------------------------------------
# 1. Empirical transition model
# ---------------------------------------------------------------------------
def fallback(base, outs, cat):
    """Deterministic advancement. Used only for state/outcome pairs never seen."""
    occ = [bool(base & 1), bool(base & 2), bool(base & 4)]
    if cat == "HR":
        return (0, outs, min(1 + sum(occ), MAXRUNS), 1.0)
    if cat in ("K", "OUT"):
        return (base, outs + 1, 0, 1.0)
    adv = {"1B": 1, "2B": 2, "3B": 3, "BB": 1, "HBP": 1, "OTHER": 1}[cat]
    new, runs = [False, False, False], 0
    for i in (2, 1, 0):
        if not occ[i]:
            continue
        dest = i + 1 + adv
        if dest > 3:
            runs += 1
        else:
            new[dest - 1] = True
    if adv <= 3:
        new[adv - 1] = True
    nb = (1 if new[0] else 0) | (2 if new[1] else 0) | (4 if new[2] else 0)
    return (nb, outs, min(runs, MAXRUNS), 1.0)


def build_transitions(raw):
    """(base, outs, cat_index) -> list of (new_base, new_outs, runs, prob)."""
    trans, thin, missing = {}, [], []
    for base in range(NBASE):
        for outs in range(NOUTS):
            for ci, cat in enumerate(CATS):
                c = raw["trans"].get((base, outs, cat), Counter())
                n = sum(c.values())
                if n == 0:
                    trans[(base, outs, ci)] = [fallback(base, outs, cat)]
                    missing.append((BASE_NAMES[base], outs, cat))
                    continue
                if n < 25:
                    thin.append((BASE_NAMES[base], outs, cat, n))
                agg = defaultdict(float)
                for (nb, no, r), k in c.items():
                    agg[(nb, min(no, 3), min(r, MAXRUNS))] += k / n
                trans[(base, outs, ci)] = [(k[0], k[1], k[2], v) for k, v in agg.items()]
    return trans, thin, missing


# ---------------------------------------------------------------------------
# 2. Empirical pitch model
# ---------------------------------------------------------------------------
def build_pitch_model(raw):
    """(balls, strikes) -> {ball, strike, foul, hbp, ip: [per-category], n}."""
    pm = {}
    for (b, s) in COUNTS:
        c = raw["pitch"].get((b, s), Counter())
        n = sum(c.values())
        out = {"ball": 0.0, "strike": 0.0, "foul": 0.0, "hbp": 0.0,
               "ip": [0.0] * NCAT, "n": n}
        for k, v in c.items():
            p = v / n
            if k.startswith("ip:"):
                out["ip"][CATS.index(k[3:])] += p
            else:
                out[k] += p
        pm[(b, s)] = out
    return pm


def cat_given_count(pm):
    """P(final PA outcome | count), propagated through the pitch model.

    The 2-strike foul leaves the count unchanged, so it is a self-loop and its
    contribution is summed as a geometric series instead of being iterated.
    """
    res = {}
    for (b, s) in sorted(COUNTS, key=lambda t: -(t[0] + t[1])):
        m = pm[(b, s)]
        v = np.array(m["ip"], dtype=float)
        v[I_HBP] += m["hbp"]
        if b < 3:
            v = v + m["ball"] * res[(b + 1, s)]
        else:
            v[I_BB] += m["ball"]
        if s < 2:
            v = v + (m["strike"] + m["foul"]) * res[(b, s + 1)]
        else:
            v[I_K] += m["strike"]
            v = v / max(1e-12, 1.0 - m["foul"])
        res[(b, s)] = v
    return res


# ---------------------------------------------------------------------------
# 3. Win expectancy
# ---------------------------------------------------------------------------
def shift(a, k):
    """Shift along the differential axis by k runs, clamping at the edges."""
    if k == 0:
        return a
    out = np.empty_like(a)
    if k > 0:
        out[..., k:] = a[..., :-k]
        out[..., :k] = a[..., :1]
    else:
        out[..., :k] = a[..., -k:]
        out[..., k:] = a[..., -1:]
    return out


class WinExpectancy:
    """P(home team wins) for every (inning, half, outs, bases, differential).

    `diff` is always home minus away. `half` is 0 while the visitors bat, 1 while
    the home team bats. Innings 1-9 are stored explicitly; innings 10+ share one
    block solved as a fixed point, because under the runner-on-second rule every
    extra inning looks the same.
    """

    def __init__(self, trans, pcat):
        # Collapse the per-outcome transitions into one distribution per
        # base/out cell, then group by runs scored so a sweep is a few matmuls.
        self.M = [np.zeros((NCELL, NCELL)) for _ in range(MAXRUNS + 1)]   # -> live states
        self.W = [np.zeros(NCELL) for _ in range(MAXRUNS + 1)]            # -> inning over
        for base in range(NBASE):
            for outs in range(NOUTS):
                i = cell(outs, base)
                for ci in range(NCAT):
                    for (nb, no, r, p) in trans[(base, outs, ci)]:
                        w = pcat[ci] * p
                        if no >= 3:
                            self.W[r][i] += w
                        else:
                            self.M[r][i, cell(no, nb)] += w
        self.reg = np.zeros((9, 2, NCELL, NDIFF))
        self.ext = np.zeros((2, NCELL, NDIFF))
        self._solve()

    # -- value once the third out of the half-inning is made, as a function of diff
    def _end_of_half(self, inn, half):
        extras = inn >= 10
        if half == 0:
            nxt = self.ext[1][cell(0, 2)] if extras else self.reg[inn - 1][1][cell(0, 0)]
            if extras or inn >= 9:
                # home already ahead after the top half -> game over
                return np.where(DIFFS > 0, 1.0, nxt)
            return nxt
        if extras or inn >= 9:
            tie = self.ext[0][cell(0, 2), DMAX]     # next extra inning, tied
            return np.where(DIFFS > 0, 1.0, np.where(DIFFS < 0, 0.0, tie))
        return self.reg[inn][0][cell(0, 0)]

    def _sweep(self, block, inn, half):
        end = self._end_of_half(inn, half)
        sgn = 1 if half == 1 else -1
        walkoff = half == 1 and inn >= 9
        acc = np.zeros_like(block)
        for r in range(MAXRUNS + 1):
            # a state at differential d moves to d + sgn*r, so we read the value
            # function shifted the other way
            vb = shift(block, -sgn * r)
            ve = shift(end, -sgn * r)
            if walkoff and r > 0:
                # the home team taking the lead ends the game where it stands
                won = (DIFFS + r) > 0
                vb = np.where(won[None, :], 1.0, vb)
                ve = np.where(won, 1.0, ve)
            acc += self.M[r] @ vb + self.W[r][:, None] * ve[None, :]
        return acc

    def _relax(self, inn, half, iters=400, tol=1e-14):
        block = self.ext[half] if inn >= 10 else self.reg[inn - 1][half]
        for _ in range(iters):
            nxt = self._sweep(block, inn, half)
            d = np.max(np.abs(nxt - block))
            block = nxt
            if d < tol:
                break
        if inn >= 10:
            self.ext[half] = block
        else:
            self.reg[inn - 1][half] = block

    def _solve(self):
        for _ in range(400):                       # extras: fixed point
            prev = self.ext.copy()
            self._relax(10, 1, iters=40)
            self._relax(10, 0, iters=40)
            if np.max(np.abs(self.ext - prev)) < 1e-13:
                break
        for inn in range(9, 0, -1):                # regulation, backwards
            self._relax(inn, 1)
            self._relax(inn, 0)

    def block(self, inn, half):
        return self.ext[half] if inn >= 10 else self.reg[inn - 1][half]

    def value(self, inn, half, outs, base, diff):
        d = max(-DMAX, min(DMAX, diff))
        return float(self.block(inn, half)[cell(outs, base), d + DMAX])

    def next_value(self, inn, half, diff, nb, no, runs):
        """Home win probability after a PA leaving `no` outs, `nb` bases, `runs` in."""
        sgn = 1 if half == 1 else -1
        d = max(-DMAX, min(DMAX, diff + sgn * runs))
        if half == 1 and inn >= 9 and d > 0:
            return 1.0                                       # walk-off
        if no < 3:
            return float(self.block(inn, half)[cell(no, nb), d + DMAX])
        if half == 0:
            if inn >= 9 and d > 0:
                return 1.0                                   # home need not bat
            if inn >= 10:
                return float(self.ext[1][cell(0, 2), d + DMAX])
            if inn == 9:
                return float(self.reg[8][1][cell(0, 0), d + DMAX])
            return float(self.reg[inn - 1][1][cell(0, 0), d + DMAX])
        if inn >= 9:
            if d > 0:
                return 1.0
            if d < 0:
                return 0.0
            return float(self.ext[0][cell(0, 2), DMAX])
        return float(self.reg[inn][0][cell(0, 0), d + DMAX])


# ---------------------------------------------------------------------------
# 4. Leverage
# ---------------------------------------------------------------------------
class Leverage:
    def __init__(self, we, trans, pm, pcat_count):
        self.we = we
        self.trans = trans
        self.pm = pm
        self.pcc = pcat_count

    def state_values(self, inn, half, outs, base, diff):
        """For one state: every reachable post-PA win prob, with its probability.

        Returns (vals, probs) where both are lists indexed by category.
        """
        vals, probs = [], []
        for ci in range(NCAT):
            vv, pp = [], []
            for (nb, no, r, p) in self.trans[(base, outs, ci)]:
                vv.append(self.we.next_value(inn, half, diff, nb, no, r))
                pp.append(p)
            vals.append(np.array(vv))
            probs.append(np.array(pp))
        return vals, probs

    def count_values(self, vals, probs):
        """Win expectancy at each count within the PA, W(count).

        Solved backwards through the count tree; the 2-strike foul self-loop is
        summed as a geometric series.
        """
        vcat = np.array([float(np.dot(v, p)) for v, p in zip(vals, probs)])
        W = {}
        for (b, s) in sorted(COUNTS, key=lambda t: -(t[0] + t[1])):
            m = self.pm[(b, s)]
            x = float(np.dot(np.array(m["ip"]), vcat)) + m["hbp"] * vcat[I_HBP]
            x += m["ball"] * (W[(b + 1, s)] if b < 3 else vcat[I_BB])
            if s < 2:
                x += (m["strike"] + m["foul"]) * W[(b, s + 1)]
            else:
                x += m["strike"] * vcat[I_K]
                x /= max(1e-12, 1.0 - m["foul"])
            W[(b, s)] = x
        return W, vcat

    def swings(self, inn, half, outs, base, diff):
        """Per count: (PA win-swing, pitch win-swing, win expectancy at that count)."""
        vals, probs = self.state_values(inn, half, outs, base, diff)
        W, vcat = self.count_values(vals, probs)
        out = {}
        for (b, s) in COUNTS:
            w0 = W[(b, s)]
            pc = self.pcc[(b, s)]
            # --- swing over the rest of the plate appearance
            pa = 0.0
            for ci in range(NCAT):
                if pc[ci] <= 0:
                    continue
                pa += pc[ci] * float(np.dot(probs[ci], np.abs(vals[ci] - w0)))
            # --- swing over the very next pitch
            m = self.pm[(b, s)]
            pit = 0.0
            if b < 3:
                pit += m["ball"] * abs(W[(b + 1, s)] - w0)
            else:
                pit += m["ball"] * float(np.dot(probs[I_BB], np.abs(vals[I_BB] - w0)))
            if s < 2:
                pit += (m["strike"] + m["foul"]) * abs(W[(b, s + 1)] - w0)
            else:
                pit += m["strike"] * float(np.dot(probs[I_K], np.abs(vals[I_K] - w0)))
                # a 2-strike foul changes nothing, so it contributes zero swing
            pit += m["hbp"] * float(np.dot(probs[I_HBP], np.abs(vals[I_HBP] - w0)))
            for ci in range(NCAT):
                if m["ip"][ci] > 0:
                    pit += m["ip"][ci] * float(np.dot(probs[ci], np.abs(vals[ci] - w0)))
            out[(b, s)] = (pa, pit, w0)
        return out


# ---------------------------------------------------------------------------
# Run expectancy from the model (used to check it against the real 2024 table)
# ---------------------------------------------------------------------------
def model_re24(trans, pcat):
    A = np.zeros((NCELL, NCELL))
    b = np.zeros(NCELL)
    for base in range(NBASE):
        for outs in range(NOUTS):
            i = cell(outs, base)
            for ci in range(NCAT):
                for (nb, no, r, p) in trans[(base, outs, ci)]:
                    w = pcat[ci] * p
                    b[i] += w * r
                    if no < 3:
                        A[i, cell(no, nb)] += w
    return np.linalg.solve(np.eye(NCELL) - A, b)


# ---------------------------------------------------------------------------
def main():
    with open(os.path.join(DATA, "parsed2024.pkl"), "rb") as f:
        raw = pickle.load(f)

    trans, thin, missing = build_transitions(raw)
    pm = build_pitch_model(raw)
    pcc = cat_given_count(pm)
    pcat = pcc[(0, 0)]                      # league PA outcome mix, from the pitch model

    print("=" * 72)
    print("MODEL INPUTS (2024, %d games, %d PA)" % (raw["games"], sum(raw["cat_totals"].values())))
    print("=" * 72)
    if missing:
        print("state/outcome cells never observed (using fallback rule): %d" % len(missing))
        for m in missing[:8]:
            print("   ", m)
    print("cells with < 25 observations: %d of %d" % (len(thin), NBASE * NOUTS * NCAT))

    tot = sum(raw["cat_totals"].values())
    print("\noutcome mix           observed    pitch model")
    for ci, c in enumerate(CATS):
        print("  %-6s %14.4f %14.4f" % (c, raw["cat_totals"][c] / tot, pcat[ci]))

    print("\nP(outcome | count), from the pitch model")
    hdr = "  count   " + "".join("%7s" % c for c in ["K", "BB", "1B", "2B", "HR", "OUT"])
    print(hdr)
    for (b, s) in COUNTS:
        v = pcc[(b, s)]
        print("   %d-%d    " % (b, s) + "".join("%7.3f" % v[CATS.index(c)]
                                                for c in ["K", "BB", "1B", "2B", "HR", "OUT"]))

    # ---- run expectancy check
    re_m = model_re24(trans, pcat)
    print("\n" + "=" * 72)
    print("CHECK 1 -- run expectancy: model vs what actually happened in 2024")
    print("=" * 72)
    print("            0 out           1 out           2 out")
    print("          model   real    model   real    model   real")
    worst = 0.0
    for base in range(NBASE):
        row = "  %s " % BASE_NAMES[base]
        for outs in range(NOUTS):
            n = raw["re_n"][(base, outs)]
            real = raw["re_runs"][(base, outs)] / n if n else float("nan")
            mv = re_m[cell(outs, base)]
            worst = max(worst, abs(mv - real))
            row += "   %5.3f  %5.3f" % (mv, real)
        print(row)
    print("  largest gap: %.3f runs" % worst)
    print("  runs per team per 9 innings: model %.2f" % (9 * re_m[cell(0, 0)]))

    # ---- win expectancy
    we = WinExpectancy(trans, pcat)
    lev = Leverage(we, trans, pm, pcc)

    print("\n" + "=" * 72)
    print("CHECK 2 -- win expectancy sanity")
    print("=" * 72)
    print("  home team, start of game (0-0, top 1st, nobody on):  %.4f" % we.value(1, 0, 0, 0, 0))
    print("  2024 actual home winning percentage:                 %.4f"
          % (raw.get("home_wins", 0) / max(1, raw["games"]) if raw.get("home_wins") else float("nan")))
    for (label, args) in [
        ("bottom 9th, tied, bases empty, 0 out", (9, 1, 0, 0, 0)),
        ("bottom 9th, down 1, bases empty, 0 out", (9, 1, 0, 0, -1)),
        ("bottom 9th, down 3, bases empty, 0 out", (9, 1, 0, 0, -3)),
        ("top 10th, tied, runner on 2nd, 0 out", (10, 0, 0, 2, 0)),
        ("top 1st, home up 1", (1, 0, 0, 0, 1)),
    ]:
        print("  %-40s %.4f" % (label, we.value(*args)))

    # ---- leverage normalisers, weighted by 2024 state frequencies
    print("\n" + "=" * 72)
    print("CHECK 3 -- leverage normalisers")
    print("=" * 72)
    cache = {}

    def sw(inn, half, outs, base, diff):
        k = (inn, half, outs, base, diff)
        if k not in cache:
            cache[k] = lev.swings(*k)
        return cache[k]

    num_pa = den_pa = 0.0
    for (inn, half, outs, base, diff), n in raw["pa_states"].items():
        num_pa += n * sw(inn, half, outs, base, diff)[(0, 0)][0]
        den_pa += n
    denom_pa = num_pa / den_pa

    num_p = den_p = 0.0
    for (inn, half, outs, base, diff, b, s), n in raw["pitch_states"].items():
        num_p += n * sw(inn, half, outs, base, diff)[(b, s)][1]
        den_p += n
    denom_pitch = num_p / den_p

    print("  mean |win-prob swing| per plate appearance: %.5f  (%d PA)" % (denom_pa, den_pa))
    print("     -> the constant usually quoted for this is ~0.0346")
    print("  mean |win-prob swing| per pitch:            %.5f  (%d pitches)" % (denom_pitch, den_p))

    print("\n" + "=" * 72)
    print("CHECK 3b -- where leverage peaks, and how leverage is distributed")
    print("=" * 72)
    best = []
    for inn in range(1, 11):
        for half in (0, 1):
            for outs in range(3):
                for base in range(8):
                    for diff in range(-4, 5):
                        li = sw(inn, half, outs, base, diff)[(0, 0)][0] / denom_pa
                        best.append((li, inn, half, outs, base, diff))
    best.sort(reverse=True)
    print("  highest-leverage plate appearances in the model:")
    for (li, inn, half, outs, base, diff) in best[:6]:
        print("    LI %5.2f  %s %d%s, %s, %d out, batting team %+d"
              % (li, "top" if half == 0 else "bot", inn, "+" if inn >= 10 else "",
                 BASE_NAMES[base], outs, diff if half == 1 else -diff))
    buckets = Counter()
    for (inn, half, outs, base, diff), n in raw["pa_states"].items():
        li = sw(inn, half, outs, base, diff)[(0, 0)][0] / denom_pa
        buckets["high (>1.5)" if li > 1.5 else
                "medium (0.85-1.5)" if li >= 0.85 else "low (<0.85)"] += n
    tot_pa = sum(buckets.values())
    print("  share of 2024 plate appearances by leverage bucket:")
    for k in ["high (>1.5)", "medium (0.85-1.5)", "low (<0.85)"]:
        print("    %-20s %5.1f%%" % (k, 100.0 * buckets[k] / tot_pa))
    print("    (0.85 / 1.5 are the conventional low/medium/high cut points)")

    print("\n" + "=" * 72)
    print("CHECK 4 -- leverage index at states with known published values")
    print("=" * 72)
    ref = [
        ("start of game, top 1st, 0-0", (1, 0, 0, 0, 0)),
        ("bot 9th, tied, bases loaded, 2 out", (9, 1, 2, 7, 0)),
        ("bot 9th, tied, bases loaded, 0 out", (9, 1, 0, 7, 0)),
        ("bot 9th, down 1, runner on 1st, 2 out", (9, 1, 2, 1, -1)),
        ("bot 9th, up 3, bases empty, 0 out", (9, 1, 0, 0, 3)),
        ("top 1st, bases empty, 2 out, 0-0", (1, 0, 2, 0, 0)),
        ("bot 8th, down 1, runners on 1&2, 1 out", (8, 1, 1, 3, -1)),
        ("bot 9th, down 1, bases loaded, 2 out", (9, 1, 2, 7, -1)),
        ("bot 9th, down 1, bases loaded, 1 out", (9, 1, 1, 7, -1)),
        ("top 3rd, up 8, bases empty, 1 out", (3, 0, 1, 0, 8)),
    ]
    for label, st in ref:
        s00 = sw(*st)[(0, 0)]
        print("  %-40s LI %6.2f   (WE %.3f)" % (label, s00[0] / denom_pa, s00[2]))

    print("\n  same at-bat, walked through the count "
          "(bot 9th, tied, runners on 1st & 2nd, 1 out):")
    st = (9, 1, 1, 3, 0)
    allc = sw(*st)
    print("     count   WE(home)   AB leverage   pitch leverage")
    for (b, s) in COUNTS:
        pa, pit, w = allc[(b, s)]
        print("      %d-%d      %.3f       %6.2f          %6.2f"
              % (b, s, w, pa / denom_pa, pit / denom_pitch))

    # ---- export
    out = {
        "meta": {
            "season": 2024,
            "games": raw["games"],
            "gamesTotal": raw["games"] + len(raw["bad_games"]),
            "plateAppearances": int(sum(raw["cat_totals"].values())),
            "source": "Retrosheet 2024 event files",
            "denomPA": denom_pa,
            "denomPitch": denom_pitch,
            "re24": [round(float(re_m[cell(o, b)]), 4) for o in range(NOUTS) for b in range(NBASE)],
        },
        "cats": CATS,
        "trans": {},
        "pitch": {},
        "catAtCount": {},
        "we": [round(float(x), 5) for x in we.reg.reshape(-1)],
        "weX": [round(float(x), 5) for x in we.ext.reshape(-1)],
    }
    for (base, outs, ci), lst in trans.items():
        out["trans"]["%d,%d,%d" % (base, outs, ci)] = [
            [nb, no, r, round(p, 6)] for (nb, no, r, p) in lst if p > 1e-9
        ]
    for (b, s) in COUNTS:
        m = pm[(b, s)]
        out["pitch"]["%d%d" % (b, s)] = {
            "ball": round(m["ball"], 6), "strike": round(m["strike"], 6),
            "foul": round(m["foul"], 6), "hbp": round(m["hbp"], 6),
            "ip": [round(x, 6) for x in m["ip"]], "n": m["n"],
        }
        out["catAtCount"]["%d%d" % (b, s)] = [round(float(x), 6) for x in pcc[(b, s)]]

    # reference values so the browser build can check itself against this run
    out["selftest"] = []
    for label, st in ref:
        s00 = sw(*st)[(0, 0)]
        out["selftest"].append({
            "state": list(st), "count": [0, 0],
            "we": round(s00[2], 5), "li": round(s00[0] / denom_pa, 4),
            "pli": round(sw(*st)[(0, 0)][1] / denom_pitch, 4),
        })
    count_state = (9, 1, 1, 3, 0)      # the at-bat walked through the count, above
    for (b, s) in [(0, 0), (3, 1), (0, 2), (3, 2)]:
        v = allc[(b, s)]
        out["selftest"].append({
            "state": list(count_state), "count": [b, s],
            "we": round(v[2], 5), "li": round(v[0] / denom_pa, 4),
            "pli": round(v[1] / denom_pitch, 4),
        })

    path = os.path.join(HERE, "model.json")
    with open(path, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    jspath = os.path.join(HERE, "model.js")
    with open(jspath, "w") as f:
        f.write("// Generated by build_model.py -- 2024 Retrosheet play-by-play.\n")
        f.write("window.LI_MODEL=")
        json.dump(out, f, separators=(",", ":"))
        f.write(";\n")
    print("\nwrote %s (%.0f KB)" % (path, os.path.getsize(path) / 1024))
    print("wrote %s (%.0f KB)" % (jspath, os.path.getsize(jspath) / 1024))


if __name__ == "__main__":
    main()
