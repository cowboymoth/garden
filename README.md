# garden

Playground for vibecoded projects. Intentionally messy — see
[`CLAUDE.md`](CLAUDE.md) for how to work in here.

Live: **https://cowboymoth.github.io/garden/** (once Pages is switched on — see
below).

## What's in here

| Project | What it is | Runs how |
|---|---|---|
| [`doodles/`](doodles/) | **Doodle Armature** — a generative sheet of naive ink/pencil drawings. Every part is pinned to an invisible 3D solid and projected, so the whole thing turns. Eight utensils, ordered-rank hatching, quality gates, 30fps animation. | open `doodles/doodles.html` |
| [`odds-game/`](odds-game/) | A small odds-guessing game. | open `odds-game/index.html` |
| [`art auctions/`](art%20auctions/) | Auction-lot pricing: estimates P(hammer > strike), calibrated against three 2026 sales. `CALIBRATION.md` documents the method. | `python3 "art auctions/price_lot.py"` |
| [`drake/`](drake/) | Lyric-frequency analysis across a catalogue. | `python3 drake/count_lyrics.py` |
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

## Turning on GitHub Pages

Everything in here is a static HTML file, so Pages serves it with no build step.

**Settings → Pages → Source: "Deploy from a branch" → Branch `main`, folder `/ (root)` → Save.**

A minute later:

- `https://cowboymoth.github.io/garden/` — the landing page
- `https://cowboymoth.github.io/garden/doodles/doodles.html`
- `https://cowboymoth.github.io/garden/odds-game/index.html`

After that, `git push` *is* the deploy.

## Working on it

```sh
git clone https://github.com/cowboymoth/garden.git
cd garden
open doodles/doodles.html          # file:// is fine for the sketches
python3 -m http.server 8000        # or serve it, if a project needs fetch()
```
