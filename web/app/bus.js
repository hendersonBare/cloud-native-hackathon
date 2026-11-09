// Event bus. Local listeners plus a BroadcastChannel so the two phones (two
// iframes on the same origin) can talk to each other in mock mode.
// Message shape: { type, data, from } where `from` is the sender's persona id.
//
// Event contract (persona ids like 'acme.ava'):
//   ui:connect        {from, to, initiated_by: 'human'|'agent'}  a phone asks to connect agents (broadcast)
//   ui:pass           {from, to}                                  swiped left (local)
//   encounter:start   {encounter_id, initiator, responder, startedAt}  responder accepted (broadcast)
//   encounter:declined{encounter_id, initiator, responder}        responder declined (broadcast)
//   exchange:message  {encounter_id, from, text, round, shared: []}   live mode only (from SSE)
//   exchange:policy   {encounter_id, org_id, allow, rule_id, reason}  live mode only (from SSE)
//   encounter:done    {encounter_id}                              exchange finished (broadcast)
//   theme             'light'|'dark'                              (local)
//   config            {malicious}                                 presenter toolbar (local)
// Per-phone shared state: ctx.store.encounter = {encounter_id, initiator, responder, startedAt,
//   status: 'waiting'|'talking'|'done'|'declined'} — written only by app/flow.js.

const listeners = new Map();
const channel = 'BroadcastChannel' in window ? new BroadcastChannel('rapport-demo') : null;
let self = null;

export function setSelf(personaId) {
  self = personaId;
}

export function on(type, fn) {
  if (!listeners.has(type)) listeners.set(type, new Set());
  listeners.get(type).add(fn);
  return () => listeners.get(type)?.delete(fn);
}

function dispatch(msg) {
  for (const fn of listeners.get(msg.type) || []) {
    try { fn(msg.data, msg); } catch (err) { console.warn('bus listener failed', msg.type, err?.name || 'Error'); }
  }
  for (const fn of listeners.get('*') || []) {
    try { fn(msg.data, msg); } catch (err) { console.warn('bus listener failed', msg.type, err?.name || 'Error'); }
  }
}

/** Emit to this phone only. */
export function emitLocal(type, data) {
  dispatch({ type, data, from: self });
}

/** Emit to this phone and the other phone. */
export function emit(type, data) {
  const msg = { type, data, from: self };
  dispatch(msg);
  channel?.postMessage(msg);
}

channel?.addEventListener('message', (e) => {
  if (e.data && typeof e.data.type === 'string') dispatch(e.data);
});
