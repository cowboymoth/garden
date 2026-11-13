// compend for Wikipedia — background script (works in Firefox AND Chrome)
// ------------------------------------------------------------------------------
// This is the part of the extension that actually talks to compend.org.
// The little panel on the Wikipedia page (content.js) sends it two kinds of
// messages:
//
//   {type: "item", qid}                  -> "what does compend know about this?"
//   {type: "log",  qid, rating, review}  -> "save a log entry for me"
//
// How logging works (plain-language version):
//   compend is a Next.js site. When you press "Log it" on compend.org, the page
//   calls a *server action* named `logItem` — basically a hidden POST endpoint
//   identified by a long hex ID instead of a URL. We call that same action,
//   with your normal compend login cookies, so it's exactly as if you'd pressed
//   the button on compend yourself.
//
// Wrinkles:
//   1. The action's hex ID changes whenever compend redeploys. So instead of
//      hardcoding it, we read compend's own JavaScript files and find the ID
//      next to the name "logItem". It's cached per deployment.
//   2. Next.js refuses action calls whose `Origin` header isn't compend.org
//      (a standard anti-forgery check). Requests from an extension say
//      `moz-extension://…` / `chrome-extension://…`, so we rewrite that header
//      — only on requests this extension makes, never on your normal browsing.
//      Firefox: blocking webRequest. Chrome: a declarativeNetRequest rule.
//   3. The first time anyone opens an item, compend fetches it from Wikipedia,
//      and that sometimes fails with a "Wikipedia is busy" page. We retry.
// ------------------------------------------------------------------------------

const api = globalThis.browser ?? globalThis.chrome;
const IS_FIREFOX = typeof globalThis.browser !== "undefined" && !!globalThis.browser.runtime.getBrowserInfo;
const COMPEND = "https://compend.org";

// The logItem ID as of 2026-11-12. Only used if auto-discovery fails.
const FALLBACK_ACTION_ID = "404c84b9fac78b01616eb4e3a6938ac57040a4abd3";

const HOSTS = ["https://compend.org/*", "https://*.wikipedia.org/*"];

// ---------------------------------------------------------------------------
// 1. Make our requests look like they came from compend.org itself.
// ---------------------------------------------------------------------------
const OUR_PREFIX = api.runtime.getURL("");

if (IS_FIREFOX && api.webRequest) {
  // Firefox: rewrite headers on the fly, only for requests this extension made.
  api.webRequest.onBeforeSendHeaders.addListener(
    (details) => {
      const from = details.originUrl || details.documentUrl || "";
      if (!from.startsWith(OUR_PREFIX)) return {};
      const headers = details.requestHeaders.filter((h) => !/^(origin|referer)$/i.test(h.name));
      headers.push({ name: "Origin", value: COMPEND });
      headers.push({ name: "Referer", value: details.url });
      return { requestHeaders: headers };
    },
    { urls: ["https://compend.org/*"] },
    ["blocking", "requestHeaders"]
  );
} else if (api.declarativeNetRequest) {
  // Chrome: a session rule that sets Origin on compend.org requests that don't
  // come from any tab (tabId -1 = this extension's background, not your browsing).
  api.declarativeNetRequest
    .updateSessionRules({
      removeRuleIds: [1],
      addRules: [
        {
          id: 1,
          priority: 1,
          action: {
            type: "modifyHeaders",
            requestHeaders: [
              { header: "origin", operation: "set", value: COMPEND },
              { header: "referer", operation: "set", value: COMPEND + "/" },
            ],
          },
          condition: { requestDomains: ["compend.org"], tabIds: [-1] },
        },
      ],
    })
    .catch((e) => console.error("[compend] couldn't install header rule", e));
}

// ---------------------------------------------------------------------------
// 2. Read an item page on compend and pull out what we need.
// ---------------------------------------------------------------------------
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// compend sometimes answers "Wikipedia is busy" when it's loading an item for
// the first time. Retry a few times before giving up.
async function fetchItem(qid) {
  let item;
  for (const wait of [0, 1500, 3000]) {
    if (wait) await sleep(wait);
    item = await fetchItemOnce(qid);
    if (!item.busy) return item;
  }
  return item;
}

async function fetchItemOnce(qid) {
  const url = `${COMPEND}/item/${qid}`;
  const res = await fetch(url, { credentials: "include", cache: "no-store" });
  const raw = await res.text();
  // React sprinkles <!-- --> between text fragments; drop them so regexes work.
  const html = raw.replace(/<!-- -->/g, "");
  // The page's data is embedded as escaped JSON (\"key\":\"value\"); unescape it.
  const flat = html.replace(/\\"/g, '"');

  const titleMatch = html.match(/<title>([^<]*?) · compend<\/title>/);
  const busy = !titleMatch && /Wikipedia is busy|couldn.t load this item/i.test(html);
  const exists = res.ok && !!titleMatch;

  // The log form is rendered with props like {"id":"Q…","signedIn":true,"alreadyLogged":false}
  let signedIn = null;
  let alreadyLogged = false;
  const at = flat.indexOf(`"id":"${qid}","signedIn":`);
  if (at !== -1) {
    const chunk = flat.slice(at, at + 200);
    signedIn = /"signedIn":true/.test(chunk);
    alreadyLogged = /"alreadyLogged":true/.test(chunk);
  } else if (html.includes("Sign in to review this")) {
    signedIn = false;
  }

  // Community rating, e.g. "4.7 average from 59 people"
  const avgMatch = html.match(/([\d.]+) average from (\d+) (?:people|person)/);

  return {
    ok: true,
    exists,
    busy,
    reviews: parseReviews(html),
    url,
    title: titleMatch ? decodeEntities(titleMatch[1]) : null,
    signedIn,
    alreadyLogged,
    average: avgMatch ? Number(avgMatch[1]) : null,
    count: avgMatch ? Number(avgMatch[2]) : 0,
    // Used for action-ID discovery, not sent to the panel:
    _deployment: (html.match(/data-dpl-id="([^"]+)"/) || [])[1] || null,
    _scripts: [...new Set(html.match(/\/_next\/static\/[^"'\s]+?\.js/g) || [])],
  };
}

// Pull the "Most liked" and "Recent" reviews out of the item page.
// (Regex, not DOMParser, because Chrome's background service worker has no DOM.)
// Each review on compend is a <div class="card relative flex flex-col gap-1 p-3 …">
// holding: username link, star rating (aria-label), date, text, like count.
function parseReviews(html) {
  const out = { liked: [], recent: [] };
  const recentAt = html.search(/<h3[^>]*>Recent<\/h3>/);
  const MARK = '<div class="card relative flex flex-col gap-1 p-3';
  let pos = html.indexOf(MARK);
  while (pos !== -1) {
    const next = html.indexOf(MARK, pos + MARK.length);
    const chunk = html.slice(pos, next === -1 ? pos + 6000 : next);

    const link = chunk.match(/href="(\/u\/[^"\/]+\/[0-9a-f-]{36})"/);
    const user = chunk.match(/font-semibold" href="\/u\/[^"]+">([^<]+)<\/a>/);
    const stars = chunk.match(/aria-label="([\d.]+) out of 5 stars"/);
    const date = chunk.match(/<span class="ml-auto text-sm text-muted">([^<]+)<\/span>/);
    const text = chunk.match(/<span class="card-text[^"]*">([\s\S]*?)<\/span><\/p>/);
    const likes = chunk.match(/aria-label="Like this review"[\s\S]*?<span>(\d+)<\/span>/);

    if (link && user) {
      const review = {
        user: decodeEntities(user[1]),
        url: COMPEND + link[1],
        rating: stars ? Number(stars[1]) : null,
        date: date ? decodeEntities(date[1]) : "",
        // reviews can contain @mentions/links; keep just the words
        text: text ? decodeEntities(text[1].replace(/<br\s*\/?>/g, "\n").replace(/<[^>]+>/g, "")).trim() : "",
        likes: likes ? Number(likes[1]) : 0,
      };
      const bucket = recentAt !== -1 && pos > recentAt ? out.recent : out.liked;
      // Only the same review once per tab
      if (!bucket.some((r) => r.url === review.url)) bucket.push(review);
    }
    pos = next;
  }
  return out;
}

function decodeEntities(s) {
  return s
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;|&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">");
}

// ---------------------------------------------------------------------------
// 3. Find the current hex ID of compend's `logItem` server action.
// ---------------------------------------------------------------------------
// In compend's bundled JS it looks like:
//   createServerReference)("404c84b9…",i.callServer,void 0,i.findSourceMapURL,"logItem")
const ACTION_RE = /createServerReference\)\("([0-9a-f]{20,})",[^"]*?"logItem"\)/;

async function getActionId(item, { force = false } = {}) {
  const { actionCache } = await api.storage.local.get("actionCache");
  if (!force && actionCache && actionCache.deployment === item._deployment) {
    return actionCache.id;
  }
  for (const path of item._scripts) {
    try {
      const js = await (await fetch(COMPEND + path)).text();
      const m = js.match(ACTION_RE);
      if (m) {
        await api.storage.local.set({ actionCache: { deployment: item._deployment, id: m[1] } });
        return m[1];
      }
    } catch (e) {
      /* try the next file */
    }
  }
  // Not on this page's scripts (e.g. a "busy" page). Reuse the last known ID.
  if (actionCache && actionCache.id) return actionCache.id;
  console.warn("[compend] couldn't discover logItem action; using fallback ID");
  return FALLBACK_ACTION_ID;
}

// ---------------------------------------------------------------------------
// 4. Call the action and decode Next's reply.
// ---------------------------------------------------------------------------
// The reply is "React Server Components" text, one row per line:
//   0:{"a":"$@1","q":"","i":false}
//   1:{"error":"You need to sign in to log items."}
// Row 0 points at the row holding the action's return value ("$@1" -> row 1).
// A row starting with "E" means the server threw.
async function callLogAction(actionId, qid, rating, review) {
  const res = await fetch(`${COMPEND}/item/${qid}`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Next-Action": actionId,
      Accept: "text/x-component",
      "Content-Type": "text/plain;charset=UTF-8",
    },
    body: JSON.stringify([{ itemId: qid, rating, review }]),
  });

  if (res.headers.get("x-nextjs-action-not-found")) return { stale: true };
  const text = await res.text();

  const rows = {};
  for (const line of text.split("\n")) {
    const m = line.match(/^([0-9a-f]+):(.*)$/);
    if (m) rows[m[1]] = m[2];
  }
  let pointer = "1";
  try {
    const head = JSON.parse(rows["0"]);
    if (typeof head.a === "string" && head.a.startsWith("$@")) pointer = head.a.slice(2);
  } catch (e) {
    /* keep default */
  }
  const body = rows[pointer];

  if (!body || body.startsWith("E")) {
    // Server crashed — most likely the action ID went stale after a deploy.
    return { stale: true, status: res.status };
  }
  let result;
  try {
    result = JSON.parse(body);
  } catch (e) {
    return { ok: false, error: "compend sent back something unexpected." };
  }
  if (result && result.error) return { ok: false, error: result.error };
  return { ok: true };
}

async function logItem(qid, rating, review) {
  const item = await fetchItem(qid);
  if (!item.exists && !item.busy) return { ok: false, error: "compend doesn't have a page for this yet." };
  if (item.signedIn === false) return { ok: false, needsSignIn: true, error: "You need to sign in to log items." };

  let id = await getActionId(item);
  let out = await callLogAction(id, qid, rating, review);
  if (out.stale) {
    // Re-discover once and retry.
    id = await getActionId(item, { force: true });
    out = await callLogAction(id, qid, rating, review);
  }
  if (out.stale) {
    return {
      ok: false,
      error: "compend changed under us and the save didn't go through. Try logging on compend directly.",
    };
  }
  return out;
}

// ---------------------------------------------------------------------------
// 5. Messages from the panel.
// ---------------------------------------------------------------------------
async function hasHostAccess() {
  try {
    return await api.permissions.contains({ origins: ["https://compend.org/*"] });
  } catch (e) {
    return true;
  }
}

async function handle(msg) {
  if (!(await hasHostAccess())) {
    return { ok: false, needsPermission: true, error: "The extension needs access to compend.org." };
  }
  try {
    if (msg.type === "item") {
      const { _deployment, _scripts, ...pub } = await fetchItem(msg.qid);
      return pub;
    }
    if (msg.type === "log") {
      const review = String(msg.review || "").slice(0, 5000); // compend's own cap
      const rating = msg.rating > 0 ? msg.rating : null; // 0 = "no rating"
      return await logItem(msg.qid, rating, review);
    }
  } catch (e) {
    console.error("[compend]", e);
    return { ok: false, error: "Couldn't reach compend. Are you online?" };
  }
  return { ok: false, error: "Unknown request." };
}

// sendResponse + `return true` is the reply style both browsers support.
api.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || (msg.type !== "item" && msg.type !== "log")) return false;
  handle(msg).then(sendResponse);
  return true;
});

// ---------------------------------------------------------------------------
// 6. Toolbar button: (Firefox) grant access if needed, then toggle the panel.
// ---------------------------------------------------------------------------
api.action.onClicked.addListener((tab) => {
  const toggle = () => {
    if (tab.url && /^https:\/\/[^/]+\.wikipedia\.org\/wiki\//.test(tab.url)) {
      return api.tabs.sendMessage(tab.id, { type: "toggle" }).catch(() => {});
    }
    return api.tabs.create({ url: COMPEND });
  };
  if (IS_FIREFOX) {
    // Firefox MV3 may hold back site access until asked. permissions.request
    // must run synchronously inside the click, so it goes first; if access is
    // already granted it resolves instantly. (Chrome grants it at install.)
    api.permissions.request({ origins: HOSTS }).catch(() => false).then(toggle);
  } else {
    toggle();
  }
});

// On install, if site access wasn't granted, show a one-time explainer.
api.runtime.onInstalled.addListener(async () => {
  if (!(await hasHostAccess())) {
    api.tabs.create({ url: api.runtime.getURL("welcome.html") });
  }
});
