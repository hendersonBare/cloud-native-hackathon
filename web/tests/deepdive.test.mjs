// Live Discover: a right swipe calls POST /api/swipe (not /api/connect), and the deep dive,
// "Researching…" state and agent decision render on the viewer's phone. initFlow wires live-events.js.
import { after, before, describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { FakeElement, install } from './fake-dom.mjs';

const fixture = JSON.parse(readFileSync(fileURLToPath(new URL('../../contracts/demo-events.json', import.meta.url)), 'utf8'));
const swipePhase = fixture.events.filter((e) => e.phase === 'swipe').map((e) => e.event);
const ofType = (type) => swipePhase.find((e) => e.type === type);

function makeBus() {
  const handlers = new Map();
  const bus = {
    emitted: [],
    on(type, fn) {
      if (!handlers.has(type)) handlers.set(type, new Set());
      handlers.get(type).add(fn);
      return () => handlers.get(type).delete(fn);
    },
    emitLocal(type, data) {
      bus.emitted.push([type, data]);
      for (const fn of handlers.get(type) || []) fn(data, { type, data });
    },
  };
  bus.emit = bus.emitLocal;
  return bus;
}

const text = (node) => node.textContent.replace(/\s+/g, ' ').trim();

describe('live deep dive', () => {
  let restore;
  let person;
  let api;
  let initFlow;
  let render;
  let home;
  before(async () => {
    restore = install();
    FakeElement.prototype.focus = function focus() {};
    globalThis.window = { addEventListener() {}, removeEventListener() {} };
    ({ person } = await import('../app/data.js'));
    ({ api } = await import('../app/api.js'));
    ({ initFlow } = await import('../app/flow.js'));
    ({ render } = await import('../app/screens/deepdive.js'));
    home = await import('../app/screens/home.js');
  });
  after(() => {
    delete FakeElement.prototype.focus;
    delete globalThis.window;
    restore();
  });

  function phone(meId = 'acme.ava') {
    const bus = makeBus();
    const store = { config: { malicious: false } };
    const hashes = [];
    const cleanups = [];
    const calls = { swipe: [], connect: [] };
    api.swipe = async (body) => { calls.swipe.push(body); return null; };
    api.connect = async (body) => { calls.connect.push(body); return { request_id: 'r' }; };
    api.openStream = () => () => {};
    const me = person(meId);
    const flow = initFlow({
      me, peer: person('bluefin.bo'), store, mode: 'live', go: (name, params) => hashes.push([name, params]),
      bus, overlay: new FakeElement('div'),
    });
    const ctx = (route = { name: 'home', params: {} }, mode = 'live') => ({
      me, peer: person('bluefin.bo'), person, view: {}, store, mode, route, go() {}, bus,
      onCleanup: (fn) => cleanups.push(fn),
    });
    return { bus, store, hashes, calls, flow, ctx, cleanups };
  }

  // An envelope as flow.js re-emits it: `gateway:<type>`, data = the full event.
  const gateway = (p, event) => p.bus.emitLocal(`gateway:${event.type}`, event);

  test('ui:swipe right calls /api/swipe with the malicious toggle and autonomy, never /api/connect', () => {
    const p = phone();
    p.store.config.malicious = true;
    p.bus.emitLocal('ui:swipe', { from: 'acme.ava', to: 'bluefin.bo', direction: 'right' });
    assert.deepEqual(p.calls.swipe, [{
      persona_id: 'acme.ava', target_persona_id: 'bluefin.bo', direction: 'right', autonomy: true, malicious: true,
    }]);
    assert.deepEqual(p.calls.connect, []);
    p.flow();
  });

  test('ui:swipe left sends direction left; swipes from another persona are ignored', () => {
    const p = phone();
    p.bus.emitLocal('ui:swipe', { from: 'acme.ava', to: 'lumenly.priya', direction: 'left' });
    p.bus.emitLocal('ui:swipe', { from: 'bluefin.bo', to: 'acme.ava', direction: 'right' });
    p.bus.emitLocal('ui:swipe', { from: 'acme.ava', to: 'bluefin.bo', direction: 'sideways' });
    assert.deepEqual(p.calls.swipe.map((b) => [b.target_persona_id, b.direction]), [['lumenly.priya', 'left']]);
    p.flow();
  });

  test('Home: a live swipe emits ui:swipe (not ui:connect); a mock swipe still emits ui:connect', async () => {
    for (const [mode, expected, absent] of [['live', 'ui:swipe', 'ui:connect'], ['mock', 'ui:connect', 'ui:swipe']]) {
      const p = phone();
      const ctx = p.ctx(undefined, mode);
      ctx.view = (await import('../app/data.js')).VIEWS['acme.ava'];
      const root = home.render(ctx);
      const [card] = root.byClass('opp-card');
      card.listeners.keydown[0]({ target: card, key: 'ArrowRight', preventDefault() {} });
      await new Promise((resolve) => setTimeout(resolve, 300));
      const types = p.bus.emitted.map(([type]) => type);
      assert.ok(types.includes(expected), `${mode} emits ${expected}`);
      assert.ok(!types.includes(absent), `${mode} does not emit ${absent}`);
      for (const fn of p.cleanups) fn();
      p.flow();
    }
  });

  test('deep_dive_started opens the Deep dive screen on Researching…, then deep_dive_ready fills it in', () => {
    const p = phone();
    gateway(p, ofType('deep_dive_started'));
    assert.deepEqual(p.hashes, [['deepdive', { id: 'bluefin.bo' }]]);
    const screen = render(p.ctx({ name: 'deepdive', params: { id: 'bluefin.bo' } }));
    assert.match(text(screen), /Researching Bo…/);

    gateway(p, ofType('deep_dive_ready'));
    const body = text(screen);
    assert.doesNotMatch(body, /Researching/);
    assert.match(body, /Bo runs Bluefin's platform team/);
    for (const part of ['Restart the Bluefin pilot', 'Case study: hospital network', 'Who signs off on HIPAA?',
      'They are also evaluating a competitor', 'Bo, I hear you want tracing without touching 300 services',
      'Bo matches both of your goals', '86% sure', 'target has an agent: yes', 'Call notes: Bluefin pilot (March)']) {
      assert.ok(body.includes(part), part);
    }
    assert.match(body, /Request sent to Bo's agent, waiting for Bo/);
    p.flow();
  });

  test('agent_decision: a handshake never calls /api/connect, human_intro and skip show their text', () => {
    const p = phone();
    const dive = (target, action, reason) => ({
      ...ofType('deep_dive_ready'),
      data: { ...ofType('deep_dive_ready').data, target_persona_id: target, decision: { action, reason, confidence: 0.4, checks: [] } },
    });
    const decide = (target, action, extra = {}) => ({
      ...ofType('agent_decision'), data: { target_persona_id: target, action, ...extra },
    });

    gateway(p, decide('bluefin.bo', 'agent_handshake', { request_id: 'req-01' }));
    assert.deepEqual(p.calls.connect, []);

    gateway(p, dive('lumenly.priya', 'human_intro', 'Catch Priya after their 2:30 PM MST talk in Room A.'));
    gateway(p, decide('lumenly.priya', 'human_intro'));
    let screen = render(p.ctx({ name: 'deepdive', params: { id: 'lumenly.priya' } }));
    assert.match(text(screen), /introducing yourself to Priya/);
    assert.match(text(screen), /Catch Priya after their 2:30 PM MST talk in Room A\./);

    gateway(p, dive('kestrel.mia', 'skip', 'Not a fit for your goals.'));
    gateway(p, decide('kestrel.mia', 'skip'));
    screen = render(p.ctx({ name: 'deepdive', params: { id: 'kestrel.mia' } }));
    assert.match(text(screen), /Not a fit for your goals\./);
    p.flow();
  });

  test('flow.js turns an agent_handshake decision into a waiting encounter carrying the request id', () => {
    const p = phone();
    gateway(p, ofType('agent_decision'));
    assert.deepEqual(
      { ...p.store.encounter },
      { encounter_id: null, initiator: 'acme.ava', responder: 'bluefin.bo', startedAt: null, status: 'waiting', request_id: 'req-01' },
    );
    p.flow();
  });

  test('server strings are rendered as text, never markup', () => {
    const p = phone();
    const evil = { ...ofType('deep_dive_ready'), data: { ...ofType('deep_dive_ready').data, summary: '<img src=x onerror=alert(1)>' } };
    gateway(p, evil);
    const screen = render(p.ctx({ name: 'deepdive', params: { id: 'bluefin.bo' } }));
    assert.equal(screen.findAll((n) => n.tagName === 'IMG').length, 0);
    assert.match(text(screen), /<img src=x/);
    p.flow();
  });
});
