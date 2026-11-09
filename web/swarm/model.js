// Swarm panel state: a pure reducer over GatewayEvents (SPEC 7.1). No DOM here, so it is
// unit-tested directly. Server strings are only ever stored; the view renders them as text.
// Only IDs, org ids, round numbers, decisions and the one-line `display` are kept.

const MAX_ENTRIES = 200;
const MAX_TEXT = 200;

export const TIME_ZONE = 'America/Denver';

/** The event types the swarm stream carries (private ones never reach it). */
export const SWARM_TYPES = [
  'connect_request', 'agent_decision', 'encounter_started', 'pod_status', 'exchange_message',
  'policy_decision', 'shared_brief', 'encounter_completed', 'error',
];

export function createState() {
  return {
    status: 'idle', // idle | requested | declined | running | completed | failed | stopped
    encounterId: null,
    initiator: null, // { persona, org }
    responder: null,
    lanes: [], // [{ org, side, pods: [{ name, phase }] }]
    timeline: [], // entries, oldest first
    detail: null,
    seq: 0,
  };
}

function text(value) {
  return typeof value === 'string' ? value.slice(0, MAX_TEXT) : '';
}

/** 'acme.ava' -> 'acme' (persona ids are `<org>.<name>`). */
export function orgOfPersona(personaId) {
  const id = text(personaId);
  const dot = id.indexOf('.');
  return dot > 0 ? id.slice(0, dot) : id;
}

function party(personaId) {
  const persona = text(personaId);
  return persona ? { persona, org: orgOfPersona(persona) } : null;
}

function lane(state, org, side) {
  let found = state.lanes.find((l) => l.org === org);
  if (!found) {
    found = { org, side: side === 'responder' ? 'responder' : 'initiator', pods: [] };
    state.lanes.push(found);
    // Initiator on the left, whichever event arrives first.
    state.lanes.sort((a, b) => (a.side === b.side ? 0 : a.side === 'initiator' ? -1 : 1));
  }
  return found;
}

function push(state, entry) {
  state.seq += 1;
  state.timeline.push({ id: state.seq, ...entry });
  if (state.timeline.length > MAX_ENTRIES) state.timeline.splice(0, state.timeline.length - MAX_ENTRIES);
}

function copy(state) {
  return {
    ...state,
    lanes: state.lanes.map((l) => ({ ...l, pods: l.pods.map((p) => ({ ...p })) })),
    timeline: state.timeline.slice(),
  };
}

function sameEncounter(state, event) {
  return !state.encounterId || !event.encounter_id || state.encounterId === event.encounter_id;
}

/** Returns a new state; unknown or malformed events return the state unchanged. */
export function reduce(previous, event) {
  if (!event || typeof event.type !== 'string') return previous;
  const data = event.data && typeof event.data === 'object' ? event.data : {};
  const ts = event.ts;
  const state = copy(previous);

  switch (event.type) {
    case 'connect_request': {
      if (state.status === 'running') return previous;
      const next = createState();
      next.status = 'requested';
      next.initiator = party(data.from_persona_id);
      next.responder = party(data.to_persona_id);
      next.seq = state.seq;
      push(next, {
        kind: 'step', step: 'requested', ts, persona: next.initiator?.persona,
        by: data.initiated_by === 'agent' ? 'agent' : 'human',
      });
      return next;
    }
    case 'agent_decision':
      push(state, {
        kind: 'step', step: 'decision', ts, persona: text(event.persona_id) || state.initiator?.persona,
        action: text(data.action),
      });
      return state;
    case 'encounter_started': {
      const next = createState();
      next.seq = state.seq;
      next.status = 'running';
      next.encounterId = text(event.encounter_id) || null;
      next.initiator = party(data.initiator_persona_id);
      next.responder = party(data.responder_persona_id);
      if (next.initiator) lane(next, next.initiator.org, 'initiator');
      if (next.responder) lane(next, next.responder.org, 'responder');
      push(next, { kind: 'step', step: 'started', ts });
      return next;
    }
    case 'pod_status': {
      if (!sameEncounter(state, event)) return previous;
      if (state.status === 'idle' || state.status === 'requested') {
        state.status = 'running';
        state.encounterId = text(event.encounter_id) || state.encounterId;
      }
      const org = text(data.org_id);
      const name = text(data.pod);
      if (!org || !name) return previous;
      const target = lane(state, org, data.side);
      const phase = text(data.phase) || 'Unknown';
      const pod = target.pods.find((p) => p.name === name);
      if (pod) pod.phase = phase;
      else target.pods.push({ name, phase });
      return state;
    }
    case 'exchange_message': {
      if (!sameEncounter(state, event)) return previous;
      const round = Number(data.round);
      if (![1, 2, 3].includes(round)) return previous;
      if (state.status === 'idle') state.status = 'running';
      push(state, {
        kind: 'message', ts, round, from: text(data.from_org), to: text(data.to_org),
        type: text(data.type), display: text(data.display),
      });
      return state;
    }
    case 'policy_decision': {
      if (!sameEncounter(state, event)) return previous;
      if (data.decision !== 'allow' && data.decision !== 'deny') return previous;
      if (state.status === 'idle') state.status = 'running';
      push(state, {
        kind: 'policy', ts, org: text(data.org_id), action: text(data.action),
        title: text(data.item_title), decision: data.decision, rule: text(data.rule_id),
      });
      return state;
    }
    case 'shared_brief': {
      if (!sameEncounter(state, event)) return previous;
      push(state, { kind: 'step', step: 'brief', ts, persona: text(event.persona_id || data.for_persona_id) });
      return state;
    }
    case 'encounter_completed': {
      if (!sameEncounter(state, event)) return previous;
      state.status = data.status === 'failed' ? 'failed' : 'completed';
      state.detail = text(data.detail) || null;
      push(state, { kind: 'step', step: state.status, ts });
      return state;
    }
    case 'error':
      push(state, { kind: 'step', step: 'error', ts, message: text(data.message) });
      return state;
    // Presenter-side synthetic events (mock mode only).
    case 'request_declined':
      state.status = 'declined';
      push(state, { kind: 'step', step: 'declined', ts });
      return state;
    case 'encounter_stopped':
      state.status = 'stopped';
      push(state, { kind: 'step', step: 'stopped', ts });
      return state;
    default:
      return previous;
  }
}

/** Every pod chip is also text: "Running". Unknown phases fall back to a neutral tone. */
export function phaseTone(phase) {
  switch (phase) {
    case 'Pending': return 'pending';
    case 'Running': return 'running';
    case 'Succeeded': return 'done';
    case 'Failed': return 'failed';
    default: return 'unknown';
  }
}

const formatter = new Intl.DateTimeFormat('en-US', {
  timeZone: TIME_ZONE, hour: 'numeric', minute: '2-digit', second: '2-digit', timeZoneName: 'short',
});

/** "2:10:05 PM MST" in America/Denver; an invalid timestamp gives an empty string. */
export function formatTime(ts) {
  const date = ts instanceof Date ? ts : new Date(ts);
  return Number.isNaN(date.getTime()) ? '' : formatter.format(date);
}
