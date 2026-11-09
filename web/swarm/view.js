// Swarm panel DOM builders. Every server string goes through h() as a text node.
import { h, icon } from '../app/ui.js';
import { ORGS, person } from '../app/data.js';
import { formatTime, phaseTone } from './model.js';

export const STATUS_LABEL = {
  idle: 'Waiting for a connection',
  requested: 'Request sent, waiting for acceptance',
  declined: 'Request declined',
  running: 'Agents meeting',
  completed: 'Encounter completed',
  failed: 'Encounter failed',
  stopped: 'Stopped by the presenter',
};

const DECISION_LABEL = {
  agent_handshake: 'start an agent handshake',
  human_intro: 'suggest a human introduction',
  skip: 'skip this contact',
};

const ROUND_LABEL = { 1: 'Introductions', 2: 'Offers and asks', 3: 'Answers and follow-ups' };

export function orgName(org) {
  return ORGS[org]?.name || org || 'Unknown org';
}

export function personaName(id) {
  return person(id)?.name || id || 'Unknown';
}

function timeNode(ts) {
  const label = formatTime(ts);
  if (!label) return null;
  const date = new Date(ts);
  return h('time', { class: 'sw-time tabular', datetime: date.toISOString() }, label);
}

function policyNode(entry) {
  const allowed = entry.decision === 'allow';
  return h('li', {
    class: `sw-entry sw-policy ${allowed ? 'is-allow' : 'is-deny'}`,
    'data-entry': String(entry.id),
  },
  h('span', { class: 'sw-chip-icon' }, icon(allowed ? 'check' : 'close', { size: 16, stroke: 2.6 })),
  h('div', { class: 'sw-body' },
    h('p', { class: 'sw-policy-line' },
      h('strong', null, allowed ? 'Allowed' : 'Denied'),
      h('span', null, ` · ${orgName(entry.org)} policy on ${entry.action || 'request'}`)),
    entry.title ? h('p', { class: 'sw-detail' }, entry.title) : null,
    h('p', { class: 'sw-rule' }, h('span', { class: 'sw-vh' }, 'Rule: '), entry.rule)),
  timeNode(entry.ts));
}

function messageNode(entry) {
  return h('li', { class: 'sw-entry sw-message', 'data-entry': String(entry.id) },
    h('span', { class: 'sw-round', title: `Round ${entry.round}: ${ROUND_LABEL[entry.round]}` },
      h('span', { class: 'sw-vh' }, 'Round '), String(entry.round)),
    h('div', { class: 'sw-body' },
      h('p', { class: 'sw-route' },
        h('strong', null, orgName(entry.from)),
        h('span', { 'aria-hidden': 'true' }, ' → '),
        h('span', { class: 'sw-vh' }, ' to '),
        h('strong', null, orgName(entry.to))),
      h('p', { class: 'sw-detail' }, entry.display)),
    timeNode(entry.ts));
}

function stepText(entry) {
  switch (entry.step) {
    case 'requested':
      return entry.by === 'agent'
        ? `${personaName(entry.persona)}'s agent asked to connect`
        : `${personaName(entry.persona)} asked to connect`;
    case 'decision':
      return `${personaName(entry.persona)}'s agent chose to ${DECISION_LABEL[entry.action] || 'act'}`;
    case 'started': return 'Encounter started · delegate pods launching';
    case 'brief': return `Shared brief ready for ${personaName(entry.persona)}`;
    case 'completed': return 'Encounter completed';
    case 'failed': return 'Encounter failed';
    case 'declined': return 'The request was declined';
    case 'stopped': return 'Stopped by the presenter';
    case 'error': return entry.message ? `Gateway error: ${entry.message}` : 'Gateway error';
    default: return 'Update';
  }
}

function stepNode(entry) {
  const tone = entry.step === 'completed' ? 'is-done'
    : entry.step === 'failed' || entry.step === 'error' ? 'is-failed' : '';
  return h('li', { class: `sw-entry sw-step ${tone}`.trim(), 'data-entry': String(entry.id) },
    h('span', { class: 'sw-dot', 'aria-hidden': 'true' }),
    h('div', { class: 'sw-body' }, h('p', { class: 'sw-detail' }, stepText(entry))),
    timeNode(entry.ts));
}

export function entryNode(entry) {
  if (entry.kind === 'message') return messageNode(entry);
  if (entry.kind === 'policy') return policyNode(entry);
  return stepNode(entry);
}

/** "Ava ↔ Bo" with the orgs underneath; before an encounter, a hint. */
export function headerNodes(state) {
  const { initiator, responder } = state;
  if (!initiator && !responder) {
    return [h('p', { class: 'sw-pair sw-pair-empty' }, 'No encounter yet')];
  }
  return [
    h('p', { class: 'sw-pair' },
      h('strong', null, personaName(initiator?.persona)),
      h('span', { class: 'sw-arrows', 'aria-hidden': 'true' }, ' ↔ '),
      h('span', { class: 'sw-vh' }, ' and '),
      h('strong', null, personaName(responder?.persona))),
    h('p', { class: 'sw-orgs' },
      `${orgName(initiator?.org)} initiated · ${orgName(responder?.org)} responded`),
  ];
}

export function laneNodes(state) {
  if (state.lanes.length === 0) {
    return [h('p', { class: 'sw-lanes-empty' }, 'Delegate pods appear here when an encounter starts.')];
  }
  return state.lanes.map((lane) => h('section', {
    class: 'sw-lane', 'aria-label': `${orgName(lane.org)} lane`, dataset: { org: lane.org },
  },
  h('h3', { class: 'sw-lane-title' },
    h('span', null, orgName(lane.org)),
    h('span', { class: 'sw-lane-side' }, lane.side === 'initiator' ? 'Initiator' : 'Responder')),
  lane.pods.length === 0
    ? h('p', { class: 'sw-detail' }, 'No pods yet')
    : h('ul', { class: 'sw-pods', 'aria-label': `${orgName(lane.org)} pods` }, lane.pods.map((pod) => h('li', {
      class: `sw-pod is-${phaseTone(pod.phase)}`, dataset: { phase: pod.phase },
    },
    h('span', { class: 'sw-pod-name' }, pod.name),
    h('span', { class: 'sw-pod-phase' }, pod.phase))))));
}
