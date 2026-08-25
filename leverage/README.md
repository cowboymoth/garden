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
        the same thing, averaged over every PA in a season
```

**1.00 is a perfectly average moment.** A bases-loaded, two-out, bottom-of-the-9th
spot with the home team down one is 11.1 — the highest leverage in baseball.
A seven-run lead in the third is 0.10.

The app shows two numbers:

- **This at-bat** — leverage over the rest of the plate appearance. At 0-0 this
  is exactly the classic LI. As the count moves it re-prices.
- **This pitch** — the same idea for one pitch, normalised against an average
  *pitch*, so 1.00 is again average. A 3-2 pitch with the bases loaded and two
  outs in a one-run 9th is **23×** an average pitch.

## Where the numbers come from

Everything is measured off the **2024 season, pitch by pitch** — Retrosheet
event files, 2,426 games, 182,232 plate appearances, 710,000 pitches. Nothing
is a rule of thumb:

| piece | how it's built |
|---|---|
| base-out transitions | the empirical distribution of what actually followed each of the 24 base/out states, by outcome. Double plays, first-to-third, sac flies all show up at their real rates |
| pitch model | P(ball / strike / foul / in play as X \| count), measured from real pitch sequences — so 3-1 counts really do produce more damage |
| win expectancy | backward induction over innings with the real rules: walk-offs, the home team not batting in the 9th when ahead, the runner-on-second rule in extras |
| the normalising constants | the average \|ΔWP\| per PA and per pitch across 2024, weighted by how often each state actually came up |

Mid-plate-appearance events (steals, wild pitches, balks) are folded into the
plate appearance they happened during, so they aren't silently dropped.

## Does it work?

The build prints its own checks. The ones that matter:

- **The parser.** Each game is replayed from the notation and its final score
  compared to the official box score. 2,426 of 2,429 games match exactly
  (99.88%). Derived counts agree with Retrosheet's own count field on 99.94% of
  plate appearances.
- **Run expectancy.** The model's RE24 table vs what actually happened in 2024:
  0.487 vs 0.485 with the bases empty and nobody out, 2.319 vs 2.317 with the
  bases loaded. 4.38 runs per team per nine innings, against 4.39 in real life.
  The model runs a touch light on runner-on-third states (1.30 vs 1.41) — the
  usual Markov-model gap, since it treats every hitter as league average.
- **The normalising constant.** Derived independently here, it comes out at
  **0.0343 wins per PA**; the constant usually quoted for this is ~0.0346.
- **Where leverage peaks.** The model's maximum is 11.08, at bottom of the 9th,
  bases loaded, two outs, down one — the state you'd expect to top the list, and
  in the right neighbourhood of the ~10-11 ceiling LI is known to have.
- **The browser matches the Python.** `check.mjs`-style comparison against the
  `selftest` values baked into `model.json`; worst disagreement is 1e-4, which
  is the rounding in the exported table.

Both teams are treated as league average with no home-field edge — the same
convention the published LI tables use. The model's start-of-game win
expectancy is therefore 0.500, where the real 2024 home winning percentage was
0.521.

## Files

```
fetch_data.sh          pull the 2024 Retrosheet season (~25 MB, not committed)
parse_retrosheet.py    event notation -> base-out transitions + pitch sequences
build_model.py         -> win expectancy, leverage, model.json / model.js
index.html             the app
model.js               the exported model the app loads (model.json is the same data)
```

Rebuild:

```
./fetch_data.sh && python3 parse_retrosheet.py && python3 build_model.py
```
