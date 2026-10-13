// engine.js — the Durak referee.
//
// Holds the whole game state, checks every move against the house rules, and
// applies it. No drawing and no clock of its own: the current time is passed
// in (`now`, in ms), so the same code runs in the browser, in the terminal
// simulator (sim.js), and — later — on a server for online play.
//
// House rules
//   • 52-card deck, 2 low … Ace high. 6 cards each; the next card is flipped
//     face up and slid under the deck — its suit is trump, and it's the last
//     card anyone draws.
//   • The player holding the lowest trump attacks first (random if no one has one).
//   • Attacks go clockwise. The opening attack is one card, or several cards of
//     the same number (a pair, trips, quads). 15 s to open, or the turn passes on.
//   • Once the battle is open, any non-defender may add cards whose number
//     matches any card on the table. Total attack cards per battle can't
//     exceed the defender's hand size at the start of the battle.
//   • Defender beats an attack with a higher card of the same suit, or any
//     trump on a non-trump. 8 s to respond, reset whenever an attack is added.
//     Running out the clock = picking up.
//   • When every attack is covered, attackers get 3 s to add more, then the
//     cards are discarded and the defender attacks next.
//   • Perevodnoy (a setting, on by default): before covering anything, the
//     defender may pass the attack on by adding a card of the same number. They
//     become an attacker; the next player clockwise must now defend against
//     the whole pile. Not allowed if that player holds fewer cards than the
//     pile would have. It can travel all the way round the table. A deflection
//     only changes who defends — it doesn't move the turn order (below).
//   • Turn order: attacking turns go clockwise from whoever opened the attack.
//     Whoever picks up skips their next turn.
//   • In a throw-in window, a non-defender can say "pass" (done adding). When
//     every non-defender has passed, the window closes without waiting.
//   • If the defender picks up, attackers get 3 s to throw in more matching
//     cards (a setting), then the defender takes everything and loses their turn.
//   • Refill to 6, one card at a time round-robin: first attacker, the other
//     attackers clockwise, defender last (so in a short deck the defender ends
//     up with fewer cards — fewer is better in this game).
//   • The clocks above are the "fast" speed; "normal" doubles them, "slow" is 5×.
//   • Once the deck is empty, anyone with no cards is out. First out wins;
//     the last one holding cards is the durak (the fool).

export const SUITS = ['♠', '♥', '♦', '♣'];
export const RED = [false, true, true, false];
export const rankOf = c => 2 + (c >> 2);   // cards are ints 0..51
export const suitOf = c => c & 3;
export const rankName = r => ({ 11: 'J', 12: 'Q', 13: 'K', 14: 'A' })[r] ?? String(r);
export const cardName = c => rankName(rankOf(c)) + SUITS[suitOf(c)];

export const DEFAULTS = {
  openMs: 15000,        // opening attacker's clock
  defendMs: 8000,       // defender's clock, reset on every added attack
  windowMs: 3000,       // all attacks covered: attackers' last chance to add
  takeMs: 3000,         // defender picked up: attackers' chance to throw in more
  throwInOnTake: true,  // whether that throw-in window exists at all
  perevodnoy: true,     // defender may pass the attack on with a same-number card
  speed: 'normal',      // see SPEEDS
  handSize: 6,
};

// Speed multiplies the clocks, and how long bots take to think. On "slow" the
// bots keep the "normal" pace — only you get the extra time.
export const SPEEDS = {
  fast:   { timers: 1, bots: 1 },
  normal: { timers: 2, bots: 2 },
  slow:   { timers: 5, bots: 2 },
};

// Small seeded random generator, so any game can be replayed from its seed.
export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Does card d beat card a?
export function beats(d, a, trump) {
  if (suitOf(d) === suitOf(a)) return rankOf(d) > rankOf(a);
  return suitOf(d) === trump;
}

// ── helpers anyone (UI, bots) can use ────────────────────────────────────────
export const uncovered = g => g.table.filter(x => x.d == null).length;
export const room = g => g.cap - g.table.length;
export const tableRanks = g => new Set(g.table.flatMap(x => x.d == null ? [rankOf(x.a)] : [rankOf(x.a), rankOf(x.d)]));
export const activePlayers = g => g.hands.map((_, p) => p).filter(p => !g.isOut[p]);

export function nextActive(g, p) {
  for (let i = 1; i <= g.n; i++) {
    const q = (p + i) % g.n;
    if (!g.isOut[q]) return q;
  }
  return p;
}

// Can player p add attack cards right now (ignoring which cards)?
export function canAdd(g, p) {
  const open = g.phase === 'battle' || (g.phase === 'taking' && g.settings.throwInOnTake);
  return open && p !== g.defender && !g.isOut[p] && room(g) > 0;
}

// Which of p's cards could legally go on the table right now?
export function playableAttacks(g, p) {
  if (g.phase === 'opening') return p === g.attacker ? [...g.hands[p]] : [];
  if (!canAdd(g, p)) return [];
  const ranks = tableRanks(g);
  return g.hands[p].filter(c => ranks.has(rankOf(c)));
}

// Can p pass the current attack on (perevodnoy)? Returns the cards that would
// do it — same number as the attack, nothing covered yet, and the next player
// holds enough cards — or [] if not.
export function transferCards(g, p) {
  if (!g.settings.perevodnoy || g.phase !== 'battle' || p !== g.defender || !g.table.length) return [];
  if (g.table.some(x => x.d != null)) return [];
  const next = nextActive(g, p);
  if (next === p || g.hands[next].length < g.table.length + 1) return [];
  const r = rankOf(g.table[0].a);
  return g.hands[p].filter(c => rankOf(c) === r);
}

// ── game setup ───────────────────────────────────────────────────────────────
export function newGame({ names, seed = Date.now(), settings = {}, now = 0 }) {
  const rng = mulberry32(seed);
  const n = names.length;
  const deck = Array.from({ length: 52 }, (_, i) => i);
  for (let i = deck.length - 1; i > 0; i--) {          // Fisher–Yates shuffle
    const j = Math.floor(rng() * (i + 1));
    [deck[i], deck[j]] = [deck[j], deck[i]];
  }
  // deck[deck.length-1] is the top; deck[0] is the bottom.
  const hands = names.map(() => []);
  for (let k = 0; k < DEFAULTS.handSize; k++) for (let p = 0; p < n; p++) hands[p].push(deck.pop());
  const trumpCard = deck.pop();
  deck.unshift(trumpCard);                              // flipped, slid under the deck

  const S = { ...DEFAULTS, ...settings };
  const m = SPEEDS[S.speed]?.timers ?? 1;
  for (const k of ['openMs', 'defendMs', 'windowMs', 'takeMs']) S[k] = (settings[k] ?? DEFAULTS[k]) * m;
  const g = {
    n, names, seed, rng, settings: S,
    deck, hands, trumpCard, trump: suitOf(trumpCard),
    discard: [], table: [], isOut: names.map(() => false), out: [],
    turn: 0,                        // whose attacking turn this is (the opener)
    skip: names.map(() => false),   // picked up → skips their next turn
    passed: [],                     // non-defenders done adding in this window
    phase: 'opening', attacker: 0, defender: 1, cap: 0, deadline: null,
    version: 0, bout: 0, events: [], fool: null, winners: null,
  };

  let lead = -1, low = 99;
  hands.forEach((h, p) => h.forEach(c => {
    if (suitOf(c) === g.trump && rankOf(c) < low) { low = rankOf(c); lead = p; }
  }));
  if (lead < 0) lead = Math.floor(rng() * n);
  startBout(g, lead, now);
  log(g, now, 'lead', lead);
  return g;
}

function log(g, t, kind, p, extra = {}) { g.events.push({ t, kind, p, ...extra }); }

function startBout(g, attacker, now) {
  g.turn = attacker;
  g.attacker = attacker;
  g.passed = [];
  g.defender = nextActive(g, attacker);
  g.table = [];
  g.cap = g.hands[g.defender].length;
  g.phase = 'opening';
  g.deadline = now + g.settings.openMs;
  g.bout++;
}

// ── moves ────────────────────────────────────────────────────────────────────
// Actions:
//   { type: 'attack', p, cards: [..] }   open, or add to an open battle
//   { type: 'defend', p, i, card }       cover table[i] with card
//   { type: 'take',   p }                defender gives up and picks up
//   { type: 'transfer', p, cards: [..] } perevodnoy: pass the attack to the next player
//   { type: 'pass',   p }                done adding cards in this throw-in window
// Returns { ok: true } or { ok: false, why }.
export function apply(g, act, now) {
  const r = applyInner(g, act, now);
  if (r.ok) {
    if (act.type !== 'pass' && g.phase !== 'opening') g.passed = [];   // the table changed: everyone reconsiders
    g.version++;
  }
  return r;
}

// Is a throw-in window open (everything covered, or the defender is picking up)?
export const windowOpen = g =>
  (g.phase === 'battle' && g.table.length > 0 && uncovered(g) === 0) || g.phase === 'taking';

// Everyone who could still add something, other than `except`, has passed.
export function othersPassed(g, except) {
  return activePlayers(g).every(q => q === g.defender || q === except || g.hands[q].length === 0 || g.passed.includes(q));
}

// The next attacking turn after `from`, clockwise, skipping (once) anyone who picked up.
function nextTurn(g, from) {
  let q = from;
  for (let i = 0; i < 2 * g.n; i++) {
    q = nextActive(g, q);
    if (g.skip[q]) { g.skip[q] = false; continue; }
    return q;
  }
  return nextActive(g, from);
}

function applyInner(g, act, now) {
  if (g.phase === 'over') return no('game over');
  const { p } = act;
  const hand = g.hands[p];
  if (!hand || g.isOut[p]) return no('not in the game');

  if (act.type === 'attack') {
    const cards = act.cards ?? [];
    if (!cards.length || new Set(cards).size !== cards.length) return no('bad cards');
    if (!cards.every(c => hand.includes(c))) return no('not your card');
    if (cards.length > room(g)) return no('defender cannot hold that many');

    if (g.phase === 'opening') {
      if (p !== g.attacker) return no('not your attack');
      if (!cards.every(c => rankOf(c) === rankOf(cards[0]))) return no('opening cards must share a number');
      playToTable(g, p, cards);
      g.phase = 'battle';
      g.deadline = now + g.settings.defendMs;
      log(g, now, 'attack', p, { cards });
      return ok();
    }

    if (!canAdd(g, p)) return no('cannot add now');
    const ranks = tableRanks(g);
    if (!cards.every(c => ranks.has(rankOf(c)))) return no('number not on the table');
    playToTable(g, p, cards);
    log(g, now, 'attack', p, { cards });
    if (g.phase === 'battle') g.deadline = now + g.settings.defendMs;   // defender's clock resets
    else if (room(g) === 0) resolve(g, now, false);                     // taking, and the pile is full
    return ok();
  }

  if (act.type === 'defend') {
    if (g.phase !== 'battle' || p !== g.defender) return no('not defending');
    const slot = g.table[act.i];
    if (!slot || slot.d != null) return no('nothing to cover there');
    if (!hand.includes(act.card)) return no('not your card');
    if (!beats(act.card, slot.a, g.trump)) return no('does not beat it');
    hand.splice(hand.indexOf(act.card), 1);
    slot.d = act.card;
    log(g, now, 'defend', p, { card: act.card, i: act.i });
    if (uncovered(g) === 0) {
      if (room(g) === 0 || !anyoneCanAdd(g)) resolve(g, now, true);
      else g.deadline = now + g.settings.windowMs;
    }
    return ok();
  }

  if (act.type === 'transfer') {
    const cards = act.cards ?? [];
    const allowed = transferCards(g, p);
    if (!cards.length || new Set(cards).size !== cards.length || !cards.every(c => allowed.includes(c))) return no('cannot pass that on');
    const next = nextActive(g, p);
    if (g.hands[next].length < g.table.length + cards.length) return no('next player has too few cards');
    playToTable(g, p, cards);
    g.attacker = p;
    g.defender = next;
    g.cap = g.hands[next].length;
    g.deadline = now + g.settings.defendMs;
    log(g, now, 'transfer', p, { cards, to: next });
    return ok();
  }

  if (act.type === 'pass') {
    if (!windowOpen(g) || p === g.defender) return no('nothing to pass on');
    if (g.passed.includes(p)) return no('already passed');
    g.passed.push(p);
    log(g, now, 'done', p);
    if (othersPassed(g, -1)) resolve(g, now, g.phase === 'battle');
    return ok();
  }

  if (act.type === 'take') {
    if (g.phase !== 'battle' || p !== g.defender) return no('not defending');
    if (uncovered(g) === 0) return no('everything is covered');
    startTaking(g, now);
    return ok();
  }
  return no('unknown action');
}

const ok = () => ({ ok: true });
const no = why => ({ ok: false, why });

function playToTable(g, p, cards) {
  for (const c of cards) {
    g.hands[p].splice(g.hands[p].indexOf(c), 1);
    g.table.push({ a: c, d: null, by: p });
  }
}

// Does any non-defender still have cards? (Deliberately not "has a matching
// card" — that would leak information through how fast the bout ends.)
function anyoneCanAdd(g) {
  return activePlayers(g).some(q => q !== g.defender && g.hands[q].length > 0);
}

function startTaking(g, now) {
  log(g, now, 'take', g.defender);
  if (g.settings.throwInOnTake && room(g) > 0 && anyoneCanAdd(g)) {
    g.phase = 'taking';
    g.deadline = now + g.settings.takeMs;
  } else {
    resolve(g, now, false);
  }
}

// ── the clock ────────────────────────────────────────────────────────────────
// Call often with the current time. Returns true if anything happened.
export function tick(g, now) {
  if (g.phase === 'over' || g.deadline == null || now < g.deadline) return false;
  if (g.phase === 'opening') {
    log(g, now, 'pass', g.attacker);
    startBout(g, nextTurn(g, g.turn), now);
  } else if (g.phase === 'battle') {
    if (uncovered(g) > 0) startTaking(g, now);   // timed out = picks up
    else resolve(g, now, true);
  } else if (g.phase === 'taking') {
    resolve(g, now, false);
  }
  g.version++;
  return true;
}

// ── end of a bout ────────────────────────────────────────────────────────────
function resolve(g, now, defended) {
  const cards = g.table.flatMap(x => x.d == null ? [x.a] : [x.a, x.d]);
  if (defended) g.discard.push(...cards);
  else g.hands[g.defender].push(...cards);
  g.table = [];
  log(g, now, defended ? 'beaten' : 'pickup', g.defender, { cards });

  drawUp(g);

  if (g.deck.length === 0) {
    const leaving = activePlayers(g).filter(q => g.hands[q].length === 0);
    if (leaving.length) {
      leaving.forEach(q => { g.isOut[q] = true; log(g, now, 'out', q); });
      g.out.push(leaving);
    }
  }

  const left = activePlayers(g);
  if (left.length <= 1) {
    g.phase = 'over';
    g.deadline = null;
    g.fool = left.length ? left[0] : null;     // null = everyone went out at once: no durak
    g.winners = g.out[0] ?? [];
    log(g, now, 'over', g.fool);
    return;
  }

  // The turn moves on clockwise from whoever opened this attack. (Without any
  // deflection that's the defender — or, if they picked up, the player after.)
  if (!defended) g.skip[g.defender] = true;
  startBout(g, nextTurn(g, g.turn), now);
}

// Round-robin refill: whoever opened the attack, the others clockwise, defender last.
export function drawOrder(g) {
  const order = [];
  let q = g.turn;
  for (let i = 0; i < g.n; i++, q = (q + 1) % g.n) if (!g.isOut[q] && q !== g.defender) order.push(q);
  if (!g.isOut[g.defender]) order.push(g.defender);
  return order;
}

function drawUp(g) {
  const order = drawOrder(g);
  const size = g.settings.handSize;
  let dealt = true;
  while (g.deck.length && dealt) {
    dealt = false;
    for (const q of order) {
      if (g.deck.length && g.hands[q].length < size) { g.hands[q].push(g.deck.pop()); dealt = true; }
    }
  }
}

// ── what a single player is allowed to see ───────────────────────────────────
export function viewFor(g, p) {
  return {
    me: p, n: g.n, hand: [...g.hands[p]], counts: g.hands.map(h => h.length),
    table: g.table.map(x => ({ ...x })), trump: g.trump, trumpCard: g.trumpCard,
    deckCount: g.deck.length, discard: [...g.discard], isOut: [...g.isOut],
    phase: g.phase, attacker: g.attacker, defender: g.defender, cap: g.cap,
    turn: g.turn, passed: [...g.passed],
    settings: g.settings,
  };
}
