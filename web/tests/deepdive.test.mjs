// Discover: with a gateway a right swipe calls POST /api/swipe (not /api/connect); without one the
// same events are replayed from the demo script. The and the deep dive,
// deep dive, "Researching…" state and agent decision render on the viewer's phone. initFlow wires live-events.js.
import { after, before, describe, mock, test } from 'node:test';
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

describe('deep dive', () => {
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

  function phone(meId = 'acme.ava', mode = 'live') {
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
      me, peer: person('bluefin.bo'), store, mode, go: (name, params) => hashes.push([name, params]),
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

  test('Home: a swipe always emits ui:swipe and never connects directly; flow.js decides what follows', async () => {
    for (const mode of ['live', 'mock']) {
      const p = phone();
      try {
        const ctx = p.ctx(undefined, mode);
        ctx.view = (await import('../app/data.js')).VIEWS['acme.ava'];
        const root = home.render(ctx);
        const [card] = root.byClass('opp-card');
        card.listeners.keydown[0]({ target: card, key: 'ArrowRight', preventDefault() {} });
        await new Promise((resolve) => setTimeout(resolve, 300));
        const types = p.bus.emitted.map(([type]) => type);
        assert.ok(types.includes('ui:swipe'), `${mode}: Home emits ui:swipe`);
        assert.ok(!types.includes('ui:connect'), `${mode}: Home never emits ui:connect itself`);
      } finally {
        for (const fn of p.cleanups) fn();
        p.flow();
      }
    }
  });

  // No gateway answering: the same screens are fed from the demo script (demo-script.js).
  test('without a gateway, a right swipe on Bo replays the deep dive, the decision and the agent request', () => {
    mock.timers.enable({ apis: ['setTimeout'] });
    const p = phone('acme.ava', 'mock');
    try {
      p.bus.emitLocal('ui:swipe', { from: 'acme.ava', to: 'bluefin.bo', direction: 'right' });
      assert.deepEqual(p.hashes, [], 'nothing happens before the script starts');
      mock.timers.tick(1000);
      assert.deepEqual(p.hashes, [['deepdive', { id: 'bluefin.bo' }]]);
      mock.timers.tick(2600);
      assert.ok(p.store.gateway.deepDives['bluefin.bo'], 'the deep dive is ready');
      assert.equal(p.store.gateway.decisions['bluefin.bo'].action, 'agent_handshake');
      mock.timers.tick(200);
      const connects = p.bus.emitted.filter(([type]) => type === 'ui:connect').map(([, data]) => data);
      assert.deepEqual(connects, [{ from: 'acme.ava', to: 'bluefin.bo', initiated_by: 'agent' }]);
      assert.equal(p.store.encounter.status, 'waiting');
      assert.deepEqual(p.calls.swipe, [], 'no gateway call');
      assert.deepEqual(p.calls.connect, [], 'no gateway call');
    } finally {
      p.flow();
      mock.timers.reset();
    }
  });

  test('without a gateway, a right swipe on someone the script does not cover connects directly', () => {
    const p = phone('acme.ava', 'mock');
    try {
      p.bus.emitLocal('ui:swipe', { from: 'acme.ava', to: 'harborline.lena', direction: 'right' });
      const connects = p.bus.emitted.filter(([type]) => type === 'ui:connect').map(([, data]) => data);
      assert.deepEqual(connects, [{ from: 'acme.ava', to: 'harborline.lena', initiated_by: 'human' }]);
      p.bus.emitLocal('ui:swipe', { from: 'acme.ava', to: 'kestrel.mia', direction: 'left' });
      assert.equal(p.bus.emitted.filter(([type]) => type === 'ui:connect').length, 1, 'a left swipe connects no one');
    } finally {
      p.flow();
    }
  });

  test('leaving the phone cancels a scripted swipe that has not finished', () => {
    mock.timers.enable({ apis: ['setTimeout'] });
    const p = phone('acme.ava', 'mock');
    try {
      p.bus.emitLocal('ui:swipe', { from: 'acme.ava', to: 'bluefin.bo', direction: 'right' });
      mock.timers.tick(1000);
      p.flow();
      mock.timers.tick(5000);
      assert.equal(p.bus.emitted.filter(([type]) => type === 'ui:connect').length, 0);
    } finally {
      mock.timers.reset();
    }
  });

  test('without a gateway the Deep dive screen explains how to start one', () => {
    const p = phone('acme.ava', 'mock');
    try {
      const screen = render(p.ctx({ name: 'deepdive', params: { id: 'kestrel.mia' } }, 'mock'));
      assert.match(text(screen), /Swipe right on Mia on Home/);
      assert.doesNotMatch(text(screen), /live mode/);
    } finally {
      p.flow();
    }
  });

  test('deep_dive_started opens the Deep dive screen on Researching…, then deep_dive_ready fills it in', () => {
    const p = phone();
    gateway(p, ofType('deep_dive_started'));
    assert.deepEqual(p.hashes, [['deepdive', { id: 'bluefin.bo' }]]);
    const screen = render(p.ctx({ name: 'deepdive', params: { id: 'bluefin.bo' } }));
    assert.match(text(screen), /Researching Bo…/);
    assert.doesNotMatch(text(screen), /null/, 'no stray "null" while researching');

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
