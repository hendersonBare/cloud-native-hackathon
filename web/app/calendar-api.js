// Calendar client. Live mode calls the calendar API that the gateway mounts at
// /api/calendar (src/rapport_calendar, see its README for the payloads). Mock mode
// uses MockCalendar (calendar-mock.js): an in-browser replica that loads the same
// seed and applies the same rules, synced between the two phones over the bus.
//
// Both clients expose the same promise-returning methods, so screens never branch
// on the mode. Every mutating call emits a local `calendar:changed` so any open
// screen refetches.

import { request } from './api.js';
import { MockCalendar } from './calendar-mock.js';
import { withFallback } from './mode.js';

const BASE = '/api/calendar';

function query(params) {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '');
  return new URLSearchParams(entries.map(([k, v]) => [k, String(v)])).toString();
}

const path = (eventId) => `${BASE}/events/${encodeURIComponent(eventId)}`;

/** The live client. `fetchJson(url, {method, body})` is injectable for tests. */
export function liveCalendar(fetchJson = request) {
  return {
    view: (personaId, { start, days } = {}) => fetchJson(`${BASE}?${query({ persona_id: personaId, start, days })}`),
    create: (body) => fetchJson(`${BASE}/events`, { method: 'POST', body }),
    update: (eventId, body) => fetchJson(path(eventId), { method: 'PATCH', body }),
    remove: (eventId, personaId) => fetchJson(`${path(eventId)}?${query({ persona_id: personaId })}`, { method: 'DELETE' }),
    respond: (eventId, body) => fetchJson(`${path(eventId)}/respond`, { method: 'POST', body }),
    setConferenceMode: (body) => fetchJson(`${BASE}/conference-mode`, { method: 'PUT', body }),
    agenda: (personaId, q = '') => fetchJson(`${BASE}/agenda?${query({ persona_id: personaId, q })}`),
    addTalk: (body) => fetchJson(`${BASE}/talks`, { method: 'POST', body }),
    propose: (body) => fetchJson(`${BASE}/propose`, { method: 'POST', body }),
    freebusy: (personaId, start, end) => fetchJson(`${BASE}/freebusy?${query({ persona_id: personaId, start, end })}`),
    exportUrl: (personaId) => `${BASE}/export.ics?${query({ persona_id: personaId })}`,
  };
}

const MUTATIONS = ['create', 'update', 'remove', 'respond', 'setConferenceMode', 'addTalk', 'propose'];

/** Wrap a client so every successful mutation announces itself on this phone. */
export function announcing(client, bus, personaId) {
  const wrapped = { ...client };
  for (const name of MUTATIONS) {
    wrapped[name] = async (...args) => {
      const result = await client[name](...args);
      bus.emitLocal('calendar:changed', { persona_ids: [personaId] });
      return result;
    };
  }
  return wrapped;
}

/** The calendar client for this phone (one per phone, kept in ctx.store). */
export function calendarClient(ctx) {
  if (!ctx.store.calendarClient) {
    // With a gateway the calendar API is used; if the gateway doesn't serve it, this phone
    // switches to the in-browser calendar (which syncs with the other phone over the bus).
    const local = () => new MockCalendar({ bus: ctx.bus, self: ctx.me.id });
    const base = ctx.mode === 'live' ? withFallback(liveCalendar(), local) : local();
    ctx.store.calendarClient = announcing(base, ctx.bus, ctx.me.id);
  }
  return ctx.store.calendarClient;
}

/** Human-readable message for a failed calendar call (status codes from the API spec). */
export function calendarErrorMessage(error, action = 'update the calendar') {
  switch (error?.status) {
    case 404: return 'That event is no longer on your calendar.';
    case 409: return action === 'propose'
      ? 'No time works for both of you this week.'
      : 'That change is not allowed for this event.';
    case 422: return 'Check the details and try again.';
    default: return `Could not ${action}. Try again.`;
  }
}
