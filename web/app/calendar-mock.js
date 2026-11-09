// In-browser replica of the calendar backend (src/rapport_calendar, see its README for the payloads).
// Used in mock mode (phone.html?mock=1): it loads the same seed as the backend, applies the same rules,
// returns the same response shapes as liveCalendar() in calendar-api.js, and rejects with an Error whose
// `.status` is the HTTP status the API would answer (404, 409 or 422), so screens never branch on the mode.
//
// Both demo phones hold a full replica of every persona's calendar. After a mutation the phone broadcasts
// `calendar:sync` with the copies it changed; the other phone upserts them and announces `calendar:changed`.
//
// The methods are arrow-function class fields on purpose: announcing() in calendar-api.js spreads the client
// (`{ ...client }`), which copies own properties only, so prototype methods would be lost.
//
// All times are aware UTC strings ('2026-11-09T22:30:00Z'); the display zone is applied by time.js.

import SEED from '../mock/calendar-seed.json' with { type: 'json' };
import { person } from './data.js';
import { addDays, localToUtc } from './time.js';

export const PERSONA_IDS = [
  'acme.ava', 'acme.sam', 'bluefin.bo', 'bluefin.kai', 'kestrel.mia', 'kestrel.raj',
  'harborline.lena', 'harborline.omar', 'tidewater.sofia', 'tidewater.ken', 'lumenly.priya', 'lumenly.tom',
];

const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
const MAX_EVENTS = 200;
const MAX_DURATION_MS = 12 * HOUR;
const MAX_FREEBUSY_MS = 14 * 24 * HOUR;
const GRID_MINUTES = 15;
const AGENDA_LIMIT = 20;

/** An API-style failure: `.status` is the HTTP status and `.code` the spec's detail string. */
export class CalendarError extends Error {
  constructor(status, code) {
    super(code);
    this.name = 'CalendarError';
    this.status = status;
    this.code = code;
  }
}

const fail = (status, code) => new CalendarError(status, code);

// ---------------------------------------------------------------------------------------------------------
// Pure helpers (exported so they are unit-tested)
// ---------------------------------------------------------------------------------------------------------

const AWARE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/;
const DATE_KEY = /^\d{4}-\d{2}-\d{2}$/;

/** A Date, epoch ms or ISO string -> epoch ms. */
function toMs(value) {
  if (typeof value === 'number') return value;
  if (value instanceof Date) return value.getTime();
  return Date.parse(value);
}

/** Epoch ms, Date or ISO string -> '2026-11-09T22:30:00Z' (UTC, whole seconds shown without a fraction). */
export function isoUtc(value) {
  return new Date(toMs(value)).toISOString().replace(/\.000Z$/, 'Z');
}

/** A request datetime must carry an explicit offset (naive values are a 422); returns epoch ms. */
export function parseAware(value) {
  let ms;
  if (value instanceof Date) ms = value.getTime();
  else if (typeof value === 'string' && AWARE.test(value)) ms = Date.parse(value);
  else throw fail(422, 'invalid_datetime');
  if (Number.isNaN(ms)) throw fail(422, 'invalid_datetime');
  return ms;
}

/** '2026-11-09' is a real calendar date (Date.parse rolls '2026-02-31' over, so round-trip it). */
function isDateKey(value) {
  return typeof value === 'string' && DATE_KEY.test(value) && addDays(value, 0) === value;
}

/** Two events (or busy blocks) overlap when each starts before the other ends. */
export function overlap(a, b) {
  return toMs(a.starts_at) < toMs(b.ends_at) && toMs(a.ends_at) > toMs(b.starts_at);
}

/** Merge busy blocks into sorted, non-overlapping blocks. Touching blocks join into one. */
export function mergeBusy(blocks) {
  const sorted = blocks
    .map((b) => [toMs(b.starts_at), toMs(b.ends_at)])
    .filter(([s, e]) => e > s)
    .sort((x, y) => x[0] - y[0] || x[1] - y[1]);
  const merged = [];
  for (const [s, e] of sorted) {
    const last = merged[merged.length - 1];
    if (last && s <= last[1]) last[1] = Math.max(last[1], e);
    else merged.push([s, e]);
  }
  return merged.map(([s, e]) => ({ starts_at: isoUtc(s), ends_at: isoUtc(e) }));
}

function offsetMinutes(utcOffset) {
  const match = /^([+-])(\d{2}):(\d{2})$/.exec(utcOffset);
  if (!match) throw new RangeError('utc offset must look like -07:00');
  return (match[1] === '-' ? -1 : 1) * (Number(match[2]) * 60 + Number(match[3]));
}

function minutesOfDay(hhmm) {
  const [hours, minutes] = hhmm.split(':').map(Number);
  return hours * 60 + minutes;
}

/**
 * The scheduling engine. Candidate starts are every `grid` minutes from max(notBefore, week start) rounded up,
 * on weekdays of the week, inside working hours (the meeting must END by `workEnd`). The first start whose
 * slot overlaps no busy block wins, so the answer is deterministic. Returns null when nothing is free.
 *
 * `busy` is the union of both people's non-declined events: [{ starts_at, ends_at }].
 */
export function firstMutualSlot({
  busy, notBefore, weekStart, utcOffset = '-07:00', minutes = 30,
  workStart = '09:00', workEnd = '18:00', grid = GRID_MINUTES, days = 7,
}) {
  const gridMs = grid * MINUTE;
  const lengthMs = minutes * MINUTE;
  const offsetMs = offsetMinutes(utcOffset) * MINUTE;
  const weekStartMs = Date.parse(localToUtc(weekStart, '00:00', utcOffset));
  const weekEndMs = Date.parse(localToUtc(addDays(weekStart, days), '00:00', utcOffset));
  const opens = minutesOfDay(workStart);
  const closes = minutesOfDay(workEnd);
  const blocks = busy.map((b) => [toMs(b.starts_at), toMs(b.ends_at)]);
  const first = Math.ceil(Math.max(toMs(notBefore), weekStartMs) / gridMs) * gridMs;
  for (let start = first; start + lengthMs <= weekEndMs; start += gridMs) {
    const local = new Date(start + offsetMs);
    const weekday = local.getUTCDay();
    if (weekday === 0 || weekday === 6) continue;
    const minute = local.getUTCHours() * 60 + local.getUTCMinutes();
    if (minute < opens || minute + minutes > closes) continue;
    const end = start + lengthMs;
    if (blocks.every(([s, e]) => !(start < e && end > s))) return { starts_at: isoUtc(start), ends_at: isoUtc(end) };
  }
  return null;
}

/** Expand the seed (local wall-clock times) into full CalendarEvent copies, agenda talks and flags. */
export function expandSeed(seed = SEED) {
  const offset = seed.utc_offset;
  const at = (day, hhmm) => isoUtc(localToUtc(addDays(seed.week_start, day), hhmm, offset));
  const events = seed.events.map((e) => ({
    event_id: e.event_id,
    persona_id: e.persona_id,
    kind: e.kind,
    title: e.title,
    starts_at: at(e.day, e.start),
    ends_at: at(e.end_day ?? e.day, e.end),
    location: e.location ?? '',
    status: e.status ?? 'confirmed',
    capture: e.capture ?? false,
    source: e.source,
    talk_id: e.talk_id ?? null,
    meeting_id: e.meeting_id ?? null,
    with_persona_ids: [...(e.with_persona_ids ?? [])],
    responses: { ...(e.responses ?? {}) },
    note: e.note ?? null,
  }));
  const agenda = seed.agenda.map((t) => {
    const starts = at(t.day, t.start);
    return {
      talk: {
        talk_id: t.talk_id, title: t.title, starts_at: starts, room: t.room, track: t.track,
        speakers: [...(t.speakers ?? [])], reason: null,
      },
      ends_at: isoUtc(Date.parse(starts) + (seed.talk_minutes ?? 30) * MINUTE),
    };
  });
  return {
    events,
    agenda,
    conferenceMode: { ...(seed.conference_mode ?? {}) },
    weekStart: seed.week_start,
    utcOffset: offset,
    timezone: seed.timezone,
    weekStartsAt: at(0, '00:00'),
    weekEndsAt: at(7, '00:00'),
  };
}

function displayName(personaId) {
  const known = person(personaId)?.name;
  if (known) return known;
  const handle = String(personaId).split('.').pop() || String(personaId);
  return handle.charAt(0).toUpperCase() + handle.slice(1);
}

function randomHex(length) {
  const bytes = new Uint8Array(Math.ceil(length / 2));
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('').slice(0, length);
}

const clone = (value) => structuredClone(value);

function cleanTitle(value) {
  const title = typeof value === 'string' ? value.trim() : '';
  if (title.length < 1 || title.length > 120) throw fail(422, 'invalid_title');
  return title;
}

function cleanLocation(value) {
  if (value === undefined || value === null) return '';
  if (typeof value !== 'string') throw fail(422, 'invalid_location');
  const location = value.trim();
  if (location.length > 80) throw fail(422, 'invalid_location');
  return location;
}

function isEvent(value) {
  return value && typeof value === 'object' && typeof value.event_id === 'string'
    && PERSONA_IDS.includes(value.persona_id) && typeof value.starts_at === 'string'
    && typeof value.ends_at === 'string' && typeof value.title === 'string';
}

/** Lowercase words: runs of letters and digits ('Zero-trust' -> zero, trust), so 'ai' never matches 'chain'. */
export function tokenize(text) {
  return String(text).toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(Boolean);
}

const RANK = { pending: 0, accepted: 1, declined: 2 };

/** Merge two answer maps per person: a real answer beats 'pending', and a decline beats an accept. */
export function mergeResponses(a = {}, b = {}) {
  const merged = { ...a };
  for (const [id, answer] of Object.entries(b)) {
    const mine = merged[id];
    if (mine === undefined || (RANK[answer] ?? 0) > (RANK[mine] ?? 0)) merged[id] = answer;
  }
  return merged;
}

/** The status a meeting copy should have given everyone's answers. */
export function meetingStatus(event, responses) {
  const people = new Set([event.persona_id, ...(event.with_persona_ids ?? []), ...Object.keys(responses)]);
  if ([...people].some((id) => responses[id] === 'declined')) return 'declined';
  return [...people].every((id) => responses[id] === 'accepted') ? 'confirmed' : event.status;
}

function byStart(a, b) {
  return toMs(a.starts_at) - toMs(b.starts_at) || (a.title < b.title ? -1 : a.title > b.title ? 1 : 0);
}

// ---------------------------------------------------------------------------------------------------------
// The replica
// ---------------------------------------------------------------------------------------------------------

export class MockCalendar {
  #bus;

  #self;

  #seed;

  #now;

  #events = new Map(); // event_id -> CalendarEvent (every persona's copy)

  #conference = new Map(); // persona_id -> boolean

  #expanded;

  #unsubscribe = null;

  #dirty = false; // true once this replica has changed something itself

  /**
   * @param {{ bus, self: string, seed?: object, now?: () => Date }} options
   * `bus` needs emit(type, data) and emitLocal(type, data); on(type, fn) is used when present.
   */
  constructor({ bus, self, seed = SEED, now = () => new Date() } = {}) {
    this.#bus = bus;
    this.#self = self;
    this.#seed = seed;
    this.#now = now;
    this.reset();
    const offSync = bus?.on?.('calendar:sync', (data, msg) => this.#receive(data, msg));
    const offHello = bus?.on?.('calendar:hello', (_data, msg) => this.#greet(msg));
    this.#unsubscribe = () => {
      offSync?.();
      offHello?.();
    };
    // A phone that builds its replica late (or reloads) asks the other one for the current state.
    bus?.emit?.('calendar:hello', {});
  }

  /** Reload the seed (demo reset). Does not broadcast. */
  reset() {
    this.#expanded = expandSeed(this.#seed);
    this.#events = new Map(this.#expanded.events.map((e) => [e.event_id, e]));
    this.#conference = new Map(PERSONA_IDS.map((id) => [id, this.#expanded.conferenceMode[id] === true]));
  }

  /** Stop listening for the other phone's changes. */
  dispose() {
    this.#unsubscribe?.();
    this.#unsubscribe = null;
  }

  // ---- reads ----------------------------------------------------------------------------------------

  view = async (personaId, { start, days } = {}) => {
    const pid = this.#persona(personaId);
    const startKey = start ?? this.#expanded.weekStart;
    if (!isDateKey(startKey)) throw fail(422, 'invalid_start');
    const count = days ?? 7;
    if (!Number.isInteger(count) || count < 1 || count > 14) throw fail(422, 'invalid_days');
    const from = Date.parse(localToUtc(startKey, '00:00', this.#expanded.utcOffset));
    const to = Date.parse(localToUtc(addDays(startKey, count), '00:00', this.#expanded.utcOffset));
    const events = this.#mine(pid)
      .filter((e) => e.status !== 'declined' && toMs(e.starts_at) < to && toMs(e.ends_at) > from)
      .sort(byStart);
    return clone({
      persona_id: pid,
      timezone: this.#expanded.timezone,
      week_start: this.#expanded.weekStart,
      start: startKey,
      days: count,
      now: isoUtc(this.#clock()),
      conference_mode: this.#conference.get(pid) === true,
      events,
    });
  };

  agenda = async (personaId, q = '') => {
    const pid = this.#persona(personaId);
    const query = typeof q === 'string' ? q.trim() : '';
    if (query.length > 100) throw fail(422, 'invalid_query');
    const words = tokenize(query);
    const mine = new Set(this.#mine(pid).map((e) => e.talk_id).filter(Boolean));
    const items = this.#expanded.agenda
      .filter(({ talk }) => {
        const tokens = new Set(tokenize([talk.title, talk.track, talk.room, ...talk.speakers].join(' ')));
        return words.every((word) => tokens.has(word));
      })
      .sort((a, b) => toMs(a.talk.starts_at) - toMs(b.talk.starts_at))
      .slice(0, AGENDA_LIMIT)
      .map((item) => ({ ...item, in_calendar: mine.has(item.talk.talk_id) }));
    return clone({
      persona_id: pid, timezone: this.#expanded.timezone, source: 'seed', query, items,
    });
  };

  freebusy = async (personaId, start, end) => {
    const pid = this.#persona(personaId);
    const from = parseAware(start);
    const to = parseAware(end);
    if (!(to > from) || to - from > MAX_FREEBUSY_MS) throw fail(422, 'invalid_window');
    const busy = mergeBusy(this.#active(pid).map((e) => ({
      starts_at: isoUtc(Math.max(toMs(e.starts_at), from)),
      ends_at: isoUtc(Math.min(toMs(e.ends_at), to)),
    })));
    return { persona_id: pid, start: isoUtc(from), end: isoUtc(to), busy };
  };

  /** The mock has no server to download from. */
  exportUrl = () => null;

  // ---- writes ---------------------------------------------------------------------------------------

  create = async (body = {}) => {
    const pid = this.#persona(body.persona_id);
    const title = cleanTitle(body.title);
    const location = cleanLocation(body.location);
    if (body.capture !== undefined && typeof body.capture !== 'boolean') throw fail(422, 'invalid_capture');
    const starts = parseAware(body.starts_at);
    const ends = parseAware(body.ends_at);
    this.#checkWindow(starts, ends);
    const result = this.#insert(pid, {
      kind: 'personal', source: 'user', title, starts, ends, location, capture: body.capture === true,
    });
    this.#commit([result.event]);
    return clone(result);
  };

  update = async (eventId, body = {}) => {
    const pid = this.#persona(body.persona_id);
    const current = this.#owned(eventId, pid);
    const given = ['capture', 'title', 'starts_at', 'ends_at', 'location'].filter((k) => body[k] !== undefined && body[k] !== null);
    if (given.length === 0) throw fail(422, 'empty_update');
    if (given.some((k) => k !== 'capture') && current.source !== 'user') throw fail(409, 'not_editable');
    const next = { ...current };
    if (given.includes('capture')) {
      if (typeof body.capture !== 'boolean') throw fail(422, 'invalid_capture');
      next.capture = body.capture;
    }
    if (given.includes('title')) next.title = cleanTitle(body.title);
    if (given.includes('location')) next.location = cleanLocation(body.location);
    if (given.includes('starts_at') || given.includes('ends_at')) {
      const starts = given.includes('starts_at') ? parseAware(body.starts_at) : toMs(current.starts_at);
      const ends = given.includes('ends_at') ? parseAware(body.ends_at) : toMs(current.ends_at);
      this.#checkWindow(starts, ends);
      next.starts_at = isoUtc(starts);
      next.ends_at = isoUtc(ends);
    }
    this.#events.set(next.event_id, next);
    this.#commit([next]);
    return clone(next);
  };

  remove = async (eventId, personaId) => {
    const pid = this.#persona(personaId);
    const current = this.#owned(eventId, pid);
    if (current.source !== 'user' && current.source !== 'conference') throw fail(409, 'not_deletable');
    this.#events.delete(current.event_id);
    this.#commit([], [current.event_id]);
    return null;
  };

  respond = async (eventId, body = {}) => {
    const pid = this.#persona(body.persona_id);
    const current = this.#owned(eventId, pid);
    if (body.response !== 'accept' && body.response !== 'decline') throw fail(422, 'invalid_response');
    if (current.kind !== 'meeting' || !current.meeting_id) throw fail(409, 'not_a_meeting');
    if (current.status === 'declined') throw fail(409, 'meeting_closed');
    const copies = [...this.#events.values()].filter((e) => e.meeting_id === current.meeting_id);
    const responses = { ...current.responses, [pid]: body.response === 'accept' ? 'accepted' : 'declined' };
    const participants = new Set([...Object.keys(responses), ...copies.map((c) => c.persona_id)]);
    for (const id of current.with_persona_ids) participants.add(id);
    participants.add(current.persona_id);
    let status = current.status;
    if (body.response === 'decline') status = 'declined';
    else if ([...participants].every((id) => responses[id] === 'accepted')) status = 'confirmed';
    for (const copy of copies) {
      copy.responses = { ...responses };
      copy.status = status;
    }
    this.#commit(copies);
    return clone(this.#events.get(current.event_id));
  };

  setConferenceMode = async (body = {}) => {
    const pid = this.#persona(body.persona_id);
    if (typeof body.enabled !== 'boolean') throw fail(422, 'invalid_enabled');
    this.#conference.set(pid, body.enabled);
    this.#commit([], [], { [pid]: body.enabled });
    return { persona_id: pid, enabled: body.enabled };
  };

  addTalk = async (body = {}) => {
    const pid = this.#persona(body.persona_id);
    const entry = this.#expanded.agenda.find(({ talk }) => talk.talk_id === body.talk_id);
    if (!entry) throw fail(404, 'unknown_talk');
    if (this.#mine(pid).some((e) => e.talk_id === entry.talk.talk_id)) throw fail(409, 'already_added');
    const result = this.#insert(pid, {
      kind: 'talk',
      source: 'conference',
      title: entry.talk.title,
      starts: toMs(entry.talk.starts_at),
      ends: toMs(entry.ends_at),
      location: entry.talk.room,
      capture: this.#conference.get(pid) === true,
      talk_id: entry.talk.talk_id,
    });
    this.#commit([result.event]);
    return clone(result);
  };

  propose = async (body = {}) => {
    const pid = this.#persona(body.persona_id);
    const other = this.#persona(body.with_persona_id);
    if (other === pid) throw fail(422, 'same_persona');
    const purpose = body.purpose ?? 'coffee';
    if (purpose !== 'coffee' && purpose !== 'meeting') throw fail(422, 'invalid_purpose');
    const minutes = body.duration_minutes ?? 30;
    if (!Number.isInteger(minutes) || minutes < 15 || minutes > 120 || minutes % GRID_MINUTES !== 0) {
      throw fail(422, 'invalid_duration');
    }
    const now = this.#clock();
    const notBefore = body.not_before === undefined || body.not_before === null ? now : parseAware(body.not_before);

    const existing = this.#mine(pid)
      .filter((e) => e.kind === 'meeting' && e.status !== 'declined' && e.with_persona_ids.includes(other)
        && toMs(e.ends_at) > now)
      .sort(byStart)[0];
    if (existing) {
      return clone({
        meeting_id: existing.meeting_id,
        created: false,
        starts_at: existing.starts_at,
        ends_at: existing.ends_at,
        status: existing.status,
        event: existing,
      });
    }

    const slot = firstMutualSlot({
      busy: [...this.#active(pid), ...this.#active(other)],
      notBefore: Math.max(notBefore, now),
      weekStart: this.#expanded.weekStart,
      utcOffset: this.#expanded.utcOffset,
      minutes,
      workStart: this.#seed.working_hours?.start ?? '09:00',
      workEnd: this.#seed.working_hours?.end ?? '18:00',
      grid: this.#seed.slot_minutes ?? GRID_MINUTES,
    });
    if (!slot) throw fail(409, 'no_mutual_slot');
    if (this.#mine(pid).length >= MAX_EVENTS || this.#mine(other).length >= MAX_EVENTS) throw fail(409, 'calendar_full');

    const meetingId = this.#freshId('mtg');
    const coffee = purpose === 'coffee';
    const responses = { [pid]: 'accepted', [other]: 'pending' };
    const copy = (owner, counterparty, note) => this.#build({
      persona_id: owner,
      kind: 'meeting',
      source: 'agent',
      status: 'proposed',
      title: `${coffee ? 'Coffee' : 'Meeting'} with ${displayName(counterparty)}`,
      starts: toMs(slot.starts_at),
      ends: toMs(slot.ends_at),
      location: coffee ? 'Lobby café' : 'Meeting room 2',
      meeting_id: meetingId,
      with_persona_ids: [counterparty],
      responses: { ...responses },
      note,
    });
    const mine = copy(pid, other, `Proposed by your agent · waiting for ${displayName(other)}`);
    const theirs = copy(other, pid, `${displayName(pid)}'s agent proposed this · tap to confirm`);
    this.#events.set(mine.event_id, mine);
    this.#events.set(theirs.event_id, theirs);
    this.#commit([mine, theirs]);
    return clone({
      meeting_id: meetingId, created: true, starts_at: slot.starts_at, ends_at: slot.ends_at, status: 'proposed', event: mine,
    });
  };

  // ---- internals ------------------------------------------------------------------------------------

  #clock() {
    return toMs(this.#now());
  }

  #persona(id) {
    if (typeof id !== 'string' || !PERSONA_IDS.includes(id)) throw fail(404, 'unknown_persona');
    return id;
  }

  #mine(personaId) {
    return [...this.#events.values()].filter((e) => e.persona_id === personaId);
  }

  #active(personaId) {
    return this.#mine(personaId).filter((e) => e.status !== 'declined');
  }

  /** An event that belongs to this persona, else 404 (never reveal another person's event). */
  #owned(eventId, personaId) {
    const event = this.#events.get(eventId);
    if (!event || event.persona_id !== personaId) throw fail(404, 'event_not_found');
    return event;
  }

  #checkWindow(starts, ends) {
    if (!(ends > starts)) throw fail(422, 'invalid_range');
    if (ends - starts > MAX_DURATION_MS) throw fail(422, 'too_long');
    if (starts < toMs(this.#expanded.weekStartsAt) || ends > toMs(this.#expanded.weekEndsAt)) throw fail(422, 'outside_week');
  }

  #freshId(prefix) {
    let id;
    do id = `${prefix}-${randomHex(12)}`; while (this.#events.has(id));
    return id;
  }

  #build(fields) {
    return {
      event_id: this.#freshId('evt'),
      persona_id: fields.persona_id,
      kind: fields.kind,
      title: fields.title,
      starts_at: isoUtc(fields.starts),
      ends_at: isoUtc(fields.ends),
      location: fields.location ?? '',
      status: fields.status ?? 'confirmed',
      capture: fields.capture ?? false,
      source: fields.source,
      talk_id: fields.talk_id ?? null,
      meeting_id: fields.meeting_id ?? null,
      with_persona_ids: fields.with_persona_ids ?? [],
      responses: fields.responses ?? {},
      note: fields.note ?? null,
    };
  }

  /** Add an event to one persona's calendar (cap 200); `conflicts` lists the overlapping events it hit. */
  #insert(personaId, fields) {
    const existing = this.#mine(personaId);
    if (existing.length >= MAX_EVENTS) throw fail(409, 'calendar_full');
    const event = this.#build({ ...fields, persona_id: personaId });
    const conflicts = existing.filter((e) => e.status !== 'declined' && overlap(e, event)).map((e) => e.event_id);
    this.#events.set(event.event_id, event);
    return { event, conflicts };
  }

  /** Tell the other phone what changed. */
  #commit(events, removed = [], conference = {}) {
    this.#dirty = true;
    this.#bus?.emit?.('calendar:sync', {
      events: clone(events), removed: [...removed], conference_mode: { ...conference },
    });
  }

  /** The other phone just built its replica: answer with everything this one knows. */
  #greet(msg) {
    if (msg?.from === this.#self) return;
    this.#bus?.emit?.('calendar:sync', {
      snapshot: true,
      events: clone([...this.#events.values()]),
      removed: [],
      conference_mode: Object.fromEntries(this.#conference),
    });
  }

  /** Apply the other phone's changes and tell this phone's screens to refetch. */
  #receive(data, msg) {
    if (!data || typeof data !== 'object' || msg?.from === this.#self) return;
    const touched = new Set();
    const meetings = new Set();
    const incoming = (Array.isArray(data.events) ? data.events : []).filter(isEvent);
    // A snapshot answers our hello. While nothing here has changed yet it simply replaces the seed state.
    const replace = data.snapshot === true && !this.#dirty;
    const before = replace ? this.#events : null;
    if (replace) this.#events = new Map();
    for (const event of incoming) {
      const copy = clone(event);
      const local = this.#events.get(copy.event_id);
      if (local && copy.meeting_id) {
        // Both phones may answer at the same moment: keep every answer instead of the last writer's copy.
        copy.responses = mergeResponses(local.responses, copy.responses);
      }
      if (copy.meeting_id) meetings.add(copy.meeting_id);
      this.#events.set(copy.event_id, copy);
      if (!replace) touched.add(copy.persona_id);
    }
    for (const meetingId of meetings) this.#reconcile(meetingId);
    if (replace) {
      // Only announce the people whose calendar actually differs from what this phone had.
      const key = (map, id) => JSON.stringify([...map.values()].filter((e) => e.persona_id === id)
        .sort((x, y) => (x.event_id < y.event_id ? -1 : 1)));
      for (const id of PERSONA_IDS) if (key(before, id) !== key(this.#events, id)) touched.add(id);
    }
    for (const id of Array.isArray(data.removed) ? data.removed : []) {
      const old = this.#events.get(id);
      if (!old) continue;
      this.#events.delete(id);
      touched.add(old.persona_id);
    }
    for (const [id, enabled] of Object.entries(data.conference_mode ?? {})) {
      if (!PERSONA_IDS.includes(id) || typeof enabled !== 'boolean') continue;
      if (replace && this.#conference.get(id) === enabled) continue;
      this.#conference.set(id, enabled);
      touched.add(id);
    }
    if (touched.size > 0) this.#bus?.emitLocal?.('calendar:changed', { persona_ids: [...touched] });
  }

  /** Give every copy of a meeting the same merged answers and the status they imply. */
  #reconcile(meetingId) {
    const copies = [...this.#events.values()].filter((e) => e.meeting_id === meetingId);
    const responses = copies.reduce((acc, copy) => mergeResponses(acc, copy.responses), {});
    for (const copy of copies) {
      copy.responses = { ...responses };
      copy.status = copy.status === 'declined' ? 'declined' : meetingStatus(copy, responses);
    }
  }
}
