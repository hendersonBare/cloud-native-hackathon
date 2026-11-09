// Venue client: the floor plan, location sharing and walking directions to another person.
// Live mode calls the venue API that the gateway mounts at /api/venue (src/rapport_venue, see its
// README). Mock mode uses MockVenue (venue-mock.js), which applies the same rules in the browser.
// Both expose the same promise-returning methods, so the find screen never branches on the mode.

import { request } from './api.js';
import { MockVenue } from './venue-mock.js';
import { withFallback } from './mode.js';

const BASE = '/api/venue';

const query = (params) => new URLSearchParams(params).toString();

/** The live client. `fetchJson(url, {method, body})` is injectable for tests. */
export function liveVenue(fetchJson = request) {
  return {
    view: (personaId) => fetchJson(`${BASE}?${query({ persona_id: personaId })}`),
    directions: (personaId, to) => fetchJson(`${BASE}/directions?${query({ persona_id: personaId, to })}`),
    updateLocation: (body) => fetchJson(`${BASE}/location`, { method: 'PUT', body }),
    setSharing: (body) => fetchJson(`${BASE}/sharing`, { method: 'PUT', body }),
  };
}

/** The venue client for this phone (one per phone, kept in ctx.store). */
export function venueClient(ctx) {
  if (!ctx.store.venueClient) {
    // With a gateway the venue API is used; if the gateway doesn't serve it, this phone
    // switches to the in-browser venue (synced with the other phone over the bus).
    const local = () => new MockVenue({ bus: ctx.bus, self: ctx.me.id });
    ctx.store.venueClient = ctx.mode === 'live' ? withFallback(liveVenue(), local) : local();
  }
  return ctx.store.venueClient;
}
