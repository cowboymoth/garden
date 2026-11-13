# compend for Wikipedia (Firefox + Chrome)

Rate and review the thing you're reading about on Wikipedia, straight into your
[compend](https://compend.org) diary, without leaving the article. You can also
browse what other people on compend said about it.

Unofficial; not made by or affiliated with compend.

## Install (temporary, for trying it out)

**Firefox**
1. Go to `about:debugging#/runtime/this-firefox`
2. **Load Temporary Add-on…** → pick `manifest.json` in this folder
3. Be signed in at compend.org in the same Firefox
4. Open any Wikipedia article. The card pops up bottom-right.

Temporary add-ons vanish when Firefox restarts.

If Firefox didn't grant site access at install, a welcome tab opens with an
**Allow access** button. Clicking the toolbar icon also asks for access.

**Chrome**
1. `./build-chrome.sh` (assembles `chrome/` from the same source files)
2. `chrome://extensions` → Developer mode → **Load unpacked** → pick `chrome/`

Managed (work) Chrome profiles may block this by policy.

## Using it

- Click/hover the stars (half-stars work), type a review, **Log it** (⌘/Ctrl+Enter also works).
- Keys on the stars: ←/→ by ½, 1–5 jump, Backspace clears.
- **Browse reviews** opens compend's Most liked / Recent reviews inside the card.
- × or Esc collapses it to a small "Log" pill. It won't auto-pop on that article again.
- "Pop up on new articles" off = only the pill / toolbar button.
- Half-written reviews are saved per article.

## How it works

- **Which item?** compend keys every item by its Wikidata ID (Pet Sounds =
  `Q212863` → `compend.org/item/Q212863`). The content script reads it from the
  page's sidebar link, falling back to Wikipedia's API (mobile pages).
- **Item info + reviews** come from compend's item page (one request per article):
  signed-in state, community average, Most liked / Recent reviews. If compend
  answers "Wikipedia is busy" (happens on an item's first-ever load), it retries.
- **Saving.** compend.org's own "Log it" button calls a Next.js *server action*
  named `logItem({itemId, rating, review})`. The background script calls that
  same action with your normal compend cookies.
  - The action's hex ID changes on redeploys, so it's rediscovered from
    compend's JS bundles (cached per deployment), with one retry if stale.
  - Next.js rejects calls whose `Origin` isn't compend.org, so the extension
    rewrites `Origin` on **its own** requests only (Firefox: blocking
    `webRequest`; Chrome: a `declarativeNetRequest` session rule).
- **Caveat:** this is compend's internal, undocumented endpoint. If compend
  changes how logging works, saving will fail with a clear error and a link to
  log on compend directly.

## Data

Declared to Firefox as `browsingActivity` (each Wikipedia article you open is
looked up on compend, logged in as you) and `personalCommunications` (reviews
you submit are posted to compend). Nothing goes anywhere except compend.org.

## Packaging

```sh
# Firefox zip -> web-ext-artifacts/
npx web-ext build --overwrite-dest --ignore-files chrome manifest.chrome.json build-chrome.sh README.md
npx web-ext lint  --ignore-files chrome manifest.chrome.json build-chrome.sh

# Chrome: zip the chrome/ folder after ./build-chrome.sh
```

## Files

| File | What |
|---|---|
| `manifest.json` | Firefox MV3 (`background.scripts`, blocking webRequest) |
| `manifest.chrome.json` | Chrome MV3 (service worker, declarativeNetRequest) |
| `background.js` | Talks to compend: item lookup, reviews, action discovery, logging (shared) |
| `content.js` | The card on Wikipedia (Shadow DOM, compend's colors/fonts) (shared) |
| `welcome.html/js` | One-time "allow access" page |
| `build-chrome.sh` | Copies shared files + Chrome manifest into `chrome/` |
| `icons/` | compend's logo, resized |
