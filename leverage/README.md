# Leverage

A phone-sized app for one question: **how much can this moment move?** Punch in
a game state — inning, score, outs, who's on, the count — and get the **Leverage
Index** of the at-bat and of the very next pitch, plus what each outcome would
swing.

Open `index.html`. No build step, no server.

Nothing here shows a probability *level*. Only changes in one.

## Swing what?

Four things a plate appearance can move, switchable in the app. Each gets its
own scale, so **1.00 is always an average moment** for that metric.

| metric | the swing in… | where it comes from |
|---|---|---|
| **Win game** | the chance of winning | published observed win-expectancy table |
| **After 5** | the chance of being ahead after 5 innings | convolved observed run distributions |
| **After 3** | the chance of being ahead after 3 innings | same |
| **Score run** | the chance the batting team scores again this inning | read straight off the observed run distribution |

They rank situations differently, which is the point. Bottom of the 3rd, tied,
runners on first and second with one out:

| | game | after 5 | after 3 | score a run |
|---|---|---|---|---|
| leverage | 2.20 | 3.32 | **5.22** | 1.57 |

The same spot is a routine moment for the game and a huge one for the F3 line.
And in the bottom of the 9th down one with the bases loaded and two outs, the
game reads **10.83** while "score a run" reads only 2.41 — nearly all of that
leverage is about *which* runs, not whether any score.

## Where the numbers come from

The rule: **if somebody has already measured it, read their matrix rather than
deriving one.**

| piece | source |
|---|---|
| **win expectancy**, per game state *and per ball-strike count* | **Pulled.** [gregstoll/baseballstats](https://github.com/gregstoll/baseballstats), the data behind the Win Expectancy Finder — measured from Retrosheet play-by-play across **195,573 major-league games / 33.6M observed situations** |
| **runs scored in the rest of a half-inning**, per base-out state, as a full distribution | **Pulled.** Same source, 15.5M observed half-innings. This is the whole basis for the other three metrics |
| a published **leverage index** column | **Pulled**, as a cross-check |
| what each outcome does to the bases, and how often each outcome happens | **Measured here** from the 2024 Retrosheet season (2,426 games, 182,232 PA, 710k pitches) — no published matrix of this exists in usable form |
| the eight normalising constants | **Measured here** from 2024 state frequencies |

"Ahead after N innings" is deliberately *not* a win model. A segment outcome is
just runs scored in the half-innings that are left, so it is the observed
run-per-inning distributions convolved together, then read off the margin. Only
the standard independence-between-half-innings assumption enters.

The one place a model of ours still appears is as a **prior**: the published win
table is thin in rare corners (20-run leads, the 14th inning), so every cell is
shrunk from its observed rate toward a structural model by its own sample size.
Weighted by how often states actually come up, the game numbers rest on **86%
observed data** at the state level (32% at the count level, where cells are a
twelfth the size).

Mid-plate-appearance events — steals, wild pitches, balks — are folded into the
plate appearance they happened during, so they aren't silently dropped.

## Does it work?

The build prints its own checks:

- **The F3 / F5 convolution against reality.** Compared to what actually
  happened in 2024, over states with 200+ observed plate appearances:
  bias −0.007, rms **0.019** after 3 innings; bias −0.009, rms **0.024** after
  5. Per-cell sampling noise alone is about 0.022, so essentially all of that
  residual is sample size. The small negative bias is home-field advantage,
  which the pooled run distribution doesn't carry.
- **Against a published leverage column.** Correlation **0.986** across 1,525
  well-sampled states. Where we differ we're better: theirs approximates a plate
  appearance as 3% home run / 27% hit / 70% out with **no walk at all**, so it
  understates spots where a walk matters — bases loaded and tied in the 9th is
  5.30 for them, 6.66 here.
- **Run expectancy.** The published observed matrix vs our 2024 outcomes: 0.495
  vs 0.487 bases empty and nobody out, 2.327 vs 2.319 bases loaded; largest gap
  0.091 runs. The published table spans decades of a higher-offence game, so
  most of that is era rather than error.
- **The prior is only a prior.** Scored against the observed table it lands at
  rms 0.028; one log-odds recalibration (it assumed no home-field edge, and the
  real table has one) takes it to 0.020. That makes it worth ~600 observed
  situations, so a cell with N = 30,000 is 98% data.
- **The count recursion**, used where no observed by-count table reaches, agrees
  with the observed by-count cells to bias −0.0002, rms 0.007 over 23M
  situations.
- **The parser.** Every 2024 game is replayed from Retrosheet notation and its
  final score compared to the official box score: **2,426 of 2,429 match
  exactly**. Derived counts agree with Retrosheet's own count field on 99.94% of
  plate appearances.
- **The game normalising constant** comes out at **0.0348 wins per PA**; the
  constant usually quoted is ~0.0346.
- **The browser matches the Python** to 2.7e-3 across 30 reference values
  spanning all four metrics — that residual is the 1e-4 quantisation of the
  shipped tables divided through by the per-pitch normaliser.

Two things worth knowing. The published win table spans decades in which extra
innings had no automatic runner on second, so extra-inning cells reflect mostly
the old rule. And observed win expectancy falls off faster with the score than
an even-teams model would, because a club that is behind really is more often
the weaker club — real leverage early in a game runs a little higher than the
textbook even-teams number for that reason (start of game 1.00 here vs 0.85
on an even-teams model — that even-teams figure is itself within a hundredth of
the conventional published value).

## Files

```
fetch_data.sh          pull the 2024 Retrosheet season + the published tables
external_tables.py     read the published win / run expectancy matrices
parse_retrosheet.py    2024 event notation -> base-out transitions + pitch sequences
build_model.py         blend, build the four metrics, write model.json / model.js
index.html             the app
model.js               the exported tables the app loads (model.json is the same data)
```

Rebuild:

```
./fetch_data.sh && python3 parse_retrosheet.py && python3 build_model.py
```

Retrosheet data is free of charge and copyrighted by Retrosheet, 20 Sunset Rd.,
Newark, DE 19711.
