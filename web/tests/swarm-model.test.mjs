import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createState, reduce, formatTime, phaseTone, orgOfPersona, SWARM_TYPES } from '../swarm/model.js';
import { acceptPhase } from '../swarm/driver.js';

const fixturePath = fileURLToPath(new URL('../swarm/demo-events.json', import.meta.url));
const contractPath = fileURLToPath(new URL('../../contracts/demo-events.json', import.meta.url));
const fixture = JSON.parse(readFileSync(fixturePath, 'utf8'));

function replay(events, state = createState()) {
  return events.reduce((s, { event }) => reduce(s, event), state);
}

test('the bundled fixture is a copy of contracts/demo-events.json', () => {
  assert.deepEqual(fixture, JSON.parse(readFileSync(contractPath, 'utf8')));
});

test('acceptPhase keeps only swarm-visible accept events, in time order', () => {
  const phase = acceptPhase(fixture);
  assert.ok(phase.length > 10);
  assert.ok(phase.every(({ event }) => SWARM_TYPES.includes(event.type)));
  assert.ok(!phase.some(({ event }) => event.type === 'private_brief'));
  assert.deepEqual(phase.map((p) => p.at_ms), [...phase.map((p) => p.at_ms)].sort((a, b) => a - b));
  assert.equal(phase[0].event.type, 'encounter_started');
  assert.equal(phase.at(-1).event.type, 'encounter_completed');
});

test('acceptPhase tolerates a missing or malformed fixture', () => {
  assert.deepEqual(acceptPhase(null), []);
  assert.deepEqual(acceptPhase({ events: 'nope' }), []);
});

test('replaying the accept phase builds lanes, rounds, policy decisions and completion', () => {
  const state = replay(acceptPhase(fixture));
  assert.equal(state.status, 'completed');
  assert.equal(state.encounterId, 'enc-1a2b3c4d');
  assert.equal(state.initiator.persona, 'acme.ava');
  assert.equal(state.responder.org, 'bluefin');
  assert.deepEqual(state.lanes.map((l) => [l.org, l.side]), [['acme', 'initiator'], ['bluefin', 'responder']]);
  // Each pod appears once and ends Running (the fixture never reports Succeeded).
  assert.deepEqual(state.lanes.map((l) => l.pods.map((p) => p.phase)), [['Running'], ['Running']]);
  const messages = state.timeline.filter((e) => e.kind === 'message');
  assert.deepEqual(messages.map((m) => m.round), [1, 1, 2, 2, 3, 3]);
  const policies = state.timeline.filter((e) => e.kind === 'policy');
  assert.equal(policies.length, 4);
  const denied = policies.filter((p) => p.decision === 'deny');
  assert.deepEqual(denied.map((p) => p.rule), ['pricing_needs_approval']);
  assert.equal(state.timeline.at(-1).step, 'completed');
});

test('timeline entries get unique increasing ids', () => {
  const state = replay(acceptPhase(fixture));
  const ids = state.timeline.map((e) => e.id);
  assert.deepEqual(ids, [...ids].sort((a, b) => a - b));
  assert.equal(new Set(ids).size, ids.length);
});

test('pod_status updates a pod in place and orders the initiator lane first', () => {
  let state = createState();
  const base = { encounter_id: 'enc-x', ts: '2026-11-09T21:00:00Z' };
  state = reduce(state, {
    ...base, type: 'pod_status', data: { org_id: 'bluefin', side: 'responder', pod: 'p-b', phase: 'Pending' },
  });
  state = reduce(state, {
    ...base, type: 'pod_status', data: { org_id: 'acme', side: 'initiator', pod: 'p-a', phase: 'Pending' },
  });
  assert.deepEqual(state.lanes.map((l) => l.org), ['acme', 'bluefin']);
  state = reduce(state, {
    ...base, type: 'pod_status', data: { org_id: 'acme', side: 'initiator', pod: 'p-a', phase: 'Succeeded' },
  });
  assert.deepEqual(state.lanes[0].pods, [{ name: 'p-a', phase: 'Succeeded' }]);
  assert.equal(state.status, 'running');
});

test('reduce does not mutate its input', () => {
  const before = createState();
  const frozen = JSON.stringify(before);
  reduce(before, { type: 'encounter_started', encounter_id: 'enc-1', ts: 'x', data: {
    initiator_persona_id: 'acme.ava', responder_persona_id: 'bluefin.bo',
  } });
  assert.equal(JSON.stringify(before), frozen);
});

test('malformed and unknown events leave the state unchanged', () => {
  const state = createState();
  assert.equal(reduce(state, null), state);
  assert.equal(reduce(state, {}), state);
  assert.equal(reduce(state, { type: 'private_brief', data: {} }), state);
  assert.equal(reduce(state, { type: 'exchange_message', data: { round: 9, display: 'x' } }), state);
  assert.equal(reduce(state, { type: 'policy_decision', data: { decision: 'maybe' } }), state);
  assert.equal(reduce(state, { type: 'pod_status', data: { org_id: 'acme' } }), state);
});

test('events for another encounter are ignored once one is running', () => {
  let state = reduce(createState(), {
    type: 'encounter_started', encounter_id: 'enc-1', ts: 't', data: {
      initiator_persona_id: 'acme.ava', responder_persona_id: 'bluefin.bo',
    },
  });
  const other = { type: 'exchange_message', encounter_id: 'enc-2', ts: 't', data: {
    round: 1, type: 'hello', from_org: 'acme', to_org: 'bluefin', display: 'x',
  } };
  assert.equal(reduce(state, other), state);
  state = reduce(state, { ...other, encounter_id: 'enc-1' });
  assert.equal(state.timeline.filter((e) => e.kind === 'message').length, 1);
});

test('a new encounter_started replaces the previous run', () => {
  const started = (id) => ({
    type: 'encounter_started', encounter_id: id, ts: 't', data: {
      initiator_persona_id: 'acme.ava', responder_persona_id: 'bluefin.bo',
    },
  });
  let state = reduce(createState(), started('enc-1'));
  state = reduce(state, { type: 'encounter_completed', encounter_id: 'enc-1', ts: 't', data: { status: 'completed' } });
  state = reduce(state, started('enc-2'));
  assert.equal(state.status, 'running');
  assert.equal(state.encounterId, 'enc-2');
  assert.equal(state.timeline.length, 1);
});

test('a failed encounter and an error event are recorded', () => {
  let state = reduce(createState(), { type: 'encounter_completed', ts: 't', data: { status: 'failed', detail: 'boom' } });
  assert.equal(state.status, 'failed');
  assert.equal(state.detail, 'boom');
  state = reduce(state, { type: 'error', ts: 't', data: { message: 'gateway trouble' } });
  assert.equal(state.timeline.at(-1).message, 'gateway trouble');
});

test('connect_request marks the request and agent decisions are logged', () => {
  let state = reduce(createState(), {
    type: 'connect_request', ts: 't', data: { from_persona_id: 'acme.ava', to_persona_id: 'bluefin.bo', initiated_by: 'agent' },
  });
  assert.equal(state.status, 'requested');
  assert.equal(state.timeline[0].by, 'agent');
  state = reduce(state, { type: 'agent_decision', persona_id: 'acme.ava', ts: 't', data: { action: 'agent_handshake' } });
  assert.equal(state.timeline.at(-1).action, 'agent_handshake');
  state = reduce(state, { type: 'request_declined', ts: 't', data: {} });
  assert.equal(state.status, 'declined');
});

test('long server strings are clipped', () => {
  const state = reduce(createState(), { type: 'exchange_message', ts: 't', data: {
    round: 1, type: 'hello', from_org: 'acme', to_org: 'bluefin', display: 'x'.repeat(5000),
  } });
  assert.equal(state.timeline[0].display.length, 200);
});

test('formatTime shows America/Denver with the MST label', () => {
  assert.equal(formatTime('2026-11-09T22:30:00Z'), '3:30:00 PM MST');
  assert.match(formatTime('2026-07-09T21:30:00Z'), /3:30:00 PM MDT/);
  assert.equal(formatTime('not a date'), '');
});

test('phaseTone and orgOfPersona', () => {
  assert.deepEqual(['Pending', 'Running', 'Succeeded', 'Failed', 'Weird'].map(phaseTone),
    ['pending', 'running', 'done', 'failed', 'unknown']);
  assert.equal(orgOfPersona('acme.ava'), 'acme');
  assert.equal(orgOfPersona(''), '');
});
