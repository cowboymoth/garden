# Doodle Armature

A generative sheet of naive ink/pencil drawings. One self-contained HTML file,
no libraries, no image assets — `doodles.html`.

Open it straight from Finder (`file://` works fine in a normal browser).

Five subjects: **Heads**, **Cats**, **Flowers**, **Owls**, **Beetles**.
Click any specimen to reroll just that one. Drag **Turn** to swivel the whole
sheet. **Show armature** exposes the invisible solid. **Animate** brings it to
life. The footer reports the sheet seed, which quality gates fired, and which
utensils the sheet used.

---

## The one idea

**The drawings are not laid out on a flat canvas.** Each subject has an
invisible 3D solid under it — an ellipsoid for a head, a tilted disc for a
flower or a beetle — and every part is pinned to a `(u, v)` coordinate on that
solid's surface. To draw, the solid is rotated, each anchor is projected to 2D,
and the part is placed there.

Rotate the solid and the features move correctly, including hiding round the
back. Everything else in the file is downstream of this.

Two consequences worth internalising:

- Each part's **orientation** comes from the solid's own global axes
  (`axes(S)`), not from the surface tangent at its anchor. Tangents all
  converge at the poles, so tangent-oriented parts collapse into a mess up
  there.
- Because the parts already live on a real surface with real normals, "which
  side is in shadow" is a dot product against one sheet-wide light, not a guess
  — and it swings correctly when you drag Turn.

---

## Architecture, in drawing order

| Layer | What it does | Key functions |
|---|---|---|
| **Solid** | The invisible 3D form. Rotation, surface points, normals, projection. | `rot`, `onSolid`, `normalAt`, `project`, `anchor`, `place` |
| **Shapes** | A radial multiplier on the *outline* only. The solid stays a plain ellipsoid; a pear is the same skull with more jaw. | `SHAPES`, `shapeR`, `outline`, `silPt` |
| **Rules layer** | Stops parts being drawn in stupid places. See below. | `toForm`, `pin`, `clampPts`, `seen`, `packStack` |
| **Pen** | Wobble, overshoot, densify. Turns a point array into a hand-drawn line. | `wobble`, `overshoot`, `densify`, `stroke` |
| **Media** | Eight utensils, one per specimen. | `MEDIA`, `penPass`, `brushPass`, `markerPass`, `dipPass`, `dryPass` |
| **Dry media** | Pencil/charcoal as *skipping dashes*, in ordered ranks. | `pencilStroke`, `pencilShade`, `pencilShadeBox`, `TECHNIQUE` |
| **Textures** | Fills for enclosed regions, in surface space so they turn. | `TEXTURES`, `texture`, `surfHatch`, `furEdge` |
| **Parts** | Small named functions with many variants each. | `eye`, `brow`, `nose`, `mouth`, `drawEars`, `drawHair`, `drawBeard`, … |
| **Subjects** | `build` (the spec) + `gates` + `draw`. | `HEAD`, `CAT`, `FLOWER`, `OWL`, `BEETLE` |
| **Sheet** | Paper texture, cell loop, gate rerolls, controls. | `makePaper`, `drawCell`, `render` |

### The rules layer

Everything above it will cheerfully draw a part in a stupid place. Four rules:

- **R1 IN** — a feature belongs on the face. Clamp it inside the outline.
- **R2 OUT** — a worn or attached thing (hair, hat, brim, ear) sits *on* the
  form, so it is pushed *out* to the edge, never pulled in.
- **R3 OCCLUDE** — a part whose surface normal has turned away is *gone*. Not
  faded, not squashed: gone.
- **R4 SPACE** — features are packed as a vertical stack so they don't land on
  each other. The minimum separation is deliberately **soft** (`TOUCH`): a
  little interpenetration is what a hand does.

R1 and R2 are the same operation with the inequality flipped, and neither needs
a search. In the ellipse's own frame the outline is a circle scaled by
`shapeR`, so "how far out is this point, and where is the edge along that
direction" is one 2×2 solve plus one function call. It stays exact when the
head turns because the matrix *is* the rotation, and exact when the head is a
pear because it asks `shapeR` the same question the outline did.

### Quality gates

Borrowed from [Strays](https://strays.vercel.app/): generate, then judge, and
throw the bad ones away. A gate is cheaper and far more honest than narrowing
every parameter range until nothing can go wrong — the ranges stay expressive
and only the bad corners get rejected.

Each subject exposes `gates: [[name, predicate], …]`. A cell that fails any
gate is rerolled with a new seed, up to `MAX_TRIES`. **The footer reports which
gates fired**, because a gate that never fires is a gate you don't need.

Prefer a **constructive rule** over a gate wherever one exists. The hairline is
derived *from* eye height rather than rolled blind and rejected on collision; a
rule that cannot fail beats a gate that has to notice.

### Media

`tool` is picked **once per specimen** and every mark in that drawing obeys it.
That consistency is the whole point: it makes the sheet read as forty drawings
made with different tools rather than forty drawings made with forty random
effects.

A utensil's signature is mostly about how *width* behaves along a stroke —
`pen`, `tech`, `brush` (tapering ribbon), `marker` (blunt, square ends), `dip`
(hairline to blot), `charcoal`/`crayon`/`pencil` (skipping dashes).

### Animation

A full redraw is ~20–35ms, so the animation genuinely **redraws** rather than
sliding cached bitmaps around. That means the armature itself moves and every
part follows it.

**Pinned to 30fps** (`FPS`). Left uncapped the rate varied from 26 to 68
depending on subject, and since motion is driven off wall-clock time the
drawings all moved at the same *speed* but with visibly different smoothness.
A fixed budget is steadier and leaves headroom.

**Warm-up.** Pressing Animate runs `WARM` (8) frames behind a "Warming n"
label before starting the clock. Two one-time costs get paid there instead of
being smeared across the opening second: the JIT has not been through the
drawing path yet, and `tryCache` has not been filled.

**The hard constraint: only ever animate continuous parameters, never
branches.** The ink comes from a seeded rng read in order, so swapping a mouth
style mid-animation would re-roll every wobble downstream of it and the
linework would boil. Perturb numbers, never code paths.

Moving: pose wiggle/nod/tilt, hair bounce (the same sine **lagged**, which is
what reads as weight), smile (mouth arc curvature), blink (a `lid` parameter
squashing eye height).

---

## Working on it

```sh
cd ~/Desktop/garden/doodles
python3 -m http.server 8931          # then open http://localhost:8931/doodles.html
```

Syntax-check without a browser:

```sh
awk '/^<script>$/{f=1;next} /^<\/script>$/{f=0} f' doodles.html > /tmp/check.js
node --check /tmp/check.js
```

Measure a frame from the console:

```js
const t=performance.now(); render(); performance.now()-t
```

Force a variant to inspect it (in-page only; reload restores):

```js
FLOWER_NAMES.length=0; FLOWER_NAMES.push('bluebonnet'); newSheet();
MEDIA.fill('charcoal'); render();
```

**Look at the output.** Every visual problem in this file was found by
screenshotting and zooming in, and several were invisible in the code.

See `SKILL.md` for the invariants and the mistakes worth not repeating.

---

## References this was built from

- **Mannay's ink sheets** — the source look. What carries those drawings is
  *value*: a solid black mass meeting a light face along one hard, slightly
  ragged edge, and every enclosed region full of texture. The outlines are
  fine, not fat.
- **Igor Trunin's prompt** ([x.com/igortr_](https://x.com/igortr_/status/2090750438626799665))
  — the original brief, including "add a rules layer so nothing slides off the
  form", which is where the rules layer comes from.
- **Yan Liu** ([x.com/yanliudesign](https://x.com/yanliudesign/status/2090635681286779057))
  — the normalised-height trick: `ry` is fixed and width/depth vary, so a long
  specimen reads as *narrow* rather than bigger. Character without footprint
  creep, which matters on a grid.
- **Strays** ([strays.vercel.app](https://strays.vercel.app/)) — quality gates,
  and "parts drawn once, moved via bones beneath".
- **Flowers** were built from photographs of real specimens, not drawing
  guides. This mattered: nearly every "how to draw a flower" source reduces
  the lot to a ring of ovals round a circle, and of the eight forms
  implemented, none actually work that way. Species notes are in the comment
  block above `FLOWER_KINDS`.

## Known caveats

- The grid is per-subject, via `cols` / `rows` on the subject object (see
  `gridFor`). Heads are 6×4 and spend the bigger cell through `fillK` and
  `ryK`; flowers are 8×3 because they are tall and narrow; the rest are 8×5.
- While animating, dry media draw at reduced density (`LOD`, 0.21). The drawing
  visibly lightens. It's the only real lever — see `SKILL.md`. **Retune it
  whenever the drawings grow**: raster area is the cost, so a bigger head eats
  the frame budget.
- `tryCache` remembers which reroll passed the gates per cell, so an animated
  frame does one `build()` per cell instead of up to `MAX_TRIES`. Cleared on
  new sheet and subject change, deliberately *not* on Turn.
- `pin()` moves a part's *anchor*; big filled parts need `clampPts()` to clamp
  every vertex.
- The four `createRadialGradient` calls left in the file are all in
  `makePaper`, where smooth falloff is genuinely correct for paper mottling.
  Nothing in the drawings uses one.
- `doodles.backup-*.html` is a pre-rewrite snapshot. The folder has no git.
