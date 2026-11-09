import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { acceptPhase, startLive, startMock } from '../swarm/driver.js';

const fixture = JSON.parse(readFileSync(fileURLToPath(new URL('../swarm/demo-events.json', import.meta.url)), 'utf8'));

// A fake clock and BroadcastChannel so the mock replay is deterministic.
function harness({ start = 1_000_000 } = {}) {
  let nowMs = start;
  const timers = [];
  const listeners = [];
  const events = [];
  const channel = {
    addEventListener: (_, fn) => listeners.push(fn),
    removeEventListener: (_, fn) => listeners.splice(listeners.indexOf(fn), 1),
  };
  const driver = startMock({
    channel,
    loadFixture: async () => fixture,
    onEvent: (e) => events.push(e),
    now: () => nowMs,
    setTimer: (fn, ms) => { const t = { fn, at: nowMs + ms, live: true }; timers.push(t); return t; },
    clearTimer: (t) => { t.live = false; },
  });
  return {
    driver, events, timers, listeners,
    send: (type, data) => listeners.forEach((fn) => fn({ data: { type, data } })),
    advance(ms) {
      nowMs += ms;
      for (const t of timers.filter((x) => x.live && x.at <= nowMs).sort((a, b) => a.at - b.at)) {
        t.live = false;
        t.fn();
      }
    },
    flush: () => new Promise((resolve) => setImmediate(resolve)),
    now: () => nowMs,
  };
}

test('encounter:start schedules the accept phase at startedAt plus each at_ms', async () => {
  const t = harness();
  t.send('encounter:start', { encounter_id: 'enc-a', initiator: 'acme.ava', responder: 'bluefin.bo', startedAt: t.now() + 600 });
  await t.flush();
  const expected = acceptPhase(fixture);
  assert.equal(t.timers.filter((x) => x.live).length, expected.length);
  assert.deepEqual(t.events, []);
  t.advance(600); // startedAt: encounter_started fires
  assert.deepEqual(t.events.map((e) => e.type), ['encounter_started']);
  t.advance(700); // 600 + 700 -> the second pod_status
  assert.deepEqual(t.events.map((e) => e.type), ['encounter_started', 'pod_status', 'pod_status']);
  t.advance(10_000);
  assert.equal(t.events.length, expected.length);
  assert.equal(t.events.at(-1).type, 'encounter_completed');
});

test('replayed events are stamped with the current time, not the fixture time', async () => {
  const t = harness();
  t.send('encounter:start', { encounter_id: 'enc-a', startedAt: t.now() });
  await t.flush();
  t.advance(0);
  assert.equal(t.events[0].ts, new Date(t.now()).toISOString());
});

test('a repeated encounter:start for the same encounter does not replay twice', async () => {
  const t = harness();
  const msg = { encounter_id: 'enc-a', startedAt: t.now() };
  t.send('encounter:start', msg);
  t.send('encounter:start', msg);
  await t.flush();
  t.advance(20_000);
  assert.equal(t.events.length, acceptPhase(fixture).length);
});

test('ui:connect announces the request and cancels a running replay', async () => {
  const t = harness();
  t.send('encounter:start', { encounter_id: 'enc-a', startedAt: t.now() });
  await t.flush();
  t.send('ui:connect', { from: 'acme.ava', to: 'bluefin.bo', initiated_by: 'agent' });
  assert.deepEqual(t.events.map((e) => [e.type, e.data.from_persona_id, e.data.initiated_by]),
    [['connect_request', 'acme.ava', 'agent']]);
  t.advance(20_000);
  assert.equal(t.events.length, 1);
});

test('declined and stopped become presenter-side events and cancel the replay', async () => {
  const t = harness();
  t.send('encounter:start', { encounter_id: 'enc-a', startedAt: t.now() + 5000 });
  await t.flush();
  t.send('encounter:declined', { initiator: 'acme.ava', responder: 'bluefin.bo' });
  t.send('encounter:done', { encounter_id: 'enc-a', stopped: true });
  t.send('encounter:done', { encounter_id: 'enc-a' }); // natural completion is ignored
  t.advance(20_000);
  assert.deepEqual(t.events.map((e) => e.type), ['request_declined', 'encounter_stopped']);
});

test('the phone Stop button broadcasts encounter:stopped, which cancels the replay', async () => {
  const t = harness();
  t.send('encounter:start', { encounter_id: 'enc-a', startedAt: t.now() });
  await t.flush();
  t.advance(2000);
  const before = t.events.length;
  t.send('encounter:stopped', { encounter_id: 'enc-a' });
  t.advance(20_000);
  assert.deepEqual(t.events.slice(before).map((e) => e.type), ['encounter_stopped']);
});

test('stop() removes the listener and silences further events', async () => {
  const t = harness();
  t.driver.stop();
  assert.equal(t.listeners.length, 0);
});

test('a fixture that fails to load is survived', async () => {
  const listeners = [];
  const events = [];
  startMock({
    channel: { addEventListener: (_, fn) => listeners.push(fn), removeEventListener() {} },
    loadFixture: async () => { throw new Error('nope'); },
    onEvent: (e) => events.push(e),
  });
  listeners[0]({ data: { type: 'encounter:start', data: { encounter_id: 'enc-a', startedAt: Date.now() } } });
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(events, []);
});

test('startLive opens the swarm view and forwards only swarm-visible types', () => {
  const calls = [];
  const received = [];
  let handler;
  const close = () => {};
  const returned = startLive({
    openStream: (query, onEvent) => { calls.push(query); handler = onEvent; return close; },
    onEvent: (e) => received.push(e.type),
  });
  assert.equal(returned, close);
  assert.deepEqual(calls, ['view=swarm']);
  for (const type of ['pod_status', 'private_brief', 'exchange_message', 'deep_dive_ready', 'policy_decision']) {
    handler({ type, data: {} });
  }
  assert.deepEqual(received, ['pod_status', 'exchange_message', 'policy_decision']);
});
