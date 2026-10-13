// sim.js — bots play each other in the terminal, as fast as the CPU allows,
// and every rule is checked after every move. Catches rule bugs before you
// ever sit down at the table.
//
//   node sim.js            10,000 games, 2–6 players
//   node sim.js 500        fewer games

import * as E from './engine.js';
import { Bot, BOT_NAMES } from './bots.js';

const GAMES = Number(process.argv[2] ?? 10000);

// ── 1. a hand-built check of the short-deck refill order ─────────────────────
{
  const g = E.newGame({ names: ['A', 'B', 'C'], seed: 1 });
  // A attacked B; C helped. Deck has 4 left. A needs 2, C needs 2, B (defender) needs 3.
  g.attacker = 0; g.turn = 0; g.defender = 1; g.phase = 'battle';
  g.hands = [[0, 1, 2, 3], [4, 5, 6], [7, 8, 9, 10]];
  g.deck = [11, 12, 13, 14]; g.discard = []; g.table = [];
  const all = new Set([...g.hands.flat(), ...g.deck]);
  for (let c = 0; c < 52; c++) if (!all.has(c)) g.discard.push(c);
  console.log('refill order:', E.drawOrder(g).map(p => g.names[p]).join(' → '));
  // resolve via the clock: everything "covered", window expires
  g.table = []; g.deadline = 0; E.tick(g, 1);
  const got = g.hands.map(h => h.length);
  console.log(`short deck (4 left, needs A2 C2 B3): A→${got[0]} B→${got[1]} C→${got[2]}`,
    got.join() === '6,4,5' ? '✓ defender gets the shortfall' : '✗ WRONG');
}

// ── 2. lots of bot games ─────────────────────────────────────────────────────
function checkInvariants(g) {
  const all = [...g.deck, ...g.discard, ...g.hands.flat(), ...g.table.flatMap(x => x.d == null ? [x.a] : [x.a, x.d])];
  if (all.length !== 52 || new Set(all).size !== 52) throw new Error(`cards not conserved: ${all.length}`);
  if (g.table.length > g.cap) throw new Error('attack cap exceeded');
  for (const x of g.table) if (x.d != null && !E.beats(x.d, x.a, g.trump)) throw new Error('bad defense');
  if (g.phase === 'opening' && g.deck.length > 0)
    for (const p of E.activePlayers(g)) if (g.hands[p].length < 6) throw new Error('did not refill to 6');
  if (g.deck.length && g.deck[0] !== g.trumpCard) throw new Error('trump card left the bottom');
  if (g.phase === 'battle' && E.uncovered(g) > g.hands[g.defender].length) throw new Error('defender cannot cover the pile');
}

const stats = { games: 0, errors: 0, rejected: 0, draws: 0, bouts: 0, seconds: 0, takes: 0, passes: 0, transfers: 0, roundTrips: 0,
  foolWasLead: 0, byN: {} };

for (let s = 1; s <= GAMES; s++) {
  const n = 2 + (s % 5);
  // every other game plays perevodnoy; speeds rotate too
  const settings = { perevodnoy: s % 2 === 0, speed: ['fast', 'normal', 'slow'][s % 3] };
  const g = E.newGame({ names: BOT_NAMES.slice(0, n), seed: s, now: 0, settings });
  const rng = E.mulberry32(s * 7919);
  const bots = g.names.map((_, p) => new Bot(p, {}, rng));
  const lead = g.attacker;
  let t = 0, steps = 0;
  try {
    while (g.phase !== 'over') {
      if (++steps > 200000) throw new Error('game never ended');
      for (const b of bots) { const a = b.update(g, t); if (a) act(g, a, t); }
      const wake = Math.min(g.deadline ?? Infinity, ...bots.map(b => b.actAt ?? Infinity));
      if (wake === Infinity) throw new Error('stuck: nobody to move and no clock');
      t = Math.max(t, wake);
      E.tick(g, t);
      checkInvariants(g);
      for (const b of bots) { const a = b.update(g, t); if (a) act(g, a, t); }
    }
  } catch (e) {
    stats.errors++;
    if (stats.errors <= 5) console.log(`seed ${s} (${n}p):`, e.message);
    continue;
  }
  stats.games++;
  stats.bouts += g.bout;
  stats.seconds += t / 1000;
  stats.takes += g.events.filter(e => e.kind === 'pickup').length;
  stats.passes += g.events.filter(e => e.kind === 'pass').length;
  stats.transfers += g.events.filter(e => e.kind === 'transfer').length;
  // a transfer chain that came all the way back to the player who opened it
  let opener = null;
  for (const e of g.events) {
    if (e.kind === 'attack' && opener == null) opener = e.p;
    if (e.kind === 'transfer' && e.to === opener && n >= 3) stats.roundTrips++;
    if (e.kind === 'beaten' || e.kind === 'pickup') opener = null;
  }
  if (g.fool == null) stats.draws++;
  if (g.fool === lead) stats.foolWasLead++;
  const b = (stats.byN[n] ??= { games: 0, bouts: 0, draws: 0, foolSeat: Array(n).fill(0) });
  b.games++; b.bouts += g.bout;
  if (g.fool == null) b.draws++; else b.foolSeat[(g.fool - lead + n) % n]++;
}

function act(g, a, t) {
  const r = E.apply(g, a, t);
  if (!r.ok) { stats.rejected++; throw new Error(`bot made illegal move ${JSON.stringify(a)}: ${r.why}`); }
  checkInvariants(g);
}

const f = x => x.toFixed(1);
console.log(`\n${stats.games} games finished, ${stats.errors} errors, ${stats.rejected} illegal bot moves`);
console.log(`avg ${f(stats.bouts / stats.games)} bouts, ${f(stats.seconds / stats.games)} s of bot time, ` +
  `${f(stats.takes / stats.games)} pickups, ${f(stats.passes / stats.games)} passes per game`);
console.log(`${f(stats.transfers / (stats.games / 2))} transfers per perevodnoy game; ` +
  `${stats.roundTrips} times (3+ players) an attack travelled all the way back round to the player who opened it`);
console.log(`no durak (last players out together): ${stats.draws}`);
console.log('\nplayers  games  bouts  draws  fool by seat (0 = first attacker, then clockwise)');
for (const [n, b] of Object.entries(stats.byN))
  console.log(`   ${n}     ${String(b.games).padStart(4)}   ${f(b.bouts / b.games).padStart(4)}   ${String(b.draws).padStart(4)}   ` +
    b.foolSeat.map(x => (100 * x / b.games).toFixed(0).padStart(3) + '%').join(' '));
