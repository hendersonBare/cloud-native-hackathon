import test, { describe, it, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { ORGS, PEOPLE, VIEWS } from '../app/data.js';
import {
  AGENT_ORGS, directoryFromGateway, directoryFromLocal, filterPeople, initialsOf, metIds, sortPeople,
  suggestionsFor, toneFor, withZone,
} from '../app/people-model.js';

import { mockResearchFor } from '../app/mock-research.js';

const RESEARCH = JSON.parse(readFileSync(new URL('../mock/demo-research.json', import.meta.url), 'utf8'));
const localDirectory = directoryFromLocal(PEOPLE, ORGS);
const byId = (id) => localDirectory.find((p) => p.id === id);

test('AGENT_ORGS lists the two companies that run agents', () => {
  assert.deepEqual([...AGENT_ORGS], ['acme', 'bluefin']);
});

test('initialsOf handles single names, full names and empty input', () => {
  assert.equal(initialsOf('Ava'), 'A');
  assert.equal(initialsOf('  ava chen '), 'AC');
  assert.equal(initialsOf('Maria de la Cruz'), 'MC');
  assert.equal(initialsOf(''), '?');
  assert.equal(initialsOf(null), '?');
});

test('toneFor is stable and always one of the four tones', () => {
  const tones = new Set(['gold', 'steel', 'sage', 'lilac']);
  for (const id of Object.keys(PEOPLE)) {
    assert.equal(toneFor(id), toneFor(id));
    assert.ok(tones.has(toneFor(id)), id);
  }
  assert.equal(toneFor('acme.ava'), toneFor('acme.ava'));
  assert.ok(new Set(Object.keys(PEOPLE).map(toneFor)).size > 1, 'ids spread across tones');
});

test('directoryFromLocal keeps the data.js shape and adds agent and interests', () => {
  assert.equal(localDirectory.length, Object.keys(PEOPLE).length);
  const ava = byId('acme.ava');
  assert.deepEqual(ava, {
    id: 'acme.ava', name: 'Ava', initials: 'A', tone: 'gold', org: 'acme', title: 'Solutions Engineer',
    lang: 'en', orgName: 'Acme Observability', role: 'Solutions Engineer · Acme Observability',
    agent: true, interests: [],
  });
  assert.equal(byId('bluefin.bo').agent, true);
  assert.equal(byId('bluefin.bo').lang, 'es');
  assert.equal(byId('kestrel.mia').agent, false);
  assert.equal(byId('lumenly.priya').orgName, 'Lumenly Energy');
});

test('directoryFromLocal adds interests from the extra map and tolerates missing orgs', () => {
  const directory = directoryFromLocal(PEOPLE, ORGS, { interests: { 'kestrel.mia': ['ebpf', 7] } });
  assert.deepEqual(directory.find((p) => p.id === 'kestrel.mia').interests, ['ebpf']);
  const orphan = directoryFromLocal({ 'x.y': { id: 'x.y', name: 'Yan', org: 'ghost', title: 'Dev', lang: 'fr' } }, {});
  assert.equal(orphan[0].orgName, '');
  assert.equal(orphan[0].role, 'Dev');
  assert.equal(orphan[0].lang, 'en');
  assert.equal(orphan[0].initials, 'Y');
  assert.equal(orphan[0].tone, toneFor('x.y'));
});

const GATEWAY = {
  orgs: [
    { org_id: 'acme', name: 'Acme Observability', agents_enabled: true },
    { org_id: 'kestrel', name: 'Kestrel Robotics', agents_enabled: false },
  ],
  personas: [
    { persona_id: 'acme.ava', org_id: 'acme', name: 'Ava', title: 'Solutions Engineer', language: 'en', interests: ['ebpf'] },
    { persona_id: 'kestrel.mia', org_id: 'kestrel', name: 'Mia', title: 'Platform Engineer', language: 'es' },
    { persona_id: 'newco.zed', org_id: 'newco', name: 'Zed Quinn', title: 'CTO', language: 'en', interests: ['security'] },
  ],
};

test('directoryFromGateway maps orgs, agents, language and interests', () => {
  const directory = directoryFromGateway(GATEWAY);
  assert.equal(directory.length, 3);
  assert.deepEqual(directory[0], {
    id: 'acme.ava', name: 'Ava', initials: 'A', tone: toneFor('acme.ava'), org: 'acme', title: 'Solutions Engineer',
    lang: 'en', orgName: 'Acme Observability', role: 'Solutions Engineer · Acme Observability',
    agent: true, interests: ['ebpf'],
  });
  assert.equal(directory[1].agent, false);
  assert.equal(directory[1].lang, 'es');
  assert.deepEqual(directory[1].interests, []);
});

test('directoryFromGateway handles unknown orgs, full names and missing input', () => {
  const zed = directoryFromGateway(GATEWAY).find((p) => p.id === 'newco.zed');
  assert.equal(zed.orgName, '');
  assert.equal(zed.agent, false);
  assert.equal(zed.initials, 'ZQ');
  assert.equal(zed.role, 'CTO');
  assert.deepEqual(directoryFromGateway(), []);
  assert.deepEqual(directoryFromGateway({ orgs: [], personas: [] }), []);
});

test('directoryFromGateway reuses the local avatar tone and initials through known', () => {
  const known = { 'acme.ava': { tone: 'lilac', initials: 'AV' } };
  const ava = directoryFromGateway({ ...GATEWAY, known })[0];
  assert.equal(ava.tone, 'lilac');
  assert.equal(ava.initials, 'AV');
});

test('suggestionsFor ranks research cards by match score and keeps the best three', () => {
  const suggestions = suggestionsFor('acme.ava', { research: RESEARCH, view: VIEWS['acme.ava'], directory: localDirectory });
  assert.deepEqual(suggestions.map((s) => s.id), ['bluefin.bo', 'lumenly.priya', 'kestrel.mia']);
  assert.deepEqual(suggestions.map((s) => s.score), [86, 72, 64]);
  assert.match(suggestions[0].why, /zero-code tracing/);
  assert.deepEqual(suggestions[0].shared, ['ebpf', 'kubernetes']);
  assert.equal(suggestions[0].agent, true);
  assert.equal(suggestions[1].agent, false);
  assert.equal(suggestions[1].talks.length, 1);
  assert.equal(suggestions[1].talks[0].talk_id, 'talk-ebpf-cost');
});

test('suggestionsFor sorts an unsorted research result and does not mutate it', () => {
  const research = {
    persona_id: 'acme.ava',
    cards: [
      { persona_id: 'kestrel.mia', match_score: 40, why_meet: 'a', shared_interests: [], agent_available: false, their_talks: [] },
      { persona_id: 'bluefin.bo', match_score: 90, why_meet: 'b', shared_interests: [], agent_available: true, their_talks: [] },
    ],
  };
  const before = JSON.stringify(research);
  const ids = suggestionsFor('acme.ava', { research, directory: localDirectory }).map((s) => s.id);
  assert.deepEqual(ids, ['bluefin.bo', 'kestrel.mia']);
  assert.equal(JSON.stringify(research), before);
});

test('suggestionsFor falls back to views.json opportunities with a null score', () => {
  const suggestions = suggestionsFor('acme.ava', { view: VIEWS['acme.ava'], directory: localDirectory });
  assert.deepEqual(suggestions.map((s) => s.id), ['kestrel.mia', 'bluefin.bo', 'harborline.lena']);
  assert.ok(suggestions.every((s) => s.score === null));
  assert.equal(suggestions[0].why, 'Low-overhead tracing at the edge');
  assert.deepEqual(suggestions[0].shared, ['Edge tracing', 'Small clusters']);
  assert.equal(suggestions[1].agent, true);
  assert.deepEqual(suggestions[0].talks, []);
});

test('suggestionsFor ignores research made for another persona', () => {
  const suggestions = suggestionsFor('bluefin.bo', { research: RESEARCH, view: VIEWS['bluefin.bo'], directory: localDirectory });
  assert.ok(suggestions.length > 0);
  assert.ok(suggestions.every((s) => s.score === null));
  assert.ok(suggestions.every((s) => s.id !== 'bluefin.bo'));
});

test('mockResearchFor returns the deck computed for each viewer, and null for others', () => {
  assert.deepEqual(mockResearchFor('acme.ava'), RESEARCH);
  assert.equal(mockResearchFor('bluefin.bo').persona_id, 'bluefin.bo');
  assert.equal(mockResearchFor('kestrel.mia'), null);
  assert.equal(mockResearchFor(undefined), null);
});

test("Bo's mock deck uses the contract card shape, real people and no one from Bluefin", () => {
  const bo = mockResearchFor('bluefin.bo');
  const keys = Object.keys(RESEARCH.cards[0]).sort();
  for (const card of bo.cards) {
    assert.deepEqual(Object.keys(card).sort(), keys, card.persona_id);
    assert.ok(byId(card.persona_id), `${card.persona_id} is in the directory`);
    assert.notEqual(card.org_id, 'bluefin');
    assert.equal(card.agent_available, AGENT_ORGS.includes(card.org_id), card.persona_id);
    assert.ok(Number.isInteger(card.match_score) && card.match_score >= 0 && card.match_score <= 100);
  }
});

test("Bo's suggestions come from his own deck, with scores", () => {
  const suggestions = suggestionsFor('bluefin.bo', {
    research: mockResearchFor('bluefin.bo'), view: VIEWS['bluefin.bo'], directory: localDirectory,
  });
  assert.deepEqual(suggestions.map((s) => s.id), ['acme.ava', 'lumenly.priya', 'tidewater.sofia']);
  assert.deepEqual(suggestions.map((s) => s.score), [86, 74, 68]);
  assert.match(suggestions[0].why, /hospital/);
  assert.equal(suggestions[0].agent, true);
  assert.equal(suggestions[1].talks[0].talk_id, 'talk-ebpf-cost');
});

test('suggestionsFor drops the viewer and ids that are not in the directory', () => {
  const research = {
    persona_id: 'acme.ava',
    cards: [
      { persona_id: 'acme.ava', match_score: 99, why_meet: 'self', shared_interests: [], agent_available: true, their_talks: [] },
      { persona_id: 'ghost.nobody', match_score: 95, why_meet: 'unknown', shared_interests: [], agent_available: true, their_talks: [] },
      { persona_id: 'bluefin.bo', match_score: 50, why_meet: 'ok', shared_interests: [], agent_available: true, their_talks: [] },
    ],
  };
  assert.deepEqual(suggestionsFor('acme.ava', { research, directory: localDirectory }).map((s) => s.id), ['bluefin.bo']);
  const view = { home: { opportunities: [{ id: 'ghost.nobody', topics: ['x'], chips: [] }, { id: 'acme.ava', topics: ['y'], chips: [] }] } };
  assert.deepEqual(suggestionsFor('acme.ava', { view, directory: localDirectory }), []);
});

test('suggestionsFor falls back to views when no research card survives, and accepts a home object', () => {
  const research = { persona_id: 'acme.ava', cards: [{ persona_id: 'ghost.nobody', match_score: 80 }] };
  const suggestions = suggestionsFor('acme.ava', { research, view: VIEWS['acme.ava'].home, directory: localDirectory });
  assert.equal(suggestions.length, 3);
  assert.equal(suggestions[0].id, 'kestrel.mia');
  assert.deepEqual(suggestionsFor('acme.ava'), []);
});

test('metIds uses talking and done encounters but not waiting or declined ones', () => {
  const encounter = (status) => ({ initiator: 'acme.ava', responder: 'bluefin.bo', status });
  assert.deepEqual(metIds('acme.ava', { encounter: encounter('talking') }), ['bluefin.bo']);
  assert.deepEqual(metIds('acme.ava', { encounter: encounter('done') }), ['bluefin.bo']);
  assert.deepEqual(metIds('acme.ava', { encounter: encounter('waiting') }), []);
  assert.deepEqual(metIds('acme.ava', { encounter: encounter('declined') }), []);
  assert.deepEqual(metIds('bluefin.bo', { encounter: encounter('done') }), ['acme.ava']);
  assert.deepEqual(metIds('acme.sam', { encounter: encounter('done') }), []);
  assert.deepEqual(metIds('acme.ava', { encounter: null }), []);
  assert.deepEqual(metIds('acme.ava'), []);
});

test('metIds adds people from non-declined meetings only', () => {
  const events = [
    { kind: 'meeting', status: 'confirmed', persona_id: 'acme.ava', with_persona_ids: ['kestrel.mia'] },
    { kind: 'meeting', status: 'proposed', persona_id: 'acme.ava', with_persona_ids: ['harborline.lena'] },
    { kind: 'meeting', status: 'declined', persona_id: 'acme.ava', with_persona_ids: ['lumenly.priya'] },
    { kind: 'talk', status: 'confirmed', persona_id: 'acme.ava', with_persona_ids: ['tidewater.sofia'] },
    { kind: 'personal', status: 'confirmed', persona_id: 'acme.ava' },
    { kind: 'meeting', status: 'confirmed', persona_id: 'acme.sam', with_persona_ids: ['bluefin.kai'] },
  ];
  assert.deepEqual(metIds('acme.ava', { events }), ['kestrel.mia', 'harborline.lena']);
});

test('metIds de-duplicates across encounter and meetings and never includes the viewer', () => {
  const encounter = { initiator: 'acme.ava', responder: 'bluefin.bo', status: 'done' };
  const events = [
    { kind: 'meeting', status: 'confirmed', with_persona_ids: ['bluefin.bo', 'acme.ava', 'kestrel.mia'] },
    { kind: 'meeting', status: 'proposed', with_persona_ids: ['kestrel.mia'] },
  ];
  assert.deepEqual(metIds('acme.ava', { encounter, events }), ['bluefin.bo', 'kestrel.mia']);
});

const everyone = sortPeople(localDirectory);
const suggestions = suggestionsFor('acme.ava', { view: VIEWS['acme.ava'], directory: localDirectory });
const names = (list) => list.map((p) => p.name);

test('filterPeople with no filters returns everyone in the same order', () => {
  assert.deepEqual(filterPeople(everyone, {}, {}), everyone);
  assert.deepEqual(filterPeople(everyone, { query: '   ' }), everyone);
  assert.notEqual(filterPeople(everyone, {}), everyone, 'returns a new array');
});

test('filterPeople matches name, title, company and interests case-insensitively', () => {
  assert.deepEqual(names(filterPeople(everyone, { query: 'KAI' })), ['Kai']);
  assert.deepEqual(names(filterPeople(everyone, { query: 'security arch' })), ['Kai']);
  assert.deepEqual(names(filterPeople(everyone, { query: 'robotics' })), ['Mia']);
  assert.deepEqual(names(filterPeople(everyone, { query: 'kestrel mia' })), ['Mia']);
  const withInterests = directoryFromLocal(PEOPLE, ORGS, { interests: { 'lumenly.priya': ['eBPF', 'cost'] } });
  assert.deepEqual(names(filterPeople(withInterests, { query: 'EBPF' })), ['Priya']);
  assert.deepEqual(filterPeople(everyone, { query: 'zzz-no-one' }), []);
});

test('filterPeople matches suggestion chips', () => {
  const found = filterPeople(everyone, { query: 'zero-code' }, { suggested: suggestions });
  assert.deepEqual(names(found), ['Bo']);
  assert.deepEqual(filterPeople(everyone, { query: 'zero-code' }, { suggested: ['bluefin.bo'] }), []);
});

test('filterPeople flags: agentOnly, metOnly and suggestedOnly', () => {
  assert.deepEqual(names(filterPeople(everyone, { agentOnly: true })), ['Ava', 'Bo', 'Kai', 'Sam']);
  assert.deepEqual(names(filterPeople(everyone, { metOnly: true }, { met: ['kestrel.mia', 'acme.sam'] })), ['Mia', 'Sam']);
  assert.deepEqual(names(filterPeople(everyone, { metOnly: true }, { met: new Set(['kestrel.mia']) })), ['Mia']);
  assert.deepEqual(filterPeople(everyone, { metOnly: true }, {}), []);
  assert.deepEqual(names(filterPeople(everyone, { suggestedOnly: true }, { suggested: suggestions })), ['Bo', 'Lena', 'Mia']);
  assert.deepEqual(names(filterPeople(everyone, { suggestedOnly: true }, { suggested: ['acme.sam'] })), ['Sam']);
});

test('filterPeople combines query and flags with AND', () => {
  const context = { met: ['kestrel.mia', 'bluefin.bo'], suggested: suggestions };
  assert.deepEqual(names(filterPeople(everyone, { agentOnly: true, metOnly: true }, context)), ['Bo']);
  assert.deepEqual(names(filterPeople(everyone, { agentOnly: true, suggestedOnly: true }, context)), ['Bo']);
  assert.deepEqual(names(filterPeople(everyone, { metOnly: true, suggestedOnly: true, query: 'rob' }, context)), ['Mia']);
  assert.deepEqual(filterPeople(everyone, { agentOnly: true, query: 'robotics' }, context), []);
});

test('sortPeople is alphabetical, stable on ties, and does not mutate its input', () => {
  const input = [
    { id: 'b.2', name: 'bo' }, { id: 'a.1', name: 'Zoe' }, { id: 'a.2', name: 'Bo' }, { id: 'c.3', name: 'Ada' },
  ];
  const before = JSON.stringify(input);
  assert.deepEqual(sortPeople(input).map((p) => p.id), ['c.3', 'a.2', 'b.2', 'a.1']);
  assert.equal(JSON.stringify(input), before);
  assert.deepEqual(sortPeople(), []);
  assert.deepEqual(names(everyone), [...names(localDirectory)].sort((a, b) => a.localeCompare(b)));
});

test('withZone adds the conference zone to bare clock times only', () => {
  const noon = '2026-11-09T21:30:00Z';
  assert.equal(withZone('Speaking at 2:30 PM; say hi', noon), 'Speaking at 2:30 PM MST; say hi');
  assert.equal(withZone('Talk at 9am and 4:15 p.m.', noon), 'Talk at 9am MST and 4:15 p.m. MST');
  assert.equal(withZone('Talk at 2:30 PM MST', noon), 'Talk at 2:30 PM MST');
  assert.equal(withZone('Talk at 2:30 PM Mountain Time', noon), 'Talk at 2:30 PM Mountain Time');
  assert.equal(withZone('No time here', noon), 'No time here');
  assert.equal(withZone(null), '');
  assert.match(withZone('At 3 PM', '2026-06-09T21:30:00Z'), /^At 3 PM MDT$/);
});

test('suggestions never show a talk time without its zone', () => {
  const [priya] = suggestionsFor('acme.ava', {
    research: { ...RESEARCH, cards: RESEARCH.cards.filter((c) => c.persona_id === 'lumenly.priya') },
    directory: localDirectory,
  });
  assert.match(priya.why, /2:30 PM MST/);
});

// ---------------------------------------------------------------------------------------------------------
// Screens, on a small fake DOM (the same approach as flow.test.mjs, with the extras these screens use)
// ---------------------------------------------------------------------------------------------------------

const ROOT_KEY = Symbol('root');

class FNode {
  constructor() { this.childNodes = []; this.parent = null; }

  append(...nodes) {
    for (const n of nodes) {
      const node = n instanceof FNode ? n : new FText(String(n));
      node.parent?.childNodes.splice(node.parent.childNodes.indexOf(node), 1);
      node.parent = this;
      this.childNodes.push(node);
    }
  }

  replaceChildren(...nodes) {
    // A browser blurs removed nodes even when the same node is inserted again.
    const active = globalThis.document?.activeElement;
    if (active && active !== this && this.contains(active)) globalThis.document.activeElement = null;
    for (const c of this.childNodes) c.parent = null;
    this.childNodes = [];
    this.append(...nodes);
    dropFocusIfDetached();
  }

  remove() {
    if (!this.parent) return;
    this.parent.childNodes.splice(this.parent.childNodes.indexOf(this), 1);
    this.parent = null;
    dropFocusIfDetached();
  }

  contains(node) {
    for (let x = node; x; x = x.parent) if (x === this) return true;
    return false;
  }

  get isConnected() {
    let x = this;
    while (x.parent) x = x.parent;
    return x[ROOT_KEY] === true;
  }

  get textContent() { return this.childNodes.map((c) => c.textContent).join(''); }

  set textContent(value) {
    for (const c of this.childNodes) c.parent = null;
    this.childNodes = [];
    if (value !== '') this.append(new FText(String(value)));
    dropFocusIfDetached();
  }
}

class FText extends FNode {
  constructor(data) { super(); this.nodeType = 3; this.data = data; }

  get textContent() { return this.data; }

  set textContent(value) { this.data = String(value); }
}

class FElement extends FNode {
  constructor(tag) {
    super();
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.attrs = new Map();
    this.listeners = {};
    this.dataset = {};
    this.style = { setProperty: (k, v) => { this.style[k] = v; } };
    this.hidden = false;
    this.disabled = false;
    this.value = '';
  }

  setAttribute(k, v) { this.attrs.set(k, String(v)); }

  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }

  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }

  click() {
    if (this.disabled || this.attrs.has('disabled')) return;
    for (const fn of this.listeners.click || []) fn({ target: this });
  }

  input(value) {
    this.value = value;
    for (const fn of this.listeners.input || []) fn({ target: this });
  }

  focus() { if (this.isConnected) document.activeElement = this; }

  all(test) {
    const out = [];
    for (const c of this.childNodes) {
      if (c.nodeType !== 1) continue;
      if (test(c)) out.push(c);
      out.push(...c.all(test));
    }
    return out;
  }

  byClass(cls) { return this.all((e) => (e.getAttribute('class') || '').split(' ').includes(cls)); }

  button(text) { return this.all((e) => e.tagName === 'BUTTON' && e.textContent === text)[0] || null; }

  link(text) { return this.all((e) => e.tagName === 'A' && e.textContent === text)[0] || null; }
}

const body = new FElement('body');
body[ROOT_KEY] = true;
const overlay = new FElement('div');
overlay[ROOT_KEY] = true;

function dropFocusIfDetached() {
  const active = globalThis.document?.activeElement;
  if (active && !active.isConnected) globalThis.document.activeElement = null;
}

let fetchCalls = [];
const FAKES = {
  Node: FNode,
  document: {
    activeElement: null,
    body,
    createElement: (tag) => new FElement(tag),
    createElementNS: (_ns, tag) => new FElement(tag),
    createTextNode: (data) => new FText(data),
    getElementById: () => overlay,
  },
  location: { hash: '' },
  window: { addEventListener() {}, removeEventListener() {} },
  setTimeout: () => 0,
  clearTimeout: () => {},
  fetch: async (url) => { fetchCalls.push(String(url)); throw new Error('no network in tests'); },
};
let saved = {};
let person;
let peerOf;
let personScreen;
let peopleScreen;
let MockCalendar;
let announcing;
let warn;

function installFakes() {
  saved = Object.fromEntries(Object.keys(FAKES).map((k) => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
  for (const [k, v] of Object.entries(FAKES)) {
    Object.defineProperty(globalThis, k, { value: v, configurable: true, writable: true });
  }
}

function restoreGlobals() {
  for (const [k, desc] of Object.entries(saved)) {
    if (desc) Object.defineProperty(globalThis, k, desc);
    else delete globalThis[k];
  }
}

const REPLICA_EVENTS = new Set(['calendar:sync', 'calendar:hello']);

function makeBus(self) {
  const listeners = new Map();
  const sent = [];
  const dispatch = (type, data) => {
    for (const fn of [...(listeners.get(type) || [])]) fn(data, { type, data, from: self });
  };
  return {
    sent,
    count: (type) => listeners.get(type)?.size || 0,
    // calendar:sync and calendar:hello belong to the app-lifetime MockCalendar replica, not to a screen
    listenerTotal: () => [...listeners].filter(([type]) => !REPLICA_EVENTS.has(type))
      .reduce((n, [, set]) => n + set.size, 0),
    on(type, fn) {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type).add(fn);
      return () => listeners.get(type)?.delete(fn);
    },
    emitLocal(type, data) { sent.push({ type, data, scope: 'local' }); dispatch(type, data); },
    emit(type, data) { sent.push({ type, data, scope: 'broadcast' }); dispatch(type, data); },
  };
}

const NOW = new Date('2026-11-09T15:00:00Z'); // Mon 8:00 AM MST, the start of the seeded week
const settle = async () => { for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setImmediate(resolve)); };

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const meeting = (over = {}) => ({
  event_id: 'evt-1', persona_id: 'acme.ava', kind: 'meeting', status: 'proposed', title: 'Coffee with Mia',
  with_persona_ids: ['kestrel.mia'], starts_at: '2026-11-10T17:00:00Z', ends_at: '2026-11-10T17:30:00Z',
  responses: { 'acme.ava': 'accepted', 'kestrel.mia': 'pending' }, note: null, ...over,
});

/** A calendar client stub with a controllable propose() and a count of view() calls. */
function stubCalendar({ events = [], propose, respond, viewError } = {}) {
  const calls = { view: 0, propose: [], respond: [] };
  return {
    calls,
    view: async () => {
      calls.view += 1;
      if (viewError) throw viewError;
      return { now: NOW.toISOString(), events };
    },
    propose: (bodyArg) => { calls.propose.push(bodyArg); return propose(); },
    respond: (id, bodyArg) => { calls.respond.push([id, bodyArg]); return respond(); },
  };
}

function mount(screen, { me = 'acme.ava', params = {}, store = {}, calendar, mode = 'mock', name } = {}) {
  body.replaceChildren();
  overlay.replaceChildren();
  FAKES.document.activeElement = null;
  const bus = makeBus(me);
  const cleanups = [];
  const routes = [];
  const ctx = {
    me: person(me), peer: person(peerOf(me)), person, view: VIEWS[me] || {}, store, mode,
    route: { name, params }, go: (n, p) => routes.push([n, p]), bus, overlay,
    onCleanup: (fn) => cleanups.push(fn),
  };
  if (calendar) store.calendarClient = calendar;
  else if (!store.calendarClient) {
    store.calendarClient = announcing(new MockCalendar({ bus, self: me, now: () => NOW }), bus, me);
  }
  const el = screen.render(ctx);
  body.append(el);
  const unmount = () => { for (const fn of cleanups.splice(0)) fn(); };
  return { el, ctx, bus, store, routes, unmount };
}

const mountPerson = (opts = {}) => mount(personScreen, { ...opts, name: 'person' });
const mountPeople = (opts = {}) => mount(peopleScreen, { ...opts, name: 'people' });
const incoming = (from = 'bluefin.bo', to = 'acme.ava') => ({
  request_id: 'req-mock-1', from, to, initiated_by: 'agent',
});

describe('person and people screens', () => {
  before(async () => {
    installFakes();
    warn = console.warn;
    console.warn = () => {};
    ({ person, peerOf } = await import('../app/data.js'));
    ({ MockCalendar } = await import('../app/calendar-mock.js'));
    ({ announcing } = await import('../app/calendar-api.js'));
    personScreen = await import('../app/screens/person.js');
    peopleScreen = await import('../app/screens/people.js');
  });
  after(() => {
    console.warn = warn;
    restoreGlobals();
  });

  describe('incoming connect request', () => {
    it('replaces Connect with Decline and Accept, and Accept answers with ui:respond', () => {
      const s = mountPerson({ params: { id: 'bluefin.bo', request: 'req-mock-1', from: 'request' }, store: { incoming: incoming() } });
      assert.equal(s.el.button('Connect our agents'), null);
      assert.ok(s.el.button('Decline'));
      s.el.button('Accept').click();
      assert.deepEqual(s.bus.sent.filter((m) => m.type === 'ui:respond').map((m) => [m.scope, m.data]),
        [['local', { request_id: 'req-mock-1', accept: true }]]);
      assert.deepEqual(s.routes, []);
    });

    it('Decline answers no and returns home', () => {
      const s = mountPerson({ params: { id: 'bluefin.bo', from: 'request' }, store: { incoming: incoming() } });
      s.el.button('Decline').click();
      assert.deepEqual(s.bus.sent.find((m) => m.type === 'ui:respond').data, { request_id: 'req-mock-1', accept: false });
      assert.deepEqual(s.routes, [['home', undefined]]);
    });

    it('points the back link home, not at the transcript', () => {
      const s = mountPerson({ params: { id: 'bluefin.bo', from: 'request' }, store: { incoming: incoming() } });
      const back = s.el.all((e) => e.getAttribute('aria-label') === 'Back to home')[0];
      assert.equal(back.getAttribute('href'), '#/home');
    });

    it('a request from someone else does not change this brief', () => {
      const s = mountPerson({ params: { id: 'kestrel.mia' }, store: { incoming: incoming() } });
      assert.equal(s.el.button('Accept'), null);
    });

    it('redraws on request:cleared and removes its listeners on unmount', () => {
      const store = { incoming: incoming() };
      const s = mountPerson({ params: { id: 'bluefin.bo' }, store });
      assert.ok(s.el.button('Accept'));
      store.incoming = null;
      s.bus.emitLocal('request:cleared', { request_id: 'req-mock-1' });
      assert.equal(s.el.button('Accept'), null);
      assert.ok(s.el.button('Connect our agents'));
      store.incoming = incoming();
      s.bus.emitLocal('request:incoming', store.incoming);
      assert.ok(s.el.button('Accept'));
      s.unmount();
      assert.equal(s.bus.listenerTotal(), 0);
    });

    it('Connect does nothing while a request from this person is waiting', () => {
      const store = { incoming: incoming() };
      const s = mountPerson({ params: { id: 'bluefin.bo' }, store });
      store.incoming = null;
      s.bus.emitLocal('request:cleared', {});
      store.incoming = incoming();
      s.el.button('Connect our agents')?.click();
      assert.equal(s.bus.sent.filter((m) => m.type === 'ui:connect').length, 0);
    });
  });

  describe('who can be connected', () => {
    it('offers Connect for a person whose company runs an agent', () => {
      const s = mountPerson({ params: { id: 'bluefin.bo' } });
      s.el.button('Connect our agents').click();
      assert.deepEqual(s.bus.sent.find((m) => m.type === 'ui:connect').data,
        { from: 'acme.ava', to: 'bluefin.bo', initiated_by: 'human' });
      assert.deepEqual(s.routes, [['exchange', undefined]]);
    });

    it('offers no Connect when the company runs no agent, but still Find a time', async () => {
      const s = mountPerson({ params: { id: 'kestrel.mia' } });
      await settle();
      assert.equal(s.el.button('Connect our agents'), null);
      assert.match(s.el.byClass('person-no-agent')[0].textContent, /No Rapport agent at Kestrel Robotics/);
      assert.ok(s.el.button('Find a time'));
    });

    it('uses the directory entry over the company list when there is one', () => {
      const directory = [{ ...directoryFromLocal(PEOPLE, ORGS).find((p) => p.id === 'kestrel.mia'), agent: true }];
      const s = mountPerson({ params: { id: 'kestrel.mia' }, store: { people: { directory } } });
      assert.ok(s.el.button('Connect our agents'));
    });
  });

  describe('unknown person', () => {
    it('shows Person not found instead of another person, with no actions', async () => {
      const s = mountPerson({ params: { id: 'kestrel.raj' } });
      await settle();
      assert.equal(s.el.byClass('person-name')[0].textContent, 'Person not found');
      assert.equal(s.el.button('Find a time'), null);
      assert.equal(s.el.button('Connect our agents'), null);
      assert.equal(s.el.link('Open People').getAttribute('href'), '#/people');
    });

    it('finds a person that only the loaded directory knows', () => {
      const directory = [{ id: 'kestrel.raj', name: 'Raj', initials: 'R', tone: 'steel', org: 'kestrel', title: 'SRE', lang: 'en', orgName: 'Kestrel Robotics', role: 'SRE', agent: false, interests: [] }];
      const s = mountPerson({ params: { id: 'kestrel.raj' }, store: { people: { directory } } });
      assert.equal(s.el.byClass('person-name')[0].textContent, 'Raj');
    });

    it('with no id at all it still shows the peer', () => {
      const s = mountPerson({ params: {} });
      assert.equal(s.el.byClass('person-name')[0].textContent, 'Bo');
    });
  });

  describe("Bo's research-backed briefs", () => {
    it("briefs Bo on Priya from Bo's own mock deck, in Spanish", () => {
      const s = mountPerson({ me: 'bluefin.bo', params: { id: 'lumenly.priya' } });
      const text = s.el.textContent;
      assert.equal(s.el.byClass('person-name')[0].textContent, 'Priya');
      assert.match(text, /Head of Infrastructure, Lumenly Energy/);
      assert.match(text, /Runs a lean platform team; wants cheaper visibility/);
      assert.match(text, /Speaking: Cutting the cloud bill with eBPF · .*2:30 PM MST/);
      const reasons = s.el.byClass('person-reasons')[0];
      assert.equal(reasons.getAttribute('lang'), 'es');
      const items = reasons.byClass('person-reason').map((e) => e.textContent);
      assert.match(items[0], /^Priya habla sobre ahorro de costos con eBPF a las 2:30 PM MST/);
      assert.equal(items[1], 'Intereses en común: kubernetes, ebpf, cost');
      assert.doesNotMatch(text, /Compare notes with|Conoce la perspectiva/, 'not the generic fallback brief');
    });

    it("uses neither viewer's deck for the other", () => {
      const s = mountPerson({ me: 'acme.ava', params: { id: 'tidewater.sofia' } });
      assert.doesNotMatch(s.el.textContent, /Sofia dirige un programa de FinOps/);
      assert.match(s.el.textContent, /Compare notes with Sofia/);
    });
  });

  describe('Find a time', () => {
    it('keeps the same focused button while pending, then focuses the result', async () => {
      const pending = deferred();
      const cal = stubCalendar({ propose: () => pending.promise });
      const s = mountPerson({ params: { id: 'kestrel.mia' }, calendar: cal });
      await settle();
      const button = s.el.button('Find a time');
      button.focus();
      button.click();
      const busy = s.el.all((e) => e.tagName === 'BUTTON' && e.textContent === 'Finding a time…')[0];
      assert.equal(busy, button, 'the button is updated in place, not rebuilt');
      assert.ok(button.isConnected);
      assert.equal(FAKES.document.activeElement, button);
      assert.equal(button.getAttribute('aria-busy'), 'true');
      assert.equal(button.getAttribute('aria-disabled'), 'true');
      button.click();
      assert.equal(cal.calls.propose.length, 1, 'a second press while pending is ignored');

      pending.resolve({ created: true, starts_at: '2026-11-10T17:00:00Z', event: meeting() });
      await settle();
      const notice = s.el.byClass('person-meet-notice')[0];
      assert.match(notice.textContent, /Coffee proposed for Tue 10:00 AM MST · waiting for Mia/);
      assert.equal(FAKES.document.activeElement, notice, 'focus moves to the result');
      assert.deepEqual(cal.calls.propose[0], {
        persona_id: 'acme.ava', with_persona_id: 'kestrel.mia', purpose: 'coffee', duration_minutes: 30,
      });
    });

    it('does not steal focus when the user moved on', async () => {
      const pending = deferred();
      const s = mountPerson({ params: { id: 'kestrel.mia' }, calendar: stubCalendar({ propose: () => pending.promise }) });
      await settle();
      s.el.button('Find a time').click();
      const other = s.el.link('Not now');
      other.focus();
      pending.resolve({ created: true, starts_at: '2026-11-10T17:00:00Z', event: meeting() });
      await settle();
      assert.equal(FAKES.document.activeElement, other);
    });

    it('says so when the meeting already existed (created: false)', async () => {
      const s = mountPerson({ params: { id: 'kestrel.mia' }, calendar: stubCalendar({
        propose: async () => ({ created: false, starts_at: '2026-11-10T17:00:00Z', event: meeting() }),
      }) });
      await settle();
      s.el.button('Find a time').click();
      await settle();
      assert.equal(s.el.byClass('person-meet-notice')[0].textContent, 'Already on your calendar');
    });

    it('shows the 409 message, keeps focus on the button and lets the user retry', async () => {
      const error = Object.assign(new Error('conflict'), { status: 409 });
      const cal = stubCalendar({ propose: async () => { throw error; } });
      const s = mountPerson({ params: { id: 'kestrel.mia' }, calendar: cal });
      await settle();
      const button = s.el.button('Find a time');
      button.focus();
      button.click();
      await settle();
      const alert = s.el.all((e) => e.getAttribute('role') === 'alert')[0];
      assert.equal(alert.textContent, 'No time works for both of you this week.');
      assert.equal(alert.hidden, false);
      assert.equal(FAKES.document.activeElement, button);
      assert.equal(button.getAttribute('aria-disabled'), 'false');
      button.click();
      assert.equal(cal.calls.propose.length, 2);
    });

    it('ignores a result that arrives after the screen was left', async () => {
      const pending = deferred();
      const s = mountPerson({ params: { id: 'kestrel.mia' }, calendar: stubCalendar({ propose: () => pending.promise }) });
      await settle();
      s.el.button('Find a time').click();
      s.unmount();
      pending.resolve({ created: true, starts_at: '2026-11-10T17:00:00Z', event: meeting() });
      await settle();
      assert.equal(s.el.byClass('person-meet-notice').length, 0);
      assert.equal(overlay.childNodes.length, 0, 'no toast from a screen that is gone');
    });

    it('refetches when this calendar changes, but not for another persona', async () => {
      const cal = stubCalendar({ propose: async () => ({}) });
      const s = mountPerson({ params: { id: 'kestrel.mia' }, calendar: cal });
      await settle();
      assert.equal(cal.calls.view, 1);
      s.bus.emitLocal('calendar:changed', { persona_ids: ['bluefin.bo'] });
      await settle();
      assert.equal(cal.calls.view, 1);
      s.bus.emitLocal('calendar:changed', { persona_ids: ['acme.ava'] });
      await settle();
      assert.equal(cal.calls.view, 2);
    });

    it('only an upcoming meeting hides Find a time; the earliest upcoming one is shown', async () => {
      const past = meeting({
        event_id: 'evt-past', title: 'Old coffee', starts_at: '2026-11-08T17:00:00Z', ends_at: '2026-11-08T17:30:00Z',
      });
      const later = meeting({ event_id: 'evt-later', title: 'Later coffee', starts_at: '2026-11-12T17:00:00Z', ends_at: '2026-11-12T17:30:00Z' });
      const soon = meeting({ event_id: 'evt-soon', title: 'Soon coffee' });
      const onlyPast = mountPerson({ params: { id: 'kestrel.mia' }, calendar: stubCalendar({ events: [past] }) });
      await settle();
      assert.ok(onlyPast.el.button('Find a time'));
      const mixed = mountPerson({ params: { id: 'kestrel.mia' }, calendar: stubCalendar({ events: [past, later, soon] }) });
      await settle();
      assert.equal(mixed.el.byClass('person-meet-title')[0].textContent, 'Soon coffee');
      assert.equal(mixed.el.button('Find a time'), null);
    });

    it('a calendar load failure says so in plain words, whatever the status', async () => {
      for (const status of [404, 409, 500]) {
        const s = mountPerson({ params: { id: 'kestrel.mia' }, calendar: stubCalendar({
          viewError: Object.assign(new Error('x'), { status }),
        }) });
        await settle();
        assert.equal(s.el.all((e) => e.getAttribute('role') === 'alert')[0].textContent,
          'Could not load your calendar. Try again.');
      }
    });
  });

  describe('confirming a proposed meeting', () => {
    it('offers Confirm only to a participant whose own answer is pending, and confirms through the calendar', async () => {
      const s = mountPerson({ params: { id: 'bluefin.bo' } });
      await settle();
      assert.match(s.el.byClass('person-meet-status')[0].textContent, /Waiting for you to confirm/);
      const confirm = s.el.button('Confirm');
      confirm.focus();
      confirm.click();
      await settle();
      assert.equal(s.el.byClass('person-meet-notice')[0].textContent, 'You accepted · waiting for Bo');
      assert.equal(s.el.button('Confirm'), null);
      assert.equal(FAKES.document.activeElement, s.el.byClass('person-meet-notice')[0]);
    });

    it('does not offer Confirm when the viewer already accepted', async () => {
      const s = mountPerson({ params: { id: 'kestrel.mia' }, calendar: stubCalendar({ events: [meeting({ note: 'Proposed by your agent · tap to confirm' })] }) });
      await settle();
      assert.equal(s.el.button('Confirm'), null);
      assert.match(s.el.byClass('person-meet-status')[0].textContent, /Waiting for Mia/);
    });

    it('shows a failure and lets the user retry', async () => {
      const error = Object.assign(new Error('x'), { status: 409 });
      const cal = stubCalendar({
        events: [meeting({ responses: { 'acme.ava': 'pending', 'kestrel.mia': 'accepted' } })],
        respond: async () => { throw error; },
      });
      const s = mountPerson({ params: { id: 'kestrel.mia' }, calendar: cal });
      await settle();
      s.el.button('Confirm').click();
      await settle();
      assert.equal(s.el.all((e) => e.getAttribute('role') === 'alert')[0].textContent,
        'That change is not allowed for this event.');
      assert.deepEqual(cal.calls.respond[0], ['evt-1', { persona_id: 'acme.ava', response: 'accept' }]);
      assert.ok(s.el.button('Confirm'));
    });
  });

  describe('People screen', () => {
    const chip = (s, label) => s.el.button(label);

    it('makes no network calls in mock mode', async () => {
      fetchCalls = [];
      const s = mountPeople();
      await settle();
      s.unmount();
      assert.deepEqual(fetchCalls, []);
    });

    it('filter chips show their state with a check, not colour alone, and announce the count', () => {
      const s = mountPeople();
      const announcer = s.el.all((e) => e.getAttribute('role') === 'status' && e.getAttribute('aria-atomic'))[0];
      const total = announcer.textContent;
      assert.match(total, /^\d+ people$/);
      const agents = s.el.all((e) => e.tagName === 'BUTTON' && e.getAttribute('aria-pressed') !== null)
        .find((e) => e.textContent === 'Has an agent');
      assert.equal(agents.getAttribute('aria-pressed'), 'false');
      assert.equal(agents.all((e) => e.tagName === 'SVG').length, 0);
      agents.click();
      assert.equal(agents.getAttribute('aria-pressed'), 'true');
      assert.equal(agents.all((e) => e.tagName === 'SVG').length, 1, 'a check mark joins the label');
      assert.equal(agents.textContent, 'Has an agent');
      assert.equal(announcer.textContent, '3 people');
      agents.click();
      assert.equal(agents.all((e) => e.tagName === 'SVG').length, 0);
      assert.equal(announcer.textContent, total);
    });

    it('Clear search resets the query and every chip', () => {
      const s = mountPeople();
      const input = s.el.all((e) => e.tagName === 'INPUT')[0];
      input.input('zzzz');
      assert.ok(s.el.button('Clear search'));
      s.el.button('Met').click();
      s.el.button('Clear search').click();
      assert.equal(input.value, '');
      for (const label of ['Suggested', 'Has an agent', 'Met']) {
        const pressed = s.el.all((e) => e.tagName === 'BUTTON' && e.textContent === label)[0];
        assert.equal(pressed.getAttribute('aria-pressed'), 'false');
        assert.equal(pressed.all((e) => e.tagName === 'SVG').length, 0);
      }
    });

    it('links each person to their brief and shows talk times with a zone', () => {
      const s = mountPeople();
      const priya = s.el.all((e) => e.tagName === 'A' && (e.getAttribute('href') || '').includes('lumenly.priya'))[0];
      assert.equal(priya.getAttribute('href'), '#/person?id=lumenly.priya&from=people');
      assert.match(priya.getAttribute('aria-label'), /2:30 PM MST/);
      assert.equal(priya.byClass('people-why')[0].textContent.includes('2:30 PM MST'), true);
    });

    it('shows match scores on both phones in mock mode', () => {
      for (const [me, first] of [['acme.ava', 'bluefin.bo'], ['bluefin.bo', 'acme.ava']]) {
        const s = mountPeople({ me, store: {} });
        const cards = s.el.byClass('people-card');
        assert.equal(cards.length, 3, me);
        assert.ok(cards.every((card) => card.byClass('people-score').length === 1), `${me} sees a score on every card`);
        assert.equal(cards[0].getAttribute('href'), `#/person?id=${first}&from=people`);
        assert.equal(cards[0].byClass('people-score')[0].textContent, '86% match');
        s.unmount();
      }
    });

    it('after a failed refresh, says the last suggestions are still shown', async () => {
      const reply = (payload) => ({ ok: true, status: 200, text: async () => JSON.stringify(payload) });
      let researchOk = true;
      const realFetch = globalThis.fetch;
      globalThis.fetch = async (url) => {
        if (String(url).startsWith('/api/personas')) {
          return reply({
            orgs: [{ org_id: 'bluefin', name: 'Bluefin Health', agents_enabled: true }],
            personas: [{ persona_id: 'bluefin.bo', name: 'Bo', title: 'Platform Lead', language: 'es', org_id: 'bluefin', interests: [] }],
          });
        }
        if (!researchOk) return { ok: false, status: 502, text: async () => '' };
        return reply({ persona_id: 'acme.ava', cards: [RESEARCH.cards[0]] });
      };
      try {
        const s = mountPeople({ mode: 'live', store: {} });
        await settle();
        const note = s.el.byClass('people-note')[0];
        assert.equal(note.textContent, '');
        assert.equal(s.el.byClass('people-card').length, 1);
        researchOk = false;
        s.el.button('Refresh suggestions').click();
        await settle();
        assert.equal(note.textContent, 'Could not refresh. Showing your last suggestions.');
        assert.equal(s.el.byClass('people-card').length, 1, 'the earlier cards are still listed');
      } finally {
        globalThis.fetch = realFetch;
      }
    });

    it('with no research at all, a failed refresh points at saved opportunities', async () => {
      const realFetch = globalThis.fetch;
      globalThis.fetch = async (url) => (String(url).startsWith('/api/personas')
        ? { ok: true, status: 200, text: async () => JSON.stringify({ orgs: [], personas: [{ persona_id: 'bluefin.bo', name: 'Bo', title: 'Lead', language: 'en', org_id: 'x', interests: [] }] }) }
        : { ok: false, status: 502, text: async () => '' });
      try {
        const s = mountPeople({ mode: 'live', store: {} });
        await settle();
        assert.match(s.el.byClass('people-note')[0].textContent, /come from your saved opportunities/);
      } finally {
        globalThis.fetch = realFetch;
      }
    });

    it('shows a pending connect request on top and follows request:cleared', () => {
      const store = { incoming: incoming() };
      const s = mountPeople({ store });
      const card = s.el.byClass('people-request')[0];
      assert.match(card.getAttribute('href'), /^#\/person\?/);
      assert.match(card.getAttribute('href'), /id=bluefin\.bo/);
      assert.match(card.getAttribute('href'), /from=request/);
      assert.match(card.textContent, /Bo's agent wants to connect/);
      store.incoming = null;
      s.bus.emitLocal('request:cleared', {});
      assert.equal(s.el.byClass('people-request').length, 0);
      s.unmount();
      assert.equal(s.bus.listenerTotal(), 0);
    });
  });
});

test('withZone leaves a.m./p.m. times that already carry a zone alone', () => {
  const noon = '2026-11-09T19:00:00Z';
  assert.equal(withZone('Talk at 10:00 a.m. MST today', noon), 'Talk at 10:00 a.m. MST today');
  assert.equal(withZone('Free 4:15 p.m. MST, or later', noon), 'Free 4:15 p.m. MST, or later');
  assert.equal(withZone('Talk at 10:00 a.m. today', noon), 'Talk at 10:00 a.m. MST today');
  assert.equal(withZone('Coffee at 9 a.m. Mountain Time', noon), 'Coffee at 9 a.m. Mountain Time');
});
