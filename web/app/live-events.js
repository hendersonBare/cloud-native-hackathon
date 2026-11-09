// Live mode: the gateway events a phone has no dedicated screen for. flow.js re-emits each
// persona-stream event as `gateway:<type>` (data = the full GatewayEvent envelope); this module
// keeps the briefs, deep dive and profile in `store.gateway` and tells the person what happened.
// Only the viewer's own events are kept. Text is shown through toast(), which renders text nodes.
import { person } from './data.js';

const MAX_TOAST = 120;

function nameOf(id) {
  return person(id)?.name || 'them';
}

function clip(value) {
  return typeof value === 'string' ? value.slice(0, MAX_TOAST) : '';
}

export function decisionMessage(action, target) {
  const name = nameOf(target);
  switch (action) {
    case 'agent_handshake': return `Request sent to ${name}'s agent, waiting for ${name}`;
    case 'human_intro': return `Your agent suggests introducing yourself to ${name}`;
    case 'skip': return `Your agent decided to skip ${name}`;
    default: return null;
  }
}

/** Returns a cleanup function. `store.gateway` is created here. */
export function initLiveEvents({ me, store, bus, toast, go }) {
  const gateway = store.gateway || (store.gateway = { deepDives: {} });
  gateway.decisions ||= {};
  const mine = (event) => !event?.persona_id || event.persona_id === me.id;
  const cleanups = [];
  const on = (type, fn) => cleanups.push(bus.on(`gateway:${type}`, (event) => {
    if (event && typeof event === 'object' && mine(event) && event.data && typeof event.data === 'object') {
      fn(event.data, event);
    }
  }));

  on('private_brief', (data) => {
    if (data.persona_id !== me.id) return;
    gateway.privateBrief = data;
    bus.emitLocal('brief:update', { kind: 'private' });
  });
  on('shared_brief', (data) => {
    if (data.for_persona_id !== me.id) return;
    gateway.sharedBrief = data;
    bus.emitLocal('brief:update', { kind: 'shared' });
  });
  on('profile_updated', (data) => {
    gateway.profile = data;
    toast('Your agent updated your profile');
  });
  // A right swipe: show the "Researching…" state, then the deep dive and the agent's decision (deepdive.js).
  on('deep_dive_started', (data) => {
    const target = data.target_persona_id;
    if (typeof target !== 'string') return;
    gateway.researching = target;
    delete gateway.deepDives[target];
    delete gateway.decisions[target];
    go?.('deepdive', { id: target });
    bus.emitLocal('deepdive:update', { target });
  });
  on('deep_dive_ready', (data) => {
    const target = data.target_persona_id;
    if (typeof target !== 'string') return;
    gateway.deepDives[target] = data;
    if (gateway.researching === target) gateway.researching = null;
    bus.emitLocal('deepdive:update', { target });
    toast(`Research on ${nameOf(target)} is ready`);
  });
  on('agent_decision', (data) => {
    const target = data.target_persona_id;
    if (typeof target === 'string') {
      gateway.decisions[target] = data;
      bus.emitLocal('deepdive:update', { target });
    }
    const message = decisionMessage(data.action, target);
    if (message) toast(message);
  });
  on('error', (data) => {
    toast(clip(data.message) || 'Something went wrong', { tone: 'error' });
  });

  return () => { for (const close of cleanups) close(); };
}
