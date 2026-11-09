import test from 'node:test';
import assert from 'node:assert/strict';
import { decisionMessage, initLiveEvents } from '../app/live-events.js';

function setup(meId = 'acme.ava') {
  const handlers = new Map();
  const emitted = [];
  const toasts = [];
  const bus = {
    on(type, fn) { handlers.set(type, fn); return () => handlers.delete(type); },
    emitLocal(type, data) { emitted.push([type, data]); },
  };
  const store = {};
  const cleanup = initLiveEvents({
    me: { id: meId }, store, bus, toast: (text, options) => toasts.push([text, options?.tone]),
  });
  const send = (type, event) => handlers.get(`gateway:${type}`)?.(event);
  return { store, send, emitted, toasts, handlers, cleanup };
}

const envelope = (type, data, persona_id = null) => ({ type, ts: 't', encounter_id: null, persona_id, data });

test('subscribes to every phone-targeted gateway event type', () => {
  const { handlers } = setup();
  assert.deepEqual([...handlers.keys()].sort(), [
    'gateway:agent_decision', 'gateway:deep_dive_ready', 'gateway:deep_dive_started', 'gateway:error',
    'gateway:private_brief', 'gateway:profile_updated', 'gateway:shared_brief',
  ]);
});

test('private_brief and shared_brief are stored for this persona only and announce an update', () => {
  const { store, send, emitted } = setup();
  send('private_brief', envelope('private_brief', { persona_id: 'acme.ava', headline: 'h' }, 'acme.ava'));
  send('private_brief', envelope('private_brief', { persona_id: 'bluefin.bo', headline: 'other' }, 'bluefin.bo'));
  send('shared_brief', envelope('shared_brief', { for_persona_id: 'acme.ava', summary: 's' }, 'acme.ava'));
  assert.equal(store.gateway.privateBrief.headline, 'h');
  assert.equal(store.gateway.sharedBrief.summary, 's');
  assert.deepEqual(emitted.map(([type, d]) => [type, d.kind]), [['brief:update', 'private'], ['brief:update', 'shared']]);
});

test('events addressed to another persona are ignored', () => {
  const { store, send, toasts } = setup('acme.ava');
  send('deep_dive_ready', envelope('deep_dive_ready', { target_persona_id: 'bluefin.bo' }, 'bluefin.kai'));
  assert.deepEqual(store.gateway.deepDives, {});
  assert.deepEqual(toasts, []);
});

test('deep dive, agent decision, profile and error events tell the person what happened', () => {
  const { store, send, toasts, emitted } = setup();
  send('deep_dive_started', envelope('deep_dive_started', { target_persona_id: 'bluefin.bo' }, 'acme.ava'));
  send('deep_dive_ready', envelope('deep_dive_ready', { target_persona_id: 'bluefin.bo', summary: 'x' }, 'acme.ava'));
  send('agent_decision', envelope('agent_decision', { target_persona_id: 'bluefin.bo', action: 'agent_handshake' }, 'acme.ava'));
  send('profile_updated', envelope('profile_updated', { persona_id: 'acme.ava' }, 'acme.ava'));
  send('error', envelope('error', { message: 'x'.repeat(500) }));
  assert.equal(store.gateway.deepDives['bluefin.bo'].summary, 'x');
  assert.equal(store.gateway.decisions['bluefin.bo'].action, 'agent_handshake');
  assert.equal(store.gateway.researching, null);
  assert.ok(emitted.some(([type]) => type === 'deepdive:update'));
  assert.deepEqual(toasts.map(([text]) => text.slice(0, 60)), [
    'Research on Bo is ready',
    "Request sent to Bo's agent, waiting for Bo",
    'Your agent updated your profile',
    'x'.repeat(60),
  ]);
  assert.equal(toasts.at(-1)[0].length, 120);
  assert.equal(toasts.at(-1)[1], 'error');
});

test('decisionMessage covers every action and ignores unknown ones', () => {
  assert.match(decisionMessage('human_intro', 'bluefin.bo'), /introducing yourself to Bo/);
  assert.match(decisionMessage('skip', 'bluefin.bo'), /skip Bo/);
  assert.equal(decisionMessage('nonsense', 'bluefin.bo'), null);
});

test('malformed envelopes are ignored and cleanup unsubscribes', () => {
  const { send, toasts, handlers, cleanup } = setup();
  send('error', null);
  send('error', { type: 'error', data: null });
  assert.deepEqual(toasts, []);
  cleanup();
  assert.equal(handlers.size, 0);
});
