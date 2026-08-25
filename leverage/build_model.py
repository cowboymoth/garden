"""
Build the Leverage Index model and export it for the web app.

WHAT LEVERAGE INDEX IS
----------------------
Tom Tango's Leverage Index asks how much a moment can swing the game:

    LI(S) = E| change in win expectancy over the next plate appearance |
            ------------------------------------------------------------
            the same quantity averaged over every plate appearance

LI = 1.00 is a perfectly average moment.

WHERE EACH PIECE COMES FROM
---------------------------
The rule here is: if somebody has already measured it, read their matrix rather
than deriving our own.

  win expectancy      PULLED. Greg Stoll's published table, computed from
  (per game state,    Retrosheet play-by-play over 195,573 major-league games --
   and per count)     33.6 million observed situations. See external_tables.py.

  run expectancy      PULLED. Their observed runs-to-end-of-inning distribution
                      per base/out state, 15.5 million observations.

  plate-appearance    MEASURED HERE, because no published matrix of it exists in
  outcomes, and how   usable form: the 2024 Retrosheet season, parsed pitch by
  the bases move      pitch. P(new base/out state, runs | state, outcome) and
                      P(ball / strike / foul / in play as X | count).

  the two normalising MEASURED HERE, from 2024 state frequencies.
  constants

The only place a model of our own still enters is as a *prior*: the published
tables are thin in rare corners (20-run leads, the 14th inning), so each cell is
shrunk from its observed rate toward a structural win-expectancy model according
to its own sample size. Common states end up almost entirely observed data. The
build prints how much weight the data carries and how far the prior sits from
the observations.
"""

import os
import json
import base64
import pickle
from collections import Counter, defaultdict

import numpy as np

import external_tables as EXTT

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

CATS = ["K", "BB", "HBP", "1B", "2B", "3B", "HR", "OUT", "OTHER"]
NCAT = len(CATS)
I_K, I_BB, I_HBP = CATS.index("K"), CATS.index("BB"), CATS.index("HBP")

DMAX = 15                          # score differentials clamped to +/- 15
NDIFF = 2 * DMAX + 1
DMAXC = 8                          # the by-count table ships for +/- 8 runs
NDIFFC = 2 * DMAXC + 1
NBASE, NOUTS = 8, 3
NCELL = NOUTS * NBASE
NINN = 10                          # innings 1-9, plus one pooled extra-innings slot
MAXRUNS = 4
BASE_NAMES = ["___", "1__", "_2_", "12_", "__3", "1_3", "_23", "123"]
DIFFS = np.arange(-DMAX, DMAX + 1)
COUNTS = [(b, s) for b in range(4) for s in range(3)]


def cell(outs, base):
    return outs * NBASE + base


def iinn(inn):
    """Inning -> table slot. 1-9 are themselves; 10+ share the extras slot."""
    return min(inn, NINN) - 1


# ---------------------------------------------------------------------------
# Outcomes: measured from the 2024 season
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
    """P(final PA outcome | count), propagated through the pitch model."""
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
# The structural prior -- our own model, used ONLY to shore up thin cells
# ---------------------------------------------------------------------------
def shift(a, k):
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


class PriorWinExpectancy:
    """A neutral-teams win-expectancy model, solved by backward induction.

    This is not what the app reports. It exists so that game states the
    published table barely ever saw still get a sensible number, and so we can
    measure how good the published table's coverage is.
    """

    def __init__(self, trans, pcat):
        self.M = [np.zeros((NCELL, NCELL)) for _ in range(MAXRUNS + 1)]
        self.W = [np.zeros(NCELL) for _ in range(MAXRUNS + 1)]
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

    def _end_of_half(self, inn, half):
        extras = inn >= 10
        if half == 0:
            nxt = self.ext[1][cell(0, 2)] if extras else self.reg[inn - 1][1][cell(0, 0)]
            if extras or inn >= 9:
                return np.where(DIFFS > 0, 1.0, nxt)
            return nxt
        if extras or inn >= 9:
            tie = self.ext[0][cell(0, 2), DMAX]
            return np.where(DIFFS > 0, 1.0, np.where(DIFFS < 0, 0.0, tie))
        return self.reg[inn][0][cell(0, 0)]

    def _sweep(self, block, inn, half):
        end = self._end_of_half(inn, half)
        sgn = 1 if half == 1 else -1
        walkoff = half == 1 and inn >= 9
        acc = np.zeros_like(block)
        for r in range(MAXRUNS + 1):
            vb = shift(block, -sgn * r)
            ve = shift(end, -sgn * r)
            if walkoff and r > 0:
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
        for _ in range(400):
            prev = self.ext.copy()
            self._relax(10, 1, iters=40)
            self._relax(10, 0, iters=40)
            if np.max(np.abs(self.ext - prev)) < 1e-13:
                break
        for inn in range(9, 0, -1):
            self._relax(inn, 1)
            self._relax(inn, 0)

    def grid(self):
        """-> array (NINN, 2, 3, 8, NDIFF) of P(home wins)."""
        g = np.zeros((NINN, 2, NOUTS, NBASE, NDIFF))
        for inn in range(1, NINN + 1):
            blk = self.ext if inn >= 10 else self.reg[inn - 1]
            for half in range(2):
                for o in range(NOUTS):
                    for b in range(NBASE):
                        g[iinn(inn), half, o, b] = blk[half][cell(o, b)]
        return g


def model_re24(trans, pcat):
    """Expected runs to the end of the half-inning, from the 2024 outcomes."""
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
# Win expectancy as read from the published table
# ---------------------------------------------------------------------------
def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def fit_prior_shift(obs, n, prior, floor=5000):
    """One-parameter recalibration of the prior toward the observed table.

    The structural model assumes two league-average teams and no home-field
    edge; the real table has one. A single shift on the log-odds scale absorbs
    most of the difference. Returns (shift, rms_before, rms_after).
    """
    m = (n >= floor) & ~np.isnan(obs)
    before = float(np.sqrt((((obs - prior)[m]) ** 2).mean()))
    best = (0.0, before)
    for a in np.arange(-0.5, 0.5, 0.002):
        r = float(np.sqrt((((obs - sigmoid(logit(prior) + a))[m]) ** 2).mean()))
        if r < best[1]:
            best = (float(a), r)
    return best[0], before, best[1]


class TableWE:
    """P(home team wins), read from the published table.

    `W` has shape (NINN, 2, 3, 8, NDIFF, 4, 3): the observed win rate in each
    game state and count, shrunk toward the structural prior by sample size.
    `N` is how many real situations each cell was measured from.
    """

    def __init__(self, W, N, ext_entry):
        self.W, self.N = W, N
        self.ext = ext_entry          # observed value on reaching extras, by diff

    def value(self, inn, half, outs, base, diff, b=0, s=0):
        d = max(-DMAX, min(DMAX, diff))
        return float(self.W[iinn(inn), half, outs, base, d + DMAX, b, s])

    def observations(self, inn, half, outs, base, diff, b=0, s=0):
        d = max(-DMAX, min(DMAX, diff))
        return float(self.N[iinn(inn), half, outs, base, d + DMAX, b, s])

    def next_value(self, inn, half, diff, nb, no, runs):
        """Win probability after a PA leaving `no` outs, `nb` bases, `runs` in.

        The branching here is the rules of baseball, not a model: a half-inning
        ends after three outs, the home team stops playing once ahead in the
        ninth, and a run that puts them ahead there ends it on the spot.
        """
        sgn = 1 if half == 1 else -1
        d = max(-DMAX, min(DMAX, diff + sgn * runs))
        if half == 1 and inn >= 9 and d > 0:
            return 1.0                                   # walk-off
        if no < 3:
            return self.value(inn, half, no, nb, d)
        if half == 0:
            if inn >= 9 and d > 0:
                return 1.0                               # home need not bat
            if inn >= 10:
                return float(self.ext[1][d + DMAX])
            return self.value(inn, 1, 0, 0, d)
        if inn >= 9:
            if d > 0:
                return 1.0
            if d < 0:
                return 0.0
            return float(self.ext[0][DMAX])              # tied, on to extras
        return self.value(inn + 1, 0, 0, 0, d)


# ---------------------------------------------------------------------------
# Leverage
# ---------------------------------------------------------------------------
class Leverage:
    def __init__(self, we, trans, pm, pcc):
        self.we, self.trans, self.pm, self.pcc = we, trans, pm, pcc

    def state_values(self, inn, half, outs, base, diff):
        """Every reachable post-PA win probability, grouped by outcome."""
        vals, probs = [], []
        for ci in range(NCAT):
            vv, pp = [], []
            for (nb, no, r, p) in self.trans[(base, outs, ci)]:
                vv.append(self.we.next_value(inn, half, diff, nb, no, r))
                pp.append(p)
            vals.append(np.array(vv))
            probs.append(np.array(pp))
        return vals, probs

    def count_recursion(self, vals, probs):
        """Win expectancy at each count, worked backwards through the count tree.

        Used only to build the prior for the published by-count table.
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
        return W

    def swings(self, inn, half, outs, base, diff):
        """Per count: (PA win-swing, pitch win-swing, win expectancy)."""
        vals, probs = self.state_values(inn, half, outs, base, diff)
        out = {}
        for (b, s) in COUNTS:
            w0 = self.we.value(inn, half, outs, base, diff, b, s)
            pc = self.pcc[(b, s)]

            def cat_swing(c):
                return float(np.dot(probs[c], np.abs(vals[c] - w0)))

            pa = 0.0
            for ci in range(NCAT):
                if pc[ci] > 0:
                    pa += pc[ci] * cat_swing(ci)

            m = self.pm[(b, s)]
            pit = (m["ball"] * abs(self.we.value(inn, half, outs, base, diff, b + 1, s) - w0)
                   if b < 3 else m["ball"] * cat_swing(I_BB))
            if s < 2:
                pit += (m["strike"] + m["foul"]) * abs(
                    self.we.value(inn, half, outs, base, diff, b, s + 1) - w0)
            else:
                pit += m["strike"] * cat_swing(I_K)   # a 2-strike foul changes nothing
            pit += m["hbp"] * cat_swing(I_HBP)
            for ci in range(NCAT):
                if m["ip"][ci] > 0:
                    pit += m["ip"][ci] * cat_swing(ci)
            out[(b, s)] = (pa, pit, w0)
        return out


class RecursionWE(TableWE):
    """Win expectancy from a state-level table, with counts filled in by the
    count recursion rather than by an observed by-count table.

    Used for the neutral-teams view, where there is no observed table to read.
    """

    def __init__(self, grid, N, ext_entry, trans, pm, pcc):
        flat = np.repeat(grid[..., None, None], 4, axis=-2).repeat(3, axis=-1)
        TableWE.__init__(self, flat, N, ext_entry)
        self._lev = Leverage(TableWE(flat, N, ext_entry), trans, pm, pcc)
        self._cache = {}

    def value(self, inn, half, outs, base, diff, b=0, s=0):
        if b == 0 and s == 0:
            return TableWE.value(self, inn, half, outs, base, diff)
        k = (inn, half, outs, base, max(-DMAX, min(DMAX, diff)))
        if k not in self._cache:
            v, p = self._lev.state_values(*k)
            W = self._lev.count_recursion(v, p)
            anchor = TableWE.value(self, *k) - W[(0, 0)]
            self._cache[k] = {c: min(1.0, max(0.0, W[c] + anchor)) for c in COUNTS}
        return self._cache[k][(b, s)]


def b64u16(a):
    return base64.b64encode(np.clip(np.round(a), 0, 65535)
                            .astype("<u2").tobytes()).decode("ascii")


# ---------------------------------------------------------------------------
def main():
    if not EXTT.available():
        raise SystemExit("external tables missing -- run ./fetch_data.sh first")
    with open(os.path.join(DATA, "parsed2024.pkl"), "rb") as f:
        raw = pickle.load(f)

    trans, thin, missing = build_transitions(raw)
    pm = build_pitch_model(raw)
    pcc = cat_given_count(pm)
    pcat = pcc[(0, 0)]

    print("=" * 74)
    print("OUTCOMES -- measured here, from 2024 (%d games, %d PA)"
          % (raw["games"], sum(raw["cat_totals"].values())))
    print("=" * 74)
    print("  state/outcome cells never observed (deterministic fallback): %d of %d"
          % (len(missing), NBASE * NOUTS * NCAT))
    tot = sum(raw["cat_totals"].values())
    print("  outcome mix: " + " ".join("%s %.3f" % (c, raw["cat_totals"][c] / tot)
                                       for c in CATS))

    obs, obsN, kept, skipped = EXTT.load_win_expectancy()
    re_mean, re_dist, re_n = EXTT.load_run_expectancy()
    pub_li = EXTT.load_published_leverage()

    print("\n" + "=" * 74)
    print("WIN EXPECTANCY -- pulled from a published table, not derived here")
    print("=" * 74)
    print("  source: gregstoll/baseballstats, measured from Retrosheet play-by-play")
    print("  observed situations read in: %s  (%s fell outside our grid)"
          % ("{:,}".format(kept), "{:,}".format(skipped)))
    print("  games behind it: %s" % "{:,}".format(int(obsN[0, 0, 0, 0, DMAX, 0, 0])))
    print("  observed home win rate at the first pitch of a game: %.4f"
          % obs[0, 0, 0, 0, DMAX, 0, 0])

    prior_model = PriorWinExpectancy(trans, pcat)
    prior0 = prior_model.grid()
    o0, n0 = obs[..., 0, 0], obsN[..., 0, 0]
    a, rms_before, rms_after = fit_prior_shift(o0, n0, prior0)
    prior0 = np.clip(sigmoid(logit(prior0) + a), 0.0, 1.0)
    K = 0.25 / max(rms_after, 1e-9) ** 2

    print("\n  our structural model, scored against the observed table:")
    print("    as built            rms %.4f  (it assumes no home-field edge)" % rms_before)
    print("    after a %+0.3f log-odds recalibration   rms %.4f" % (a, rms_after))
    print("    -> as a prior it is worth %.0f observed situations, so a cell with" % K)
    for nn in (500, 5000, 30000):
        print("       N = %-6d is %4.1f%% observed data" % (nn, 100 * nn / (nn + K)))

    blend0 = np.where(np.isnan(o0), prior0,
                      (np.nan_to_num(o0) * n0 + K * prior0) / (n0 + K))

    # Observed win expectancy on actually reaching extra innings, pooled over
    # however those innings happened to start -- so no assumption is needed
    # about which extra-innings rule was in force.
    ext_entry = np.zeros((2, NDIFF))
    for half in (0, 1):
        w = obsN[NINN - 1, half, 0, :, :, 0, 0]
        v = np.nan_to_num(obs[NINN - 1, half, 0, :, :, 0, 0])
        ext_entry[half] = (w * v).sum(0) / np.maximum(w.sum(0), 1e-9)

    # --- by-count table. Prior for a count cell is the count recursion, anchored
    # so its 0-0 value is exactly the blended 0-0 number the app will show.
    flat0 = np.repeat(blend0[..., None, None], 4, axis=-2).repeat(3, axis=-1)
    lev_tmp = Leverage(TableWE(flat0, obsN, ext_entry), trans, pm, pcc)
    priorC = flat0.copy()
    for inn in range(1, NINN + 1):
        for half in range(2):
            for o in range(NOUTS):
                for base in range(NBASE):
                    for d in range(-DMAXC, DMAXC + 1):
                        v, p = lev_tmp.state_values(inn, half, o, base, d)
                        W = lev_tmp.count_recursion(v, p)
                        anchor = blend0[iinn(inn), half, o, base, d + DMAX] - W[(0, 0)]
                        for (b, s) in COUNTS:
                            priorC[iinn(inn), half, o, base, d + DMAX, b, s] = \
                                min(1.0, max(0.0, W[(b, s)] + anchor))

    mC = (obsN >= 500) & ~np.isnan(obs)
    resid, wts = (obs - priorC)[mC], obsN[mC]
    rmsC = float(np.sqrt((resid ** 2 * wts).sum() / wts.sum()))
    KC = 0.25 / max(rmsC, 1e-9) ** 2
    print("\n  by-count table (%s observed pitches):" % "{:,}".format(kept))
    print("    our count recursion vs the observed cells: bias %+0.4f  rms %.4f"
          % (float((resid * wts).sum() / wts.sum()), rmsC))
    print("    -> count prior is worth %.0f situations" % KC)

    blendC = np.where(np.isnan(obs), priorC,
                      (np.nan_to_num(obs) * obsN + KC * priorC) / (obsN + KC))
    blendC += (blend0[..., None, None] - blendC[..., 0:1, 0:1])   # keep 0-0 exact
    blendC = np.clip(blendC, 0.0, 1.0)

    we = TableWE(blendC, obsN, ext_entry)
    lev = Leverage(we, trans, pm, pcc)

    # ---- run expectancy: published observations vs our 2024 outcomes
    re_m = model_re24(trans, pcat)
    print("\n" + "=" * 74)
    print("CHECK -- run expectancy: the published observed table vs our 2024 outcomes")
    print("=" * 74)
    print("            0 out           1 out           2 out")
    print("          pub'd   2024    pub'd   2024    pub'd   2024")
    worst = 0.0
    for base in range(NBASE):
        row = "  %s " % BASE_NAMES[base]
        for outs in range(NOUTS):
            pubv, mv = re_mean[outs, base], re_m[cell(outs, base)]
            worst = max(worst, abs(mv - pubv))
            row += "   %5.3f  %5.3f" % (pubv, mv)
        print(row)
    print("  largest gap %.3f runs. The published table spans many decades of a"
          % worst)
    print("  higher-offence game; ours is 2024 alone, so most of that is era.")

    # ---- leverage
    cache = {}

    def sw(inn, half, outs, base, diff):
        k = (inn, half, outs, base, diff)
        if k not in cache:
            cache[k] = lev.swings(*k)
        return cache[k]

    num = den = 0.0
    for (inn, half, outs, base, diff), n in raw["pa_states"].items():
        num += n * sw(inn, half, outs, base, diff)[(0, 0)][0]
        den += n
    denom_pa = num / den
    num = denp = 0.0
    for (inn, half, outs, base, diff, b, s), n in raw["pitch_states"].items():
        num += n * sw(inn, half, outs, base, diff)[(b, s)][1]
        denp += n
    denom_pitch = num / denp

    print("\n" + "=" * 74)
    print("LEVERAGE")
    print("=" * 74)
    print("  mean |win-prob swing| per plate appearance: %.5f" % denom_pa)
    print("     -> the constant usually quoted for this is ~0.0346")
    print("  mean |win-prob swing| per pitch:            %.5f" % denom_pitch)

    pairs = []
    for (half, inn, outs, base, d), theirs in pub_li.items():
        if inn > NINN or abs(d) > 6 or outs > 2:
            continue
        if obsN[iinn(inn), half, outs, base, d + DMAX, 0, 0] < 2000:
            continue
        pairs.append((sw(inn, half, outs, base, d)[(0, 0)][0] / denom_pa, theirs))
    A = np.array([p[0] for p in pairs])
    B = np.array([p[1] for p in pairs])
    print("\n  our LI vs the published leverage column, on well-sampled states:")
    print("    %d states   correlation %.4f   mean ours %.3f vs theirs %.3f"
          % (len(A), float(np.corrcoef(A, B)[0, 1]), A.mean(), B.mean()))
    print("    (theirs approximates a plate appearance as 3% HR / 27% hit / 70% out,")
    print("     with no walk at all, so it understates spots where a walk matters.)")

    # The published table is measured over real, unequal teams, so its win
    # expectancy falls off faster with the score than a two-average-teams model
    # does (clubs that are behind really are more often the weaker club). That
    # lifts leverage early in a game. Quantify it rather than hiding it.
    neutral = Leverage(RecursionWE(prior0, obsN, ext_entry, trans, pm, pcc),
                       trans, pm, pcc)
    ncache = {}

    def nsw(k):
        if k not in ncache:
            ncache[k] = neutral.swings(*k)
        return ncache[k]

    nn = nd = 0.0
    for k, n in raw["pa_states"].items():
        nn += n * nsw(k)[(0, 0)][0]
        nd += n
    denom_neutral = nn / nd
    nn = ndp = 0.0
    for (inn, half, outs, base, diff, b, s), n in raw["pitch_states"].items():
        nn += n * nsw((inn, half, outs, base, diff))[(b, s)][1]
        ndp += n
    denom_neutral_pitch = nn / ndp
    print("\n  the same leverage arithmetic on a neutral-teams model instead of the")
    print("  observed table: mean swing %.5f per PA, %.5f per pitch"
          % (denom_neutral, denom_neutral_pitch))
    print("  (observed table: %.5f and %.5f)." % (denom_pa, denom_pitch))

    ref = [
        ("start of game, top 1st", (1, 0, 0, 0, 0)),
        ("bot 9th, tied, bases loaded, 2 out", (9, 1, 2, 7, 0)),
        ("bot 9th, down 1, bases loaded, 2 out", (9, 1, 2, 7, -1)),
        ("bot 9th, down 1, runner on 1st, 2 out", (9, 1, 2, 1, -1)),
        ("bot 8th, down 1, runners on 1&2, 1 out", (8, 1, 1, 3, -1)),
        ("top 1st, bases empty, 2 out", (1, 0, 2, 0, 0)),
        ("top 3rd, up 8, bases empty, 1 out", (3, 0, 1, 0, 8)),
    ]
    print("\n  %-40s %7s %7s %8s %8s %10s"
          % ("", "our LI", "neutral", "theirs", "WE", "observed N"))
    for label, st in ref:
        pa, pit, w = sw(*st)[(0, 0)]
        theirs = pub_li.get((st[1], st[0], st[2], st[3], st[4]))
        print("  %-40s %7.2f %7.2f %7s %8.3f %10s"
              % (label, pa / denom_pa, nsw(st)[(0, 0)][0] / denom_neutral,
                 ("%.2f" % theirs) if theirs is not None else "--",
                 w, "{:,}".format(int(we.observations(*st)))))
    print("  'neutral' is the same computation on a two-average-teams model. The")
    print("  gap is real teams: an early deficit predicts a loss a bit more strongly")
    print("  than equal-teams maths says, which lifts early-game leverage.")

    st = (9, 1, 1, 3, 0)
    allc = sw(*st)
    print("\n  one at-bat through the count (bot 9th, tied, 1st & 2nd, 1 out):")
    print("     count   WE(home)   AB leverage   pitch leverage   observed N")
    for (b, s) in COUNTS:
        pa, pit, w = allc[(b, s)]
        print("      %d-%d      %.3f       %6.2f          %6.2f    %11s"
              % (b, s, w, pa / denom_pa, pit / denom_pitch,
                 "{:,}".format(int(we.observations(*st, b, s)))))

    wt = 0.0
    for (inn, half, outs, base, diff, b, s), n in raw["pitch_states"].items():
        nn = we.observations(inn, half, outs, base, diff, b, s)
        wt += n * nn / (nn + KC)
    share = wt / denp
    wt0 = 0.0
    for (inn, half, outs, base, diff), n in raw["pa_states"].items():
        nn = we.observations(inn, half, outs, base, diff)
        wt0 += n * nn / (nn + K)
    share0 = wt0 / den
    print("\n  Weighted by how often states actually came up in 2024, the win")
    print("  expectancy this app reports is:")
    print("    at the state level (what drives at-bat leverage)  %.1f%% observed data"
          % (100 * share0))
    print("    at the count level (what drives pitch leverage)   %.1f%% observed data"
          % (100 * share))

    # ---- export
    weC = blendC[:, :, :, :, DMAX - DMAXC: DMAX + DMAXC + 1, :, :]
    out = {
        "meta": {
            "season2024Games": raw["games"],
            "season2024PA": int(sum(raw["cat_totals"].values())),
            "weGames": int(obsN[0, 0, 0, 0, DMAX, 0, 0]),
            "weSituations": int(kept),
            "denomPA": denom_pa,
            "denomPitch": denom_pitch,
            "priorWeight": K,
            "priorWeightCount": KC,
            "observedShare": share0,
            "observedShareCount": share,
            "denomNeutralPA": denom_neutral,
            "denomNeutralPitch": denom_neutral_pitch,
            "reObserved": [round(float(re_mean[o, b]), 4)
                           for o in range(NOUTS) for b in range(NBASE)],
        },
        "cats": CATS,
        "dmax": DMAX, "dmaxc": DMAXC, "ninn": NINN,
        "trans": {}, "pitch": {}, "catAtCount": {},
        "we0": b64u16(blend0.reshape(-1) * 10000.0),      # win prob in basis points
        "weC": b64u16(weC.reshape(-1) * 10000.0),
        "we0n": b64u16(prior0.reshape(-1) * 10000.0),   # neutral-teams variant
        "obsN": b64u16(np.minimum(obsN[..., 0, 0].reshape(-1) / 4.0, 65535)),
        "extEntry": [round(float(x), 5) for x in ext_entry.reshape(-1)],
    }
    for (base, outs, ci), lst in trans.items():
        out["trans"]["%d,%d,%d" % (base, outs, ci)] = [
            [nb, no, r, round(p, 6)] for (nb, no, r, p) in lst if p > 1e-9]
    for (b, s) in COUNTS:
        m = pm[(b, s)]
        out["pitch"]["%d%d" % (b, s)] = {
            "ball": round(m["ball"], 6), "strike": round(m["strike"], 6),
            "foul": round(m["foul"], 6), "hbp": round(m["hbp"], 6),
            "ip": [round(x, 6) for x in m["ip"]], "n": m["n"]}
        out["catAtCount"]["%d%d" % (b, s)] = [round(float(x), 6) for x in pcc[(b, s)]]

    out["selftest"] = []
    for label, s0 in ref:
        pa, pit, w = sw(*s0)[(0, 0)]
        out["selftest"].append({"state": list(s0), "count": [0, 0], "mode": "obs",
                                "we": round(w, 5), "li": round(pa / denom_pa, 4),
                                "pli": round(pit / denom_pitch, 4)})
        npa, npit, nw = nsw(s0)[(0, 0)]
        out["selftest"].append({"state": list(s0), "count": [0, 0], "mode": "neu",
                                "we": round(nw, 5), "li": round(npa / denom_neutral, 4),
                                "pli": round(npit / denom_neutral_pitch, 4)})
    for (b, s) in [(0, 0), (3, 1), (0, 2), (3, 2)]:
        pa, pit, w = allc[(b, s)]
        out["selftest"].append({"state": list(st), "count": [b, s], "mode": "obs",
                                "we": round(w, 5), "li": round(pa / denom_pa, 4),
                                "pli": round(pit / denom_pitch, 4)})

    with open(os.path.join(HERE, "model.json"), "w") as f:
        json.dump(out, f, separators=(",", ":"))
    js = os.path.join(HERE, "model.js")
    with open(js, "w") as f:
        f.write("// Generated by build_model.py. Win expectancy is Greg Stoll's published\n"
                "// Retrosheet table; plate-appearance outcomes are 2024. See README.md.\n")
        f.write("window.LI_MODEL=")
        json.dump(out, f, separators=(",", ":"))
        f.write(";\n")
    print("\nwrote model.json / model.js (%.0f KB)" % (os.path.getsize(js) / 1024))


if __name__ == "__main__":
    main()
