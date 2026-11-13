// compend for Wikipedia — the panel that appears on Wikipedia articles
// ------------------------------------------------------------------------------
// What it does:
//   1. Works out which Wikidata item this article is (compend keys every item
//      by its Wikidata ID, e.g. Pet Sounds = Q212863 -> compend.org/item/Q212863).
//   2. Asks the background script what compend knows (are you signed in?
//      have you logged this before? community average?).
//   3. Pops up a compend-styled card: half-star rating, review box, "Log it".
//
// All UI lives inside a Shadow DOM, so Wikipedia's CSS can't leak into it and
// ours can't leak into Wikipedia.
// ------------------------------------------------------------------------------

(() => {
  if (window.__compendPanel) return;
  window.__compendPanel = true;

  const api = globalThis.browser ?? globalThis.chrome;
  const COMPEND = "https://compend.org";

  // -------------------------------------------------------------------------
  // 1. Which article is this?
  // -------------------------------------------------------------------------
  // MediaWiki embeds its page config in an inline <script> as RLCONF={...}.
  // Content scripts can't read the page's JS variables, but they can read the
  // script's text, so we pluck the few keys we need out of it.
  function readPage() {
    const info = {};
    for (const s of document.querySelectorAll("script:not([src])")) {
      const t = s.textContent;
      if (!t.includes("wgNamespaceNumber")) continue;
      const grab = (key) => {
        const m = t.match(new RegExp(`"${key}":("(?:[^"\\\\]|\\\\.)*"|-?\\d+|true|false)`));
        return m ? JSON.parse(m[1]) : undefined;
      };
      info.qid = grab("wgWikibaseItemID"); // not always present (enwiki dropped it)
      info.ns = grab("wgNamespaceNumber");
      info.isMain = grab("wgIsMainPage");
      info.action = grab("wgAction");
      info.pageName = grab("wgPageName");
      break;
    }
    // Backup #1: the "Wikidata item" link in the desktop sidebar.
    if (!info.qid) {
      const a = document.querySelector("#t-wikibase a");
      const m = a && a.href.match(/Q\d+/);
      if (m) info.qid = m[0];
    }
    const h1 = document.querySelector("#firstHeading") || document.querySelector("h1");
    info.title = (h1 && h1.textContent.trim()) || document.title.replace(/ - Wikipedia$/, "");
    // Only real articles (namespace 0), being viewed (not edited), not the Main Page.
    info.isArticle = info.ns === 0 && !info.isMain && (info.action ?? "view") === "view";
    return info;
  }

  const page = readPage();

  // Backup #2 (e.g. mobile Wikipedia, which has no sidebar): ask this wiki's
  // own API which Wikidata item the page belongs to.
  async function resolveQid() {
    if (page.qid || !page.pageName) return;
    try {
      const url =
        `${location.origin}/w/api.php?action=query&prop=pageprops&ppprop=wikibase_item` +
        `&redirects=1&format=json&titles=${encodeURIComponent(page.pageName)}`;
      const data = await (await fetch(url)).json();
      const p = Object.values(data?.query?.pages || {})[0];
      if (p?.pageprops?.wikibase_item) page.qid = p.pageprops.wikibase_item;
    } catch (e) {
      /* no QID -> the card explains compend can't find it */
    }
  }

  // -------------------------------------------------------------------------
  // 2. Small storage helpers (settings, per-article drafts, dismissals)
  // -------------------------------------------------------------------------
  const store = {
    async get(key, fallback) {
      try {
        const r = await api.storage.local.get(key);
        return r[key] ?? fallback;
      } catch (e) {
        return fallback;
      }
    },
    async set(key, value) {
      try {
        await api.storage.local.set({ [key]: value });
      } catch (e) {
        /* storage is a nicety, never a blocker */
      }
    },
  };

  async function updateMap(key, qid, value, limit = 500) {
    const map = await store.get(key, {});
    if (value === undefined) delete map[qid];
    else map[qid] = value;
    const keys = Object.keys(map);
    if (keys.length > limit) for (const k of keys.slice(0, keys.length - limit)) delete map[k];
    await store.set(key, map);
  }

  // -------------------------------------------------------------------------
  // 3. Styles — lifted from compend.org's own design tokens
  // -------------------------------------------------------------------------
  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; }

    /* compend's palette (light), straight from its stylesheet */
    .root {
      --bg: #fff; --surface: #f1f3f8; --line: #a9adb8; --fg: #000;
      --muted: #555; --accent: #00c; --danger: #b00000; --star: #c98a00;
      font-family: "Times New Roman", Times, "Liberation Serif", serif;
      font-size: 16px; line-height: 1.5; color: var(--fg);
      position: fixed; right: 20px; bottom: 20px; z-index: 2147483000;
      display: flex; flex-direction: column; align-items: flex-end; gap: 10px;
    }
    /* compend's dark palette */
    .root.dark {
      --bg: #0a1017; --surface: #111b26; --line: #263646; --fg: #d8e1e8;
      --muted: #7f95a8; --accent: #e8e5e5; --danger: #ff5a6a; --star: #f0a23b;
      color-scheme: dark;
    }
    .logo-dark { display: none; }
    .root.dark .logo-light { display: none; }
    .root.dark .logo-dark { display: inline-block; }

    button { font: inherit; color: inherit; background: none; border: 0; padding: 0; margin: 0; cursor: pointer; border-radius: 0; }
    a { color: inherit; }

    /* ---------- the card ---------- */
    .card {
      width: 340px; max-width: calc(100vw - 40px);
      background: var(--bg); color: var(--fg);
      border: 2px dashed var(--line);
      box-shadow: 0 10px 30px rgba(0,0,0,.16);
      animation: rise .22s ease-out;
      display: flex; flex-direction: column; max-height: calc(100vh - 40px);
    }
    .card[hidden] { display: none; }
    @keyframes rise { from { transform: translateY(14px); opacity: 0; } to { transform: none; opacity: 1; } }

    .bar {
      display: flex; align-items: center; gap: 8px;
      background: var(--surface); border-bottom: 1px solid var(--line);
      padding: 6px 10px;
    }
    .brand { display: flex; align-items: center; gap: 6px; text-decoration: none; color: var(--accent); font-weight: 700; font-size: 18px; }
    .brand img { width: 22px; height: auto; }
    .bar .spacer { flex: 1; }
    .icon-btn { color: var(--accent); width: 26px; height: 26px; display: grid; place-items: center; font-size: 18px; line-height: 1; }
    .icon-btn:hover { opacity: .7; }

    .body { padding: 14px 16px 12px; display: flex; flex-direction: column; gap: 12px; overflow-y: auto; min-height: 0; }
    .kicker { font-size: 12px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); font-weight: 600; }
    h2 { font-family: "Times New Roman", Times, serif; font-weight: 700; font-size: 22px; line-height: 1.2; margin: 2px 0 0; }
    .community { font-size: 14px; color: var(--muted); }
    .community a { text-decoration: underline; }
    .community .s { color: var(--star); }

    /* ---------- half-star slider (same math as compend's) ---------- */
    .stars-row { display: flex; align-items: center; gap: 12px; }
    .slider { position: relative; display: inline-block; font-size: 30px; line-height: 1; letter-spacing: .05em; cursor: pointer; user-select: none; outline: none; }
    .slider:focus-visible { outline: 2px dotted var(--accent); outline-offset: 3px; }
    .slider .track { opacity: .35; color: var(--muted); }
    .slider .fill  { position: absolute; inset: 0; white-space: nowrap; color: var(--star); }
    .val { min-width: 2em; font-size: 14px; color: var(--muted); }
    .clear { font-size: 12px; color: var(--accent); text-decoration: underline; }

    textarea {
      width: 100%; min-height: 78px; resize: vertical;
      font: inherit; color: var(--fg);
      background: var(--surface); border: 1px solid var(--line); border-radius: 0;
      padding: 8px 12px;
    }
    textarea:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
    textarea::placeholder { color: var(--muted); }

    .actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .primary { background: var(--accent); color: var(--bg); padding: 8px 16px; }
    .primary:disabled { opacity: .4; cursor: default; }
    .primary:not(:disabled):hover { opacity: .85; }
    .hint { font-size: 12px; color: var(--muted); }

    .ok  { font-size: 14px; color: var(--accent); margin: 0; }
    .err { font-size: 14px; color: var(--danger); margin: 0; }
    .muted { color: var(--muted); }
    p { margin: 0; }
    .linkish { text-decoration: underline; color: var(--accent); }

    /* ---------- browse reviews ---------- */
    .browse { color: var(--accent); text-decoration: underline; font-size: 14px; }
    .reviews { display: flex; flex-direction: column; gap: 8px; }
    .tabs { display: flex; gap: 14px; border-bottom: 1px solid var(--line); }
    .tab {
      font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em;
      color: var(--muted); padding: 2px 0 5px; margin-bottom: -1px; border-bottom: 2px solid transparent;
    }
    .tab[aria-selected="true"] { color: var(--fg); border-bottom-color: var(--accent); }
    .rev-list { display: flex; flex-direction: column; gap: 8px; max-height: 260px; overflow-y: auto; padding-right: 2px; }
    .rev { border: 2px dashed var(--line); padding: 8px 10px; display: flex; flex-direction: column; gap: 3px; font-size: 14px; }
    .rev-top { display: flex; align-items: center; gap: 8px; }
    .rev-user { font-weight: 700; text-decoration: none; }
    .rev-user:hover { text-decoration: underline; }
    .rev-stars { color: var(--star); letter-spacing: .05em; }
    .rev-date { margin-left: auto; color: var(--muted); font-size: 12px; white-space: nowrap; }
    .rev-text { white-space: pre-wrap; overflow-wrap: anywhere; }
    .rev-foot { display: flex; gap: 12px; font-size: 12px; color: var(--muted); }
    .rev-foot a { margin-left: auto; text-decoration: underline; }
    .all { font-size: 13px; align-self: flex-start; }

    .foot {
      display: flex; justify-content: space-between; align-items: center; gap: 8px;
      border-top: 1px dashed var(--line); padding: 6px 16px 8px; font-size: 12px; color: var(--muted);
    }
    .foot label { display: flex; align-items: center; gap: 5px; cursor: pointer; }
    .foot input { margin: 0; accent-color: var(--accent); }
    .foot a { text-decoration: underline; }

    /* ---------- the collapsed pill ---------- */
    .pill {
      display: flex; align-items: center; gap: 6px;
      background: var(--bg); color: var(--accent);
      border: 2px dashed var(--line); padding: 5px 12px 5px 8px;
      box-shadow: 0 4px 14px rgba(0,0,0,.12); font-size: 15px;
    }
    .pill img { width: 18px; height: auto; }
    .pill .tick { color: var(--star); }
    .pill[hidden] { display: none; }
    .pill:hover { opacity: .85; }

    .loading { color: var(--muted); font-size: 14px; }
    @media (prefers-reduced-motion: reduce) { .card { animation: none; } }
  `;

  // -------------------------------------------------------------------------
  // 4. Tiny DOM helper: h("div.card", {attrs}, ...children)
  // -------------------------------------------------------------------------
  function h(spec, attrs, ...kids) {
    const [tag, ...classes] = spec.split(".");
    const el = document.createElement(tag || "div");
    if (classes.length) el.className = classes.join(" ");
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "text") el.textContent = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid);
    return el;
  }

  const logoLight = api.runtime.getURL("icons/logo-light.png");
  const logoDark = api.runtime.getURL("icons/logo-dark.png");
  const logos = () => [
    h("img.logo-light", { src: logoLight, alt: "" }),
    h("img.logo-dark", { src: logoDark, alt: "" }),
  ];

  // -------------------------------------------------------------------------
  // 5. The half-star slider. Same feel as compend's: hover to preview,
  //    click to set, arrow keys nudge by ½, Backspace clears.
  // -------------------------------------------------------------------------
  function starSlider(initial, onChange) {
    let value = initial || 0;
    let hover = null;

    const fill = h("span.fill", { "aria-hidden": "true", text: "★★★★★" });
    const slider = h(
      "div.slider",
      { role: "slider", tabindex: "0", "aria-label": "Rating (optional)", "aria-valuemin": "0.5", "aria-valuemax": "5" },
      h("span.track", { "aria-hidden": "true", text: "★★★★★" }),
      fill
    );
    const label = h("span.val");
    const clear = h("button.clear", { type: "button", text: "clear", onclick: () => set(0) });

    // x-position -> 0.5, 1, 1.5 … 5 (exactly compend's formula)
    const fromX = (x) => {
      const r = slider.getBoundingClientRect();
      return Math.max(1, Math.ceil(10 * Math.min(Math.max((x - r.left) / r.width, 0), 1))) / 2;
    };

    function render() {
      const shown = hover ?? value;
      fill.style.clipPath = `inset(-0.5em ${(1 - shown / 5) * 100}% -0.5em -0.5em)`;
      label.textContent = shown > 0 ? String(shown) : "optional";
      clear.hidden = !(value > 0);
      if (value > 0) slider.setAttribute("aria-valuenow", value);
      else slider.removeAttribute("aria-valuenow");
      slider.setAttribute("aria-valuetext", value > 0 ? `${value} out of 5 stars` : "No rating");
    }
    function set(v) {
      value = v;
      render();
      onChange(v);
    }

    slider.addEventListener("pointermove", (e) => {
      if (e.pointerType === "mouse") { hover = fromX(e.clientX); render(); }
    });
    slider.addEventListener("pointerleave", () => { hover = null; render(); });
    slider.addEventListener("click", (e) => set(fromX(e.clientX)));
    slider.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowUp") { e.preventDefault(); set(Math.min(5, value + 0.5)); }
      else if (e.key === "ArrowLeft" || e.key === "ArrowDown") { e.preventDefault(); set(Math.max(0.5, value - 0.5)); }
      else if (e.key === "Backspace" || e.key === "Delete") { e.preventDefault(); set(0); }
      else if (/^[1-5]$/.test(e.key)) { e.preventDefault(); set(Number(e.key)); }
    });

    render();
    return { el: h("div.stars-row", null, slider, label, clear), reset: () => set(0), focus: () => slider.focus() };
  }

  // -------------------------------------------------------------------------
  // 6. Mount: a host element with a Shadow DOM, holding the card + the pill
  // -------------------------------------------------------------------------
  const host = document.createElement("compend-panel");
  const shadow = host.attachShadow({ mode: "closed" });
  shadow.append(h("style", { text: CSS }));
  const root = h("div.root");
  shadow.append(root);

  const card = h("section.card", { hidden: true, role: "dialog", "aria-label": "Log on compend" });
  const pill = h("button.pill", { type: "button", hidden: true, title: "Log this on compend", onclick: () => open() });
  root.append(card, pill);

  // Follow Wikipedia's light/dark setting (and the OS, if Wikipedia says "automatic").
  function syncTheme() {
    const c = document.documentElement.classList;
    const dark =
      c.contains("skin-theme-clientpref-night") ||
      (c.contains("skin-theme-clientpref-os") && matchMedia("(prefers-color-scheme: dark)").matches);
    root.classList.toggle("dark", dark);
  }
  syncTheme();
  new MutationObserver(syncTheme).observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", syncTheme);

  // -------------------------------------------------------------------------
  // 7. State + rendering
  // -------------------------------------------------------------------------
  const state = {
    item: null,      // what the background told us about this item
    loggedNow: false, // logged during this visit
    saving: false,
    error: "",
    rating: 0,
    review: "",
    showReviews: false,   // "Browse reviews" open?
    reviewTab: "liked",   // "liked" | "recent"
  };

  function renderPill() {
    pill.replaceChildren(
      ...logos(),
      state.loggedNow || state.item?.alreadyLogged
        ? h("span", null, h("span.tick", { text: "★ " }), "Logged")
        : h("span", { text: "Log" })
    );
  }

  function closeCard() {
    card.hidden = true;
    pill.hidden = false;
    renderPill();
    if (page.qid) updateMap("dismissed", page.qid, true);
  }

  // `focus` is true when you opened it yourself (pill / toolbar). When it pops
  // up on its own we don't steal keyboard focus from the article.
  async function open({ focus = true } = {}) {
    card.hidden = false;
    pill.hidden = true;
    await renderCard();
    if (focus) (card.querySelector(".slider") || card.querySelector("textarea"))?.focus({ preventScroll: true });
  }

  async function renderCard() {
    const autoOpen = await store.get("autoOpen", true);
    const item = state.item;
    const itemUrl = `${COMPEND}/item/${page.qid}`;

    const bar = h(
      "div.bar",
      null,
      h("a.brand", { href: COMPEND, target: "_blank", rel: "noopener" }, ...logos(), "compend"),
      h("span.spacer"),
      h("button.icon-btn", { type: "button", title: "Close (Esc)", "aria-label": "Close", text: "×", onclick: closeCard })
    );

    const heading = h(
      "div",
      null,
      h("div.kicker", { text: state.loggedNow ? "Logged" : item?.alreadyLogged ? "Log it again" : "Log" }),
      h("h2", { text: page.title })
    );

    const body = h("div.body", null, heading);

    if (!page.qid) {
      body.append(h("p.muted", { text: "This Wikipedia page isn't linked to a Wikidata item, so compend can't find it." }));
    } else if (!item) {
      body.append(h("p.loading", { text: "Asking compend…" }));
    } else if (item.needsPermission) {
      body.append(
        h("p.err", { text: "The extension needs permission to reach compend.org." }),
        h("p.muted", { text: "Click the compend button in your toolbar and choose “Allow”." })
      );
    } else if (item.ok === false) {
      body.append(h("p.err", { text: item.error || "Couldn't reach compend." }), retryButton());
    } else if (item.busy) {
      // compend's own "Wikipedia is busy" page — happens on first look at an item.
      body.append(
        h("p.muted", { text: "compend couldn't fetch this from Wikipedia just now (it says “Wikipedia is busy”)." }),
        h("div.actions", null, retryButton(), h("a.linkish", { href: itemUrl, target: "_blank", rel: "noopener", text: "Open on compend ↗" }))
      );
    } else if (!item.exists) {
      body.append(
        h("p.muted", { text: "compend doesn't have a page for this yet." }),
        h("a.linkish", { href: itemUrl, target: "_blank", rel: "noopener", text: "Try it on compend ↗" })
      );
    } else {
      // Community line: "★ 4.7 · 59 people · Browse reviews"
      const revs = item.reviews || { liked: [], recent: [] };
      const anyReviews = revs.liked.length + revs.recent.length > 0;
      body.append(
        h(
          "p.community",
          null,
          item.count > 0
            ? [h("span.s", { text: "★ " }), `${item.average} · ${item.count} ${item.count === 1 ? "person" : "people"}`]
            : "No ratings yet",
          anyReviews
            ? [
                " · ",
                h("button.browse", {
                  type: "button",
                  "aria-expanded": String(state.showReviews),
                  text: state.showReviews ? "Hide reviews" : "Browse reviews",
                  onclick: () => {
                    state.showReviews = !state.showReviews;
                    renderCard();
                  },
                }),
              ]
            : null
        )
      );
      if (state.showReviews && anyReviews) body.append(reviewBrowser(revs, itemUrl));

      if (item.signedIn === false) {
        const next = encodeURIComponent(`/item/${page.qid}`);
        body.append(
          h(
            "p",
            null,
            h("a.linkish", { href: `${COMPEND}/login?next=${next}`, target: "_blank", rel: "noopener", text: "Sign in to review this" })
          ),
          h("p.hint", { text: "Come back to this tab after signing in — the form will appear." })
        );
      } else {
        body.append(...formParts());
      }
    }

    const foot = h(
      "div.foot",
      null,
      h(
        "label",
        { title: "Open this card automatically on articles you haven't logged" },
        h("input", {
          type: "checkbox",
          checked: autoOpen,
          onchange: (e) => store.set("autoOpen", e.target.checked),
        }),
        "Pop up on new articles"
      )
    );

    card.replaceChildren(bar, body, foot);
  }

  // -------------------------------------------------------------------------
  // "Browse reviews": compend's Most liked / Recent logs, inside the card.
  // The data comes from the same compend page we already fetched.
  // -------------------------------------------------------------------------
  function reviewBrowser(revs, itemUrl) {
    const tabs = [
      ["liked", "Most liked", revs.liked],
      ["recent", "Recent", revs.recent],
    ].filter(([, , list]) => list.length);
    if (!tabs.some(([k]) => k === state.reviewTab)) state.reviewTab = tabs[0][0];
    const list = tabs.find(([k]) => k === state.reviewTab)[2];

    const tabRow = h(
      "div.tabs",
      { role: "tablist" },
      tabs.map(([key, label]) =>
        h("button.tab", {
          type: "button",
          role: "tab",
          "aria-selected": String(key === state.reviewTab),
          text: label,
          onclick: () => {
            state.reviewTab = key;
            renderCard();
          },
        })
      )
    );

    const items = list.map((r) =>
      h(
        "article.rev",
        null,
        h(
          "div.rev-top",
          null,
          h("a.rev-user", { href: `${COMPEND}/u/${encodeURIComponent(r.user)}`, target: "_blank", rel: "noopener", text: r.user }),
          r.rating ? h("span.rev-stars", { "aria-label": `${r.rating} out of 5 stars`, text: starText(r.rating) }) : null,
          h("span.rev-date", { text: r.date })
        ),
        r.text ? h("p.rev-text", { text: r.text }) : null,
        h(
          "div.rev-foot",
          null,
          r.likes > 0 ? h("span", { text: `♥ ${r.likes}` }) : null,
          h("a", { href: r.url, target: "_blank", rel: "noopener", text: "Open ↗" })
        )
      )
    );

    return h(
      "section.reviews",
      { "aria-label": "Reviews on compend" },
      tabRow,
      h("div.rev-list", null, items),
      h("a.linkish.all", { href: itemUrl, target: "_blank", rel: "noopener", text: "All reviews on compend ↗" })
    );
  }

  // 4.5 -> "★★★★½" (compend shows half stars as a half glyph)
  function starText(n) {
    return "★".repeat(Math.floor(n)) + (n % 1 >= 0.5 ? "½" : "");
  }

  function retryButton() {
    return h("button.primary", {
      type: "button",
      text: "Retry",
      onclick: async () => {
        state.item = null; // shows "Asking compend…"
        renderCard();
        await loadItem();
        renderCard();
        renderPill();
      },
    });
  }

  function formParts() {
    const stars = starSlider(state.rating, (v) => {
      state.rating = v;
      saveDraft();
    });
    const ta = h("textarea", {
      placeholder: "Add a review (optional)",
      rows: "3",
      maxlength: "5000",
      oninput: (e) => {
        state.review = e.target.value;
        saveDraft();
      },
      onkeydown: (e) => {
        if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit(); }
      },
    });
    ta.value = state.review;

    const again = state.loggedNow || state.item?.alreadyLogged;
    const btn = h("button.primary", {
      type: "button",
      disabled: state.saving,
      text: state.saving ? "Saving…" : again ? "Log it again" : "Log it",
      onclick: submit,
    });

    const parts = [stars.el, ta, h("div.actions", null, btn)];
    if (state.loggedNow && !state.error) {
      parts.push(
        h(
          "p.ok",
          null,
          "Entry added. ",
          h("a", { href: `${COMPEND}/item/${page.qid}`, target: "_blank", rel: "noopener", style: "text-decoration:underline", text: "View on compend ↗" })
        )
      );
    }
    if (state.error) parts.push(h("p.err", { text: state.error }));
    return parts;
  }

  // Remember half-written reviews per article, so closing the tab doesn't lose them.
  let draftTimer;
  function saveDraft() {
    clearTimeout(draftTimer);
    draftTimer = setTimeout(() => {
      const empty = !state.rating && !state.review.trim();
      updateMap("drafts", page.qid, empty ? undefined : { rating: state.rating, review: state.review });
    }, 300);
  }

  async function submit() {
    if (state.saving || !page.qid) return;
    state.saving = true;
    state.error = "";
    renderCard();

    const res = await api.runtime
      .sendMessage({ type: "log", qid: page.qid, rating: state.rating, review: state.review })
      .catch(() => ({ ok: false, error: "The extension couldn't reach its background script. Try reloading the page." }));

    state.saving = false;
    if (res && res.ok) {
      state.loggedNow = true;
      state.rating = 0;
      state.review = "";
      await updateMap("drafts", page.qid, undefined);
      // Refresh community numbers so your rating shows up in the average.
      const fresh = await api.runtime.sendMessage({ type: "item", qid: page.qid }).catch(() => null);
      if (fresh && fresh.ok) state.item = fresh;
      state.item = { ...state.item, alreadyLogged: true };
    } else {
      state.error = (res && res.error) || "Something went wrong.";
      if (res && res.needsSignIn && state.item) state.item = { ...state.item, signedIn: false };
    }
    renderCard();
    renderPill();
  }

  async function loadItem() {
    if (!page.qid) return;
    state.item = await api.runtime
      .sendMessage({ type: "item", qid: page.qid })
      .catch(() => ({ ok: false, error: "The extension couldn't reach its background script." }));
  }

  // -------------------------------------------------------------------------
  // 8. Boot
  // -------------------------------------------------------------------------
  async function boot() {
    await resolveQid();
    if (!page.qid) return; // not a Wikidata-linked article: stay invisible
    document.documentElement.append(host);

    const draft = page.qid ? (await store.get("drafts", {}))[page.qid] : null;
    if (draft) {
      state.rating = draft.rating || 0;
      state.review = draft.review || "";
    }

    pill.hidden = false;
    renderPill();
    await loadItem();
    renderPill();

    // Pop the card open if: setting is on, you haven't closed it on this article
    // before, you haven't logged it yet — or you have an unsent draft.
    // (Errors still pop up, so a broken lookup is visible instead of silent.)
    const autoOpen = await store.get("autoOpen", true);
    const dismissed = (await store.get("dismissed", {}))[page.qid];
    const fresh = !state.item?.alreadyLogged;
    if (draft || (autoOpen && !dismissed && fresh)) open({ focus: false });
  }

  // Escape closes the card — when focus is in the card, or nowhere in particular
  // (so we never hijack Escape from Wikipedia's own search box or dialogs).
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || card.hidden) return;
    const a = document.activeElement;
    if (a === host || a === document.body || a === null) { e.stopPropagation(); closeCard(); }
  });

  // If you went off to sign in and came back, re-check.
  document.addEventListener("visibilitychange", async () => {
    if (document.visibilityState !== "visible" || !page.qid) return;
    if (state.item && state.item.signedIn === false) {
      await loadItem();
      if (!card.hidden) renderCard();
      renderPill();
    }
  });

  // Toolbar button toggles the card (works on any article, even if auto-open is off).
  api.runtime.onMessage.addListener((msg) => {
    if (msg && msg.type === "toggle") {
      if (!host.isConnected) document.documentElement.append(host);
      if (!card.hidden) return closeCard();
      open();
      // Opened via toolbar on a page we didn't boot on (or before data arrived)
      if (!state.item) resolveQid().then(loadItem).then(renderCard);
    }
  });

  if (page.isArticle) boot();
})();
