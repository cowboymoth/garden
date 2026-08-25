# Leverage

A phone-sized app for the question "how big is this moment?" Punch in a game
state — inning, score, outs, who's on, the count — and get the **Leverage
Index** of the at-bat and of the very next pitch.

Open `index.html`. No build step, no server.

## What Leverage Index is

Tom Tango's stat, the one FanGraphs uses. It's the win-probability swing you
should expect from a spot, divided by the swing of an average plate appearance:

```
        E| change in win expectancy over the next plate appearance |
LI  =   -----------------------------------------------------------
        the same thing, averaged over every PA
```

**1.00 is a perfectly average moment.** The app shows two numbers:

- **This at-bat** — leverage over the rest of the plate appearance. At 0-0 this
  is exactly the classic LI. As the count moves it re-prices.
- **This pitch** — the same idea for one pitch, normalised against an average
  *pitch*, so 1.00 is again average. A 3-2 pitch with the bases loaded and two
  outs in a one-run 9th is **22×** an average pitch.

## Where the numbers come from

The rule: **if somebody has already measured it, read their matrix rather than
deriving one.**

| piece | source |
|---|---|
| **win expectancy**, per game state *and per ball-strike count* | **Pulled.** [gregstoll/baseballstats](https://github.com/gregstoll/baseballstats), the data behind the Win Expectancy Finder — measured from Retrosheet play-by-play across **195,573 major-league games / 33.6 million observed situations**, including a split by count |
| **run expectancy** per base-out state | **Pulled.** Their observed runs-to-end-of-inning distribution, 15.5M observations |
| a published **leverage index** column | **Pulled**, as a cross-check only — see below |
| what each outcome does to the bases, and how often each outcome happens | **Measured here** from the 2024 Retrosheet season (2,426 games, 182,232 PA, 710k pitches), because no published matrix of this exists in usable form |
| the two normalising constants | **Measured here** from 2024 state frequencies |

The only place a model of ours still enters is as a **prior**. The published
tables are thin in rare corners — 20-run leads, the 14th inning — so every cell
is shrunk from its observed rate toward a structural win-expectancy model by its
own sample size. Weighted by how often states actually come up, what the app
reports is **85% observed data at the state level** and 32% at the count level
(count cells are a twelfth the size, so the prior carries more of them there).
The build prints all of this.

Mid-plate-appearance events (steals, wild pitches, balks) are folded into the
plate appearance they happened during, so they aren't silently dropped.

## Observed vs even teams

There's a switch in the app, and it's the most interesting thing here.

Real win expectancy **falls off faster with the score** than a two-average-teams
model says it should, because a club that is behind really is more often the
weaker club. Score margin carries team quality with it. So leverage computed
from the observed table runs higher early in a game and lower in the extreme
late-inning spots than the textbook version:

| situation | observed table | even teams | their published LI |
|---|---|---|---|
| start of game | 0.98 | 0.83 | 0.86 |
| bot 9th, tied, bases loaded, 2 out | 6.66 | 6.99 | 5.30 |
| bot 9th, down 1, bases loaded, 2 out | 10.63 | 11.41 | 10.39 |
| bot 8th, down 1, on 1st & 2nd, 1 out | 5.23 | 5.18 | 5.20 |
| top 3rd, up 8, bases empty, 1 out | 0.10 | 0.09 | 0.23 |

The conventional LI you'd read on FanGraphs is the **even teams** column — that
convention is deliberate, since LI is meant to describe the *situation*, not the
clubs. The app defaults to the observed table (it is, after all, what actually
happened) and the switch gets you the conventional number.

## Does it work?

The build prints its own checks:

- **Against their published leverage column.** Correlation **0.986** across
  1,525 well-sampled states. Where we differ, we're right: their leverage
  approximates a plate appearance as 3% home run / 27% hit / 70% out, with **no
  walk at all**, so it understates spots where a walk matters — bases loaded and
  tied in the 9th is 5.30 for them, 6.66 here.
- **Run expectancy.** The published observed matrix vs our 2024 outcomes:
  0.495 vs 0.487 bases empty and nobody out, 2.327 vs 2.319 bases loaded,
  largest gap 0.091 runs. The published table spans many decades of a
  higher-offence game, so most of that is era rather than error.
- **The prior is only a prior.** Scored against the observed table it lands at
  rms 0.028; a single log-odds recalibration (it assumes no home-field edge, and
  the real table has one) takes that to 0.020. That makes it worth ~600 observed
  situations, so a cell with N = 30,000 is 98% data.
- **The count recursion.** Before falling back on it, we check it against the
  observed by-count cells: bias −0.0002, rms 0.007 over 23M situations.
- **The parser.** Every 2024 game is replayed from Retrosheet notation and its
  final score compared to the official box score: **2,426 of 2,429 match
  exactly**. Derived counts agree with Retrosheet's own count field on 99.94% of
  plate appearances.
- **The normalising constant** comes out at **0.0355 wins per PA**; the constant
  usually quoted for this is ~0.0346.
- **The browser matches the Python** to 2.5e-3 on 18 reference values across
  both modes — that residual is the 1e-4 quantisation of the shipped table
  divided through by the per-pitch normaliser.

One caveat worth knowing: the published win-expectancy table spans decades in
which extra innings had no automatic runner on second, so extra-inning cells
reflect mostly the old rule.

## Files

```
fetch_data.sh          pull the 2024 Retrosheet season + the published tables
external_tables.py     read the published win/run expectancy matrices
parse_retrosheet.py    2024 event notation -> base-out transitions + pitch sequences
build_model.py         blend, compute leverage, write model.json / model.js
index.html             the app
model.js               the exported tables the app loads (model.json is the same data)
```

Rebuild:

```
./fetch_data.sh && python3 parse_retrosheet.py && python3 build_model.py
```

Retrosheet data is free of charge and copyrighted by Retrosheet, 20 Sunset Rd.,
Newark, DE 19711.
