---
name: doodle-armature
description: Work on the generative doodle sheet in ~/Desktop/garden/doodles/doodles.html — a single self-contained HTML file that draws grids of naive ink/pencil specimens (heads, cats, flowers, owls, beetles) by pinning parts to an invisible 3D solid. Use when asked to add a subject, part, texture, or art medium; to change how the drawings look; to fix a visual problem; or to work on the animation. Read README.md first for the architecture.
---

# Picking up the pen

`doodles.html` is one file, ~3000 lines, no dependencies. `README.md` next to it
has the architecture and the layer table. This file is the part you cannot infer
from the code: the invariants, and the mistakes that cost real iterations.

## Before you change anything

1. **Serve it and look at it.** `python3 -m http.server 8931` in the folder.
   Screenshot the sheet, then *zoom in on individual cells*. Nearly every real
   problem here was invisible in the code and obvious at 3× zoom.
2. **Syntax-check after every edit** — the script is inside HTML so nothing
   else will catch a typo:
   ```sh
   awk '/^<script>$/{f=1;next} /^<\/script>$/{f=0} f' doodles.html > /tmp/c.js && node --check /tmp/c.js
   ```
3. **Edit surgically.** Prefer exact-string replacement with an assertion that
   the target was found exactly once, so a silent no-op can't slip through.

## Invariants — do not break these

**Randomness is a seeded stream read in order.** `build()` consumes from an
rng and `draw()` continues from where it stopped. Anything that changes *how
much* randomness a code path consumes re-rolls every mark downstream of it.
This is why:

- **Animation may only perturb continuous numbers, never branches.** Swap a
  mouth style mid-animation and the linework boils. Add a `smile` parameter
  that changes an arc's curvature instead.
- Adding a part in the middle of `draw()` shifts everything after it. Append at
  the end, or give the new part its own rng.

**`amp` is a fraction of PATH LENGTH, not pixels.** `amp: 0.05` on a 0.1-unit
hair spike is nothing; the same number on a full head outline is a lumpy potato.
When wobble looks wrong, check the path length, not the amp.

**Both stroke passes must share a wobble phase.** They used to roll independent
phases, which pushed the two lines up to 20px apart and made every specimen
read as two overlapping heads. A hand going back over a line *retraces* it.

**Units.** `unit` is the cell size. `S.rx`/`S.ry` are absolute px derived from
it. Anything expressed as a fraction of the *solid* (`cR`, `rad`, `k` in
`discPt`) must be multiplied by `S.rx`/`S.ry`, never by `unit`. Getting this
wrong drew a loop wider than the cell around every flower.

**Prefer a constructive rule to a gate.** Derive the value so it cannot be
wrong (the hairline is computed *from* eye height) rather than rolling blind and
rejecting. Gates are for what you cannot construct.

**`pin()` moves an anchor, not a footprint.** A big filled part — a bushy brow,
a toothbrush moustache — needs `clampPts()` to clamp every vertex.

## Mistakes worth not repeating

**Sketchiness is not noise.** The pen once drew two passes, each split into 3–4
chunks with random width *and* alpha — six to eight marks per line. That reads
as *fuzzy*, not sketchy. Confident naive drawing is a small number of committed
marks; the randomness should be a nudge, not the effect.

**Gradients give the game away.** `createRadialGradient` has perfectly smooth
falloff, which nothing made by hand does. Dry media are built from *skipping
dashes* — pigment catches the high points of the paper and misses the hollows,
and that skip is the entire difference between a real mark and a gradient.

**Skip must be correlated for a contour.** Deciding it independently per 7px
segment turns an outline into a dotted ring. Charcoal rides the paper for a
stretch then loses it for a moment: walk in *runs* separated by short lifts.
Heavy skip is right for a fill and fatal for a contour.

**Ordered ranks, not random scatter.** All five dry textures once routed
through one function that scattered strokes at random positions, so pencil,
charcoal and smear were the same grey cloud at three densities. Shading marches
in parallel ranks at roughly even spacing. **The eye reads ranks as technique
and random scatter as mush** — that one change is most of the personality.

**A flat multiplier on a hair region makes a helmet.** `rad` used to scale the
skull uniformly, so the outer edge of every haircut was a perfectly scaled copy
of the head underneath. No amount of interior texture fixes that. Give the
outer edge its own lobes and a lean.

**Colour is not a fill.** `fillPts(sil, tint, 0.32)` floods the whole
silhouette and reads as a paint bucket; it also kills the paper. Colour goes on
as coloured pencil, in ordered ranks, misregistered from the outline like a
badly aligned second plate. Coloured pencil needs *more* passes than graphite
to register at all — do the coverage arithmetic (region area ÷ stroke area)
rather than guessing.

**One texture per specimen, not one per part.** Hair and beard picking
independently meant a single face could carry three different mark-making
styles at once. That is what "too abstract" looks like.

**Put the wonk on axes that cannot collide.** Vertical jitter causes pile-ups;
sideways offset, size and rotation don't. Same character, far less mess.

**Look up real references, not drawings of them.** Asked for flower
references, the first search returned drawing tutorials, which uniformly reduce
every flower to a ring of ovals round a circle. Of the eight forms built from
actual photographs, *none* work that way — an iris is organised vertically, a
poppy is a crumpled bowl, a sunflower's disc is tiny tubes on a golden-angle
spiral. Fetch photographs and open them.

## Performance

**The cost is raster area, not call count.** This one is counter-intuitive and
cost a wasted refactor: batching every dash into `Path2D` buckets cut canvas
calls from 276,000 to 28,000 and made flowers **twice as slow**. Hundreds of
thousands of tiny translucent strokes cost the same to rasterise either way.

So the only real lever is **drawing fewer marks**. `LOD()` scales dry-media
density while animating and `heavy()` gates the passes that cost most for
least. Reducing rows also helps linearly.

Also cache what does not change per frame. `tryCache` stores which reroll
passed the gates for each cell; without it every frame re-ran up to `MAX_TRIES`
builds per cell to rediscover the same answer.

Measure before optimising:
```js
const t=performance.now(); render(); performance.now()-t          // one frame
// count canvas calls by monkey-patching ctx.stroke / ctx.fill
```

**Gotcha when driving this from browser automation:** `requestAnimationFrame`
is suspended when the tab is not being composited, so the animation will look
frozen and `animT` will never advance — it is not your bug. Confirm by counting
rAF ticks yourself; if you get zero, drive the loop by hand with synthetic
timestamps instead:
```js
playing=true; warming=WARM; animStart=0; lastFrame=0;
let t=5000; for(let i=0;i<68;i++) frame(t+=16.7);   // 8 warm + 60 @60Hz => 30 renders
```

## Square exports

`renderSquare()` draws one specimen into an offscreen canvas at any size, for
profile pictures. Two things it does that the sheet does not, and both matter:

- **It composes for a circle, not a square.** Most clients crop an avatar
  round, so the corners are thrown away. Solve for the largest `unit` whose
  extremes stay inside the inscribed circle — and remember the binding
  constraint is usually an *off-axis* extreme (a cat's ear tip), not the
  topmost or widest point.
- **It does not jitter.** No cell offset, minimal turn. The sheet's jitter is
  character; in a fixed frame it is just miscomposition.

`ctx` is a `let` so it can be pointed at an offscreen canvas — restore it in
the same function or every later draw goes to the wrong place. Any preview
decoration (crop guides) must be drawn when compositing onto the main canvas,
never into the tile itself.

## Adding things

**A texture** — add to `TEXTURES` (and `TEXINK` for the contrast gate; and
`HAIRTEX` if it has enough body for hair), then a branch in `texture()`. Work
in surface `(u,v)` and project, so it turns with the form. Callers wrap it in
`clipTo(region, …)`, so spill generously and let the clip cut the edge — that
hard edge is the look.

**A medium** — add to `MEDIA`, a width scale in `TOOLW`, a `…Pass()` function,
and a case in `inkPass()`. Remember a line of varying width is a *polygon*, not
a line (see `brushPass`).

**A part** — a small function with several named variants, taking `(A, r,
opts)` where `A` is an anchor. Give it a `col` so void cats can cut it out of
black, and a `tilt` so no two are stamped at the same angle. Apply R1 with
`pin()` at the call site.

**A subject** — an object with `name`, `solid`, `shapes`, `build`, `gates`,
`tag`, `draw`, and optional `cols` / `rows` / `fillK` / `ryK` to shape its grid
and how much of the cell it fills. Add it to `SUBJECTS`. Radial subjects can
reuse the tilted-disc solid; `silPt`/`discPt` already foreshorten correctly.

**Foliage or any attached appendage** — pin it to the armature with
`radialDir()`: an angle round the plant's vertical axis and a length, carried
through the rotation. Then it swings and foreshortens with the pose instead of
being stamped in page space. Sort by the returned depth so the one behind the
stem draws first, and floor the projected length or a part pointing dead at the
viewer collapses to nothing. Stems stay in page space — a stem answers to
gravity, not to the pose.

## House style

This lives in `~/Desktop/garden`, a personal playground — creativity over
rigor, one-file scripts, hardcoded paths fine. But comments are load-bearing
here: explain *why* a number is what it is, and when you fix something, say
what the broken version did wrong. Most of the value in this file is in those
comments.
