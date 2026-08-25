# garden

Playground for vibecoded projects. Intentionally messy — see
[`CLAUDE.md`](CLAUDE.md) for how to work in here.

Live: **https://cowboymoth.github.io/garden/**

## What's in here

| Project | What it is | Runs how |
|---|---|---|
| [`doodles/`](doodles/) | **Doodle Armature** — a generative sheet of naive ink/pencil drawings. Every part is pinned to an invisible 3D solid and projected, so the whole thing turns. Eight utensils, ordered-rank hatching, quality gates, 30fps animation. | open `doodles/doodles.html` |
| [`leverage/`](leverage/) | **Leverage** — punch in a game state and see how much it can move: leverage index of the at-bat and of the next pitch, measured against winning the game, leading after 5, leading after 3, or scoring this inning. Published Retrosheet win/run tables, 2024 outcome rates. | open `leverage/index.html` |
| [`odds-game/`](odds-game/) | A small odds-guessing game. | open `odds-game/index.html` |
| [`art-auctions/`](art-auctions/) | Auction-lot pricing: estimates P(hammer > strike), calibrated against three 2026 sales. `CALIBRATION.md` documents the method. | `python3 art-auctions/price_lot.py` |
| `nightcore/` | Sped-up edits of one track at several speeds. Source and renders are audio, so they stay local — nothing is committed. | local only |
| `tools/` | Scratch `esbuild`/`typescript` install. Generated, not committed. | local only |

`doodles/` is the one with real documentation:
[README](doodles/README.md) for the architecture,
[SKILL.md](doodles/SKILL.md) for the invariants and the mistakes worth not
repeating.

## What is deliberately not committed

This repo is **public**, so `.gitignore` keeps a few categories local:

- **Third-party media** — the album rip, the nightcore renders derived from it,
  the auction-house catalogue PDFs, and the lyrics corpus. All commercial
  copyrighted material, and ~340MB besides (the largest PDF is 74MB against
  GitHub's 100MB per-file limit).
- **Generated** — `node_modules/`, `__pycache__/`, `.venv/`, `.DS_Store`.
- **Local config** — `**/.claude/settings.local.json`.
- **`CLAUDE.local.md`** — the fuller local copy of the notes. The tracked
  `CLAUDE.md` is the *portable* version, deliberately free of any reference to
  work projects.

Every script reads from local paths, so nothing here needs the ignored files
committed in order to run.

## GitHub Pages

Pages is on, deploying from `main` at `/ (root)`. Everything in here is a static
HTML file, so there is no build step — **`git push` is the deploy**, and the
site updates about a minute later.

- <https://cowboymoth.github.io/garden/> — the landing page
- <https://cowboymoth.github.io/garden/leverage/>
- <https://cowboymoth.github.io/garden/doodles/doodles.html>
- <https://cowboymoth.github.io/garden/odds-game/index.html>

## Working on it

```sh
git clone https://github.com/cowboymoth/garden.git
cd garden
open doodles/doodles.html          # file:// is fine for the sketches
python3 -m http.server 8000        # or serve it, if a project needs fetch()
```
