# durak

The Russian card game, house rules, you against bots. Hand-drawn ink on black,
by candlelight.

```
cd durak && python3 -m http.server 8000      →  http://localhost:8000
node sim.js                                   →  10,000 bot games, every rule checked
```

| File | What it is |
|---|---|
| `engine.js` | The referee: game state, legal moves, timers. The full house rules are written at the top. No drawing. |
| `bots.js` | Computer players and their tuning knobs (`BOT_DEFAULTS`). Bots see only what a seated player would see. |
| `index.html` | The table (p5.js). Setup screen → deal → play → who's the durak. |
| `sim.js` | Bots play each other in the terminal; checks card conservation, legal moves, refills, the attack cap, and the short-deck order. |
| `lib/` | p5 (and three, unused for now), committed so GitHub Pages needs no build. See `LIBS.md`. |

**Playing:** click a card to attack or throw it in. When defending, click a card and it covers the attack
it beats (if it could beat several, click the card, then the attack). `take` (or T / space) picks
up. With **perevodnoy** on, a card matching the attack's number can be passed on: click it, or click
the dashed "pass on" slot. The wick is the clock — at *fast*: 15 s to open, 8 s to defend, 3 s for last
throw-ins; *normal* doubles that, *slow* is 5× (bots keep the normal pace).

**Dev shortcuts:** `index.html#deal5` skips setup with 5 players; `#deal5auto` also lets a bot play your
seat; `durak.g` in the console is the live game state.
