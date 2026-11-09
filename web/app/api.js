// Gateway client (SPEC §7.1). Payloads stay in their gateway contract shapes.

const EVENT_TYPES = [
  'connect_request', 'encounter_started', 'pod_status', 'exchange_message',
  'policy_decision', 'private_brief', 'shared_brief', 'encounter_completed',
  'profile_updated', 'deep_dive_started', 'deep_dive_ready', 'agent_decision', 'error',
];

async function request(url, { method = 'GET', body } = {}) {
  const multipart = body instanceof FormData;
  const headers = { Accept: 'application/json' };
  if (body !== undefined && !multipart) headers['Content-Type'] = 'application/json';
  const response = await fetch(url, {
    method,
    credentials: 'same-origin',
    headers,
    body: body === undefined ? undefined : multipart ? body : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${method} request failed with status ${response.status}`);
  if (response.status === 204) return null;
  const text = await response.text();
  return text ? JSON.parse(text) : null;
}

export function getPersonas() {
  return request('/api/personas');
}

export function getProfile(personaId) {
  return request(`/api/profile?${new URLSearchParams({ persona_id: personaId })}`);
}

export function uploadContext({ personaId, visibility, file, text }) {
  const body = new FormData();
  body.append('persona_id', personaId);
  body.append('visibility', visibility);
  if (file != null) body.append('file', file);
  if (text != null) body.append('text', text);
  return request('/api/context', { method: 'POST', body });
}

export function connect(body) {
  return request('/api/connect', { method: 'POST', body });
}

export function accept(requestId, body) {
  return request(`/api/connect/${encodeURIComponent(requestId)}/accept`, { method: 'POST', body });
}

export function ask(body) {
  return request('/api/ask', { method: 'POST', body });
}

export function talks(personaId, q = '') {
  return request(`/api/talks?${new URLSearchParams({ persona_id: personaId, q })}`);
}

export function research(body) {
  return request('/api/research', { method: 'POST', body });
}

export function swipe(body) {
  return request('/api/swipe', { method: 'POST', body });
}

export function reset() {
  return request('/api/demo/reset', { method: 'POST' });
}

/** onEvent receives the complete GatewayEvent; call the returned function to close. */
export function openStream(query, onEvent) {
  const source = new EventSource(`/api/stream?${query}`, { withCredentials: true });
  const seen = new Set();
  let closed = false;
  function receive(message) {
    // Native connection errors have no data; EventSource handles reconnection.
    if (closed || typeof message.data !== 'string') return;
    let event;
    try {
      event = JSON.parse(message.data);
    } catch {
      console.warn('Invalid gateway event JSON');
      return;
    }
    if (!event || !EVENT_TYPES.includes(event.type)) return;
    const key = JSON.stringify([event.type, event.ts, event.encounter_id]);
    if (seen.has(key)) return;
    seen.add(key);
    onEvent(event);
  }
  for (const type of EVENT_TYPES) source.addEventListener(type, receive);
  return function close() {
    if (closed) return;
    closed = true;
    for (const type of EVENT_TYPES) source.removeEventListener(type, receive);
    source.close();
    seen.clear();
  };
}

export const api = {
  getPersonas, getProfile, uploadContext, connect, accept, ask, talks, research, swipe, reset, openStream,
};
