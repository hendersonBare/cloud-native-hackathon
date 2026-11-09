// Venue client: the floor plan, location sharing and walking directions to another person.
// Live mode calls the venue API that the gateway mounts at /api/venue (src/rapport_venue, see its
// README). Mock mode uses MockVenue (venue-mock.js), which applies the same rules in the browser.
// Both expose the same promise-returning methods, so the find screen never branches on the mode.

import { request } from './api.js';
import { MockVenue } from './venue-mock.js';
import { withFallback } from './mode.js';

const BASE = '/api/venue';

const query = (params) => new URLSearchParams(params).toString();

/**
 * The live client. `fetchJson(url, {method, body})` is injectable for tests.
 *
 * Turning sharing on returns a sharing_token for this device only. The client keeps it in memory
 * (never in storage, the URL or the screen), sends it with every GPS fix, and drops it when sharing
 * goes off, so screens never see it. If sharing was already on before this device held a token
 * (the demo seed), the first fix gets 403 and the client claims sharing once, then retries.
 */
export function liveVenue(fetchJson = request) {
  const tokens = new Map(); // persona_id -> this device's sharing token
  const setSharing = async (body) => {
    const held = tokens.get(body.persona_id);
    const send = body.enabled && held ? { ...body, sharing_token: held } : { ...body };
    const result = await fetchJson(`${BASE}/sharing`, { method: 'PUT', body: send });
    if (!body.enabled) tokens.delete(body.persona_id);
    else if (typeof result?.sharing_token === 'string') tokens.set(body.persona_id, result.sharing_token);
    if (!result || typeof result !== 'object') return result;
    const { sharing_token: _hidden, ...state } = result; // the token stays inside this client
    return state;
  };
  const sendFix = (body) => fetchJson(`${BASE}/location`, {
    method: 'PUT', body: { ...body, sharing_token: tokens.get(body.persona_id) ?? null },
  });
  return {
    view: (personaId) => fetchJson(`${BASE}?${query({ persona_id: personaId })}`),
    directions: (personaId, to) => fetchJson(`${BASE}/directions?${query({ persona_id: personaId, to })}`),
    updateLocation: async (body) => {
      try {
        return await sendFix(body);
      } catch (error) {
        if (error?.status !== 403 || tokens.has(body.persona_id)) throw error;
        await setSharing({ persona_id: body.persona_id, enabled: true });
        return sendFix(body);
      }
    },
    setSharing,
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
