// In-browser replica of the venue API (src/rapport_venue), used in mock mode (phone.html?mock=1).
// It loads the same venue.json and applies the same rules: sharing is a per-person consent flag,
// turning it off forgets that person's GPS position, a GPS fix only counts for gps_ttl_s, and
// someone who is not sharing reveals nothing. Changes go to the other phone as `venue:sync`.
//
// Methods are arrow-function class fields so the client can be spread or passed around unbound.

import SEED from '../mock/venue.json' with { type: 'json' };
import { person } from './data.js';
import { directions as route, geoToVenue, placeOnSite, publicVenue, roomAt } from './venue-model.js';

export class VenueError extends Error {
  constructor(status, code) {
    super(`venue request failed with status ${status}`);
    this.name = 'VenueError';
    this.status = status;
    this.code = code;
  }
}

export class MockVenue {
  #venue;
  #self;
  #bus;
  #clock;
  #sharing = new Map();
  #gps = new Map(); // persona_id -> { x, y, accuracy_m, updated_at (ms) }

  /** `bus` needs emit(type, data) and emitLocal(type, data); on(type, fn) is used when present. */
  constructor({ bus = null, self = null, venue = SEED, clock = () => Date.now() } = {}) {
    this.#venue = structuredClone(venue);
    this.#self = self;
    this.#bus = bus;
    this.#clock = clock;
    this.reset();
    bus?.on?.('venue:sync', (data, msg) => this.#receive(data, msg));
  }

  reset = () => {
    this.#sharing = new Map(Object.entries(this.#venue.sharing || {}));
    this.#gps.clear();
  };

  #known(id) {
    if (!person(id)) throw new VenueError(404, 'unknown_persona');
  }

  #position(id) {
    const fix = this.#gps.get(id);
    if (fix && this.#sharing.get(id) === true && this.#clock() - fix.updated_at <= this.#venue.gps_ttl_s * 1000) {
      return {
        persona_id: id, x: fix.x, y: fix.y, room_id: roomAt(this.#venue, fix.x, fix.y).id,
        source: 'gps', accuracy_m: fix.accuracy_m, updated_at: new Date(fix.updated_at).toISOString(),
      };
    }
    const spot = this.#venue.checkins?.[id] || [this.#venue.width_m / 2, this.#venue.corridor_y];
    return {
      persona_id: id, x: spot[0], y: spot[1], room_id: roomAt(this.#venue, spot[0], spot[1]).id,
      source: 'checkin', accuracy_m: null, updated_at: null,
    };
  }

  view = async (personaId) => {
    this.#known(personaId);
    return {
      persona_id: personaId,
      venue: publicVenue(this.#venue),
      sharing: this.#sharing.get(personaId) === true,
      me: this.#position(personaId),
    };
  };

  setSharing = async ({ persona_id: id, enabled }) => {
    this.#known(id);
    this.#sharing.set(id, enabled === true);
    if (!enabled) this.#gps.delete(id);
    this.#broadcast(id);
    return { persona_id: id, enabled: enabled === true };
  };

  updateLocation = async ({ persona_id: id, lat, lng, accuracy_m: accuracy = null }) => {
    this.#known(id);
    if (this.#sharing.get(id) !== true) throw new VenueError(409, 'sharing_off');
    if (accuracy != null && accuracy > this.#venue.max_accuracy_m) throw new VenueError(422, 'too_inaccurate');
    const raw = geoToVenue(this.#venue, lat, lng);
    const spot = placeOnSite(this.#venue, raw.x, raw.y);
    if (!spot) throw new VenueError(422, 'outside_venue');
    this.#gps.set(id, { ...spot, accuracy_m: accuracy, updated_at: this.#clock() });
    this.#broadcast(id);
    return this.#position(id);
  };

  directions = async (personaId, to) => {
    this.#known(personaId);
    this.#known(to);
    if (personaId === to) throw new VenueError(422, 'same_person');
    const from = this.#position(personaId);
    const base = { persona_id: personaId, to_persona_id: to };
    if (this.#sharing.get(to) !== true) {
      return {
        ...base, peer_status: 'not_sharing', from, to: null,
        route: [], distance_m: null, bearing_deg: null, compass: null, legs: [],
      };
    }
    const target = this.#position(to);
    return { ...base, peer_status: 'sharing', from, to: target, ...route(this.#venue, from, target) };
  };

  #broadcast(id) {
    const fix = this.#gps.get(id) || null;
    this.#bus?.emit?.('venue:sync', { persona_id: id, sharing: this.#sharing.get(id) === true, gps: fix });
  }

  #receive(data, msg) {
    if (!data || msg?.from === this.#self || !person(data.persona_id)) return;
    this.#sharing.set(data.persona_id, data.sharing === true);
    if (data.sharing === true && data.gps && Number.isFinite(data.gps.x) && Number.isFinite(data.gps.y)) {
      this.#gps.set(data.persona_id, { ...data.gps });
    } else {
      this.#gps.delete(data.persona_id);
    }
    this.#bus?.emitLocal?.('venue:changed', { persona_id: data.persona_id });
  }
}
