# durak — library notes

Cheat sheet for the two libraries installed here, written 2026-10-13. Most of
what's online describes older versions, and **both libraries have changed in
ways that break old tutorials.**

## What's installed, and where

| | Version | Use this file in the page | Reference copy (not committed) |
|---|---|---|---|
| p5.js | 2.3.4 | `lib/p5.min.js` | `node_modules/p5/` (+ `types/p5.d.ts`) |
| three.js | r186 (0.186.1) | `lib/three/three.module.js` **+** `lib/three/three.core.js` | `node_modules/three/` (+ `examples/jsm/` add-ons, `@types/three`) |

- `lib/` is committed, so GitHub Pages serves the libraries with no CDN and no build step. `node_modules/` is gitignored and holds the source, type definitions and three's add-ons, for reading.
- `three.module.js` imports `./three.core.js`, so both files must stay side by side.
- **Run locally through a server**, not by double-clicking the file: `python3 -m http.server 8000` in `durak/`. Browsers refuse to load ES modules (three.js) from `file://`. A page that uses only p5 would open fine directly.
- To add a three add-on (such as `DragControls`), copy it from `node_modules/three/examples/jsm/...` into `lib/three/addons/`, and add `"three/addons/": "./lib/three/addons/"` to the import map.

## p5.js 2.x: what changed from 1.x (most tutorials are 1.x)

- **`preload()` is gone.** Load assets with `async function setup() { img = await loadImage(...) }`. Code before the `await` runs right away. To load several assets in parallel, use `Promise.all`.
- **Mouse and touch are merged** into pointer events. Use `mousePressed`/`mouseReleased`/`mouseDragged` and the `touches` array. `touchStarted`/`touchMoved`/`touchEnded` are no longer the 2.x approach. One set of handlers covers both phone and desktop, which suits a card game.
- **`mouseButton` is now an object**: write `mouseButton.left` and `mouseButton.right`, not `mouseButton === RIGHT`.
- **Keys:** use `keyIsDown(LEFT_ARROW)`, `key === 'Enter'` or `code === 'KeyA'`. String comparisons against `keyCode` no longer work.
- **Curves renamed:** `curveVertex`→`splineVertex`, `curve`→`spline`. `bezierVertex` now takes **one point per call**; set the curve's order with `bezierOrder()`. `endShape(CLOSE)` now smooths the closing join.
- **Text:** `textWidth` measures tightly and skips leading and trailing spaces. `fontWidth` includes them.
- `createVector()` needs explicit components, e.g. `createVector(0, 0)`.
- Removed: `append`, `arrayCopy`, `concat`, `reverse`, `shorten`, `sort`, `splice`, `subset`, `createStringDict`/`createNumberDict`. Use plain JS arrays and objects.
- The old p5.sound does **not** work with 2.x. Use the new p5.sound or Tone.js.
- **Instance mode** (`new p5(p => { p.setup = ...; p.draw = ... })`) keeps p5 out of the global namespace. Use it whenever three.js shares the page. `index.html` uses it.

## three.js r186, used for a mostly-2D game

- Use an **`OrthographicCamera`** sized to the canvas, `new OrthographicCamera(-W/2, W/2, H/2, -H/2, -1000, 1000)`, so that 1 unit = 1 pixel with no perspective. Bring in a `PerspectiveCamera` only for moments that need depth.
- A card is a thin `BoxGeometry` (or two `PlaneGeometry`s back to back) with a face texture and a back texture. Rotating it on Y gives a real **3D flip**. That flip is the main thing three adds over p5.
- Card faces can be drawn on a 2D canvas (even with p5, or with `createGraphics`) and wrapped in `CanvasTexture`. That way three doesn't need image files at all.
- Clicking cards uses `Raycaster` with pointer coordinates. Dragging can use `examples/jsm/controls/DragControls.js`.
- Use `renderer.setAnimationLoop(fn)` rather than calling `requestAnimationFrame` by hand.
- `WebGLRenderer` is the safe default. `WebGPURenderer` (`three.webgpu.js`) exists, but a card table doesn't need it.

## Which one for durak?

**Recommendation: p5 for the game (table, hands, rules UI, animation), with three
held in reserve.** Durak is a flat card table, and p5's immediate-mode drawing
(the whole frame is redrawn every tick) makes hit-testing, layout and
"juice" (animation polish) quick to write. Bring in three only if we want
showy physical moments: real 3D card flips, a tilted table, a deck that
fans out in depth. Running both on one page works, but costs two render loops.

**Decision (2026-10-13):** the game is built in p5 alone (`index.html`). Three is
installed but unused.

## Sources

- p5 v2 teachers' guide: https://p5js.org/tutorials/v2_transition/
- p5 1.x→2.x technical changes and compatibility add-ons: https://github.com/processing/p5.js-compatibility
- Async in p5 2.0: https://dev.to/limzykenneth/asynchronous-p5js-20-458f
