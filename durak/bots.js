// bots.js — computer players.
//
// A bot only ever looks at viewFor(g, p): its own hand plus what's public on
// the table. Same information a person sitting there would have.
//
// For now every bot plays the same way. Personalities later = give each one
// its own copy of BOT_DEFAULTS with different numbers.

import { rankOf, suitOf, beats, viewFor, SPEEDS } from './engine.js';

export const BOT_NAMES = ['Polina', 'Tobias', 'Gabriel', 'Alexander', 'Luca', 'Greta'];

export const BOT_DEFAULTS = {
  reactMin: 450,          // ms of "thinking" before each move …
  reactMax: 1300,         // … picked at random in this range
  pairBonus: 1.5,         // opening: how much a pair/trio is preferred over a lone card
  lateDeck: 4,            // deck this small or smaller = endgame, trumps get spent
  throwTrumpMaxRank: 9,   // endgame: trumps up to 9 may be thrown into attacks
  giftMaxRank: 11,        // defender is picking up: throw in non-trumps up to J (A/K/Q kept while the deck lasts)
  earlyDeck: 12,          // deck this big or bigger = early game …
  saveTrumpRank: 12,      // … where the bot would rather pick up 1–2 cards than spend a Q+ trump
  endgameShuffle: 6,      // deck empty: random wobble added to each lead option's score
};

export class Bot {
  constructor(p, params = {}, rng = Math.random) {
    this.p = p;
    this.k = { ...BOT_DEFAULTS, ...params };
    this.rng = rng;
    this.seen = -1;       // last game version we reacted to
    this.actAt = null;    // when we'll make our next decision
    this.led = {};        // endgame: how often we've led each number
  }

  // Call every frame. Returns an action to apply, or null.
  update(g, now) {
    if (g.phase === 'over' || g.isOut[this.p]) { this.actAt = null; return null; }
    if (g.version !== this.seen) {                       // something changed: think about it
      this.seen = g.version;
      const pace = SPEEDS[g.settings.speed]?.bots ?? 1;
      this.actAt = now + pace * (this.k.reactMin + this.rng() * (this.k.reactMax - this.k.reactMin));
    }
    if (this.actAt != null && now >= this.actAt) {
      this.actAt = null;
      return this.decide(viewFor(g, this.p));
    }
    return null;
  }

  decide(v) {
    const room = v.cap - v.table.length;
    if (v.phase === 'opening' && v.attacker === v.me) return this.open(v, room);
    if (v.phase === 'battle' && v.defender === v.me) return this.defend(v);
    const adding = v.phase === 'battle' || (v.phase === 'taking' && v.settings.throwInOnTake);
    if (adding && v.defender !== v.me && room > 0 && v.hand.length) {
      const t = this.throwIn(v, room);
      if (t) return t;
    }
    // Nothing (more) to add while the window is closing: say so, so it can close early.
    const closing = (v.phase === 'battle' && v.table.length && v.table.every(x => x.d != null)) || v.phase === 'taking';
    if (closing && v.defender !== v.me && v.hand.length && !v.passed.includes(v.me)) return { type: 'pass', p: v.me };
    return null;
  }

  // Lead with the cheapest number, preferring to unload pairs/trios; trumps last.
  open(v, room) {
    const late = v.deckCount <= this.k.lateDeck;
    const byRank = new Map();
    for (const c of v.hand) byRank.set(rankOf(c), [...(byRank.get(rankOf(c)) ?? []), c]);
    let best = null;
    for (const [r, cards] of byRank) {
      const plain = cards.filter(c => suitOf(c) !== v.trump);
      let play, score;
      if (plain.length) { play = plain; score = r - this.k.pairBonus * (plain.length - 1); }
      else { play = [cards[0]]; score = r + (late ? 6 : 13); }
      if (late) { play = cards; score = r - this.k.pairBonus * (cards.length - 1) + (plain.length ? 0 : 6); }
      // Endgame: sometimes lead something else, or three bots can pass the same
      // cards around in a circle forever (each one picking up what it can't beat).
      // Leading the same number again and again gets boring, for people and bots.
      if (v.deckCount === 0) score += this.rng() * this.k.endgameShuffle + 4 * (this.led[r] ?? 0);
      if (!best || score < best.score) best = { play, score, r };
    }
    if (v.deckCount === 0) this.led[best.r] = (this.led[best.r] ?? 0) + 1;
    return { type: 'attack', p: v.me, cards: best.play.slice(0, room) };
  }

  // Pile on: throw in every matching card that isn't too precious.
  throwIn(v, room) {
    const late = v.deckCount <= this.k.lateDeck;
    const ranks = new Set(v.table.flatMap(x => x.d == null ? [rankOf(x.a)] : [rankOf(x.a), rankOf(x.d)]));
    const cards = v.hand
      .filter(c => ranks.has(rankOf(c)))
      .filter(c => {
        const trump = suitOf(c) === v.trump;
        if (trump) return late && rankOf(c) <= this.k.throwTrumpMaxRank;
        if (v.phase === 'taking' && v.deckCount > 0) return rankOf(c) <= this.k.giftMaxRank;
        return true;
      })
      .sort((a, b) => this.val(a, v) - this.val(b, v))
      .slice(0, room);
    return cards.length ? { type: 'attack', p: v.me, cards } : null;
  }

  // Pass it on if we can do that cheaply (perevodnoy). Otherwise cover the
  // hardest attacks with the cheapest cards that beat them; pick up if that's
  // impossible, or if it would burn a big trump early on a small battle.
  defend(v) {
    const open = v.table.map((x, i) => ({ ...x, i })).filter(x => x.d == null);
    if (!open.length) return null;
    const pass = this.transfer(v);
    if (pass) return pass;
    open.sort((a, b) => this.val(b.a, v) - this.val(a.a, v));
    const avail = [...v.hand].sort((a, b) => this.val(a, v) - this.val(b, v));
    const plan = [];
    for (const x of open) {
      const j = avail.findIndex(c => beats(c, x.a, v.trump));
      if (j < 0) return { type: 'take', p: v.me };
      plan.push({ i: x.i, card: avail[j] });
      avail.splice(j, 1);
    }
    const early = v.deckCount >= this.k.earlyDeck;
    const bigTrump = plan.some(m => suitOf(m.card) === v.trump && rankOf(m.card) >= this.k.saveTrumpRank);
    if (early && bigTrump && v.table.length <= 2) return { type: 'take', p: v.me };
    return { type: 'defend', p: v.me, i: plan[0].i, card: plan[0].card };
  }

  transfer(v) {
    if (!v.settings.perevodnoy || v.table.some(x => x.d != null)) return null;
    let next = v.me;
    do next = (next + 1) % v.n; while (v.isOut[next] && next !== v.me);
    const room = v.counts[next] - v.table.length;
    if (next === v.me || room < 1) return null;
    const r = rankOf(v.table[0].a);
    const same = v.hand.filter(c => rankOf(c) === r).sort((a, b) => this.val(a, v) - this.val(b, v));
    const plain = same.filter(c => suitOf(c) !== v.trump);
    // Plain cards: always worth passing on (it sheds cards and dodges the fight).
    if (plain.length) return { type: 'transfer', p: v.me, cards: plain.slice(0, room) };
    // Only a trump would do it: spend it if we couldn't defend anyway, or it's the endgame.
    if (same.length && (v.deckCount <= this.k.lateDeck || !this.canCoverAll(v)))
      return { type: 'transfer', p: v.me, cards: [same[0]] };
    return null;
  }

  canCoverAll(v) {
    const avail = [...v.hand];
    for (const x of v.table.filter(x => x.d == null).sort((a, b) => this.val(b.a, v) - this.val(a.a, v))) {
      const j = avail.filter(c => beats(c, x.a, v.trump)).sort((a, b) => this.val(a, v) - this.val(b, v))[0];
      if (j == null) return false;
      avail.splice(avail.indexOf(j), 1);
    }
    return true;
  }

  val(c, v) { return rankOf(c) + (suitOf(c) === v.trump ? 13 : 0); }
}
