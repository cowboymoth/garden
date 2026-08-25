"""
Load the published, externally-measured tables this project is built on.

The point of this module: win expectancy is not something we should be deriving
ourselves when somebody has already measured it off 195,573 real major-league
games. Everything here is somebody else's published matrix, read as-is.

Source: https://github.com/gregstoll/baseballstats  (Greg Stoll's Win Expectancy
Finder), computed from Retrosheet play-by-play. Retrosheet's data is free of
charge and copyrighted by Retrosheet, 20 Sunset Rd., Newark, DE 19711.

Files used
----------
probswithballsstrikes.txt
    "H"/"V", inning, outs, bases(1-8), run differential, balls, strikes,
    situations, wins
    -- the batting team's observed win rate in every game state, split by count.
    33.6 million observed situations. The balls=0,strikes=0 rows are exactly the
    plain probs.txt table, so this one file covers both.

runsperinningstats
    (outs, (on1st, on2nd, on3rd)): [how many times 0 runs, 1 run, 2 runs, ...
    scored in the rest of the inning]
    -- an observed run-expectancy matrix, as a full distribution rather than
    just a mean.

linescores.raw
    Retrosheet box-score `line` records for 2005-2024, one file: the per-inning
    runs for both teams in 47,062 games. Used to measure multi-inning run
    margins directly.

statsyears/leverage
    "H"/"V", inning, outs, bases, differential, leverage
    -- their own published leverage index, used here only as a cross-check.
    Note their leverage uses a 3-outcome approximation of a plate appearance
    (3% home run / 27% hit / 70% out), which is why ours differs on states where
    walks matter.

Conventions in the raw files: the run differential and the win count are both
from the *batting* team's point of view. This module converts everything to
"probability the home team wins", which is what the rest of the code speaks.
"""

import os
import ast
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EXT = os.path.join(HERE, "data", "external")

DMAX = 15
NDIFF = 2 * DMAX + 1
MAXINN = 10          # innings 10 and up are pooled into one "extra innings" slot


def load_win_expectancy(path=None):
    """-> (P, N) arrays of shape (10, 2, 3, 8, 31, 4, 3).

    P is the observed probability the HOME team wins; N is how many real
    situations that came from. Index order: inning slot (0-8 = innings 1-9,
    9 = innings 10 and up pooled),
    half (0 = visitors batting), outs, base state (0-7), differential + 15,
    balls, strikes. NaN where nothing was ever observed.
    """
    path = path or os.path.join(EXT, "probswithballsstrikes.txt")
    N = np.zeros((MAXINN, 2, 3, 8, NDIFF, 4, 3))
    W = np.zeros_like(N)
    kept = skipped = 0
    for line in open(path):
        p = line.strip().replace('"', "").split(",")
        if len(p) != 9:
            continue
        side, inn, outs, b1, diff, balls, strikes, n, w = (
            p[0], int(p[1]), int(p[2]), int(p[3]), int(p[4]),
            int(p[5]), int(p[6]), int(p[7]), int(p[8]))
        if inn < 1 or outs > 2 or balls > 3 or strikes > 2 or not 1 <= b1 <= 8:
            skipped += n
            continue
        home_bats = side == "H"
        d = diff if home_bats else -diff
        if abs(d) > DMAX:
            skipped += n
            continue
        home_wins = w if home_bats else n - w
        i = min(inn, MAXINN) - 1
        N[i, 1 if home_bats else 0, outs, b1 - 1, d + DMAX, balls, strikes] += n
        W[i, 1 if home_bats else 0, outs, b1 - 1, d + DMAX, balls, strikes] += home_wins
        kept += n
    P = np.divide(W, N, out=np.full_like(N, np.nan), where=N > 0)
    return P, N, kept, skipped


def load_run_expectancy(path=None):
    """-> (mean runs, distributions, N) each keyed [outs][base 0-7].

    The observed number of runs scored from a base/out state to the end of the
    half-inning.
    """
    path = path or os.path.join(EXT, "runsperinningstats")
    mean = np.full((3, 8), np.nan)
    n = np.zeros((3, 8))
    dist = {}
    for line in open(path):
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        outs, runners = ast.literal_eval(key.strip())
        counts = ast.literal_eval(val.strip())
        base = (1 if runners[0] else 0) | (2 if runners[1] else 0) | (4 if runners[2] else 0)
        tot = sum(counts)
        if not tot:
            continue
        mean[outs, base] = sum(i * c for i, c in enumerate(counts)) / tot
        n[outs, base] = tot
        dist[(outs, base)] = counts
    return mean, dist, n


def load_linescores(path=None):
    """-> [(away runs by inning, home runs by inning)] for every game on file.

    Read from Retrosheet's box-score `line` records. Linescores are what make it
    possible to measure how many runs a team really scores over several innings
    -- including the fact that innings within a game are not independent of each
    other -- rather than assuming it.
    """
    path = path or os.path.join(EXT, "linescores.raw")
    games, cur = [], {}
    for line in open(path):
        p = line.rstrip("\n").split(",")
        if len(p) < 3:
            continue
        if p[1] == "id":
            if 0 in cur and 1 in cur:
                games.append((cur[0], cur[1]))
            cur = {}
        elif p[1] == "line":
            cur[int(p[2])] = [int(x) for x in p[3:]
                              if x.strip().lstrip("-").isdigit()]
    if 0 in cur and 1 in cur:
        games.append((cur[0], cur[1]))
    return games


def load_published_leverage(path=None):
    """-> dict[(half, inning, outs, base, diff_home)] = their published LI."""
    path = path or os.path.join(EXT, "leverage")
    out = {}
    for line in open(path):
        p = line.strip().replace('"', "").split(",")
        if len(p) != 6:
            continue
        side, inn, outs, b1, diff, li = p[0], int(p[1]), int(p[2]), int(p[3]), int(p[4]), float(p[5])
        home_bats = side == "H"
        out[(1 if home_bats else 0, inn, outs, b1 - 1, diff if home_bats else -diff)] = li
    return out


def available():
    return all(os.path.exists(os.path.join(EXT, f)) for f in
               ("probswithballsstrikes.txt", "runsperinningstats", "leverage",
                "linescores.raw"))
