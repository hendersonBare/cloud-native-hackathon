import test, { after, before, describe } from 'node:test';
import assert from 'node:assert/strict';
import SEED from '../mock/calendar-seed.json' with { type: 'json' };
import {
  MockCalendar, PERSONA_IDS, expandSeed, firstMutualSlot, isoUtc, mergeBusy, mergeResponses, meetingStatus, overlap, parseAware,
  tokenize,
} from '../app/calendar-mock.js';
import {
  announcing, calendarClient, calendarErrorMessage, liveCalendar,
} from '../app/calendar-api.js';

const clone = (value) => structuredClone(value);
const AVA = 'acme.ava';
const BO = 'bluefin.bo';
const SAM = 'acme.sam';

// Monday 2026-11-09 08:07 in Denver (MST, UTC-7).
const MONDAY_MORNING = '2026-11-09T15:07:00Z';

/** A tiny bus: records what the calendar emits and lets a test deliver messages to its listeners. */
function fakeBus(self) {
  const handlers = new Map();
  const bus = {
    self,
    emitted: [],
    local: [],
    peers: [],
    on(type, fn) {
      if (!handlers.has(type)) handlers.set(type, new Set());
      handlers.get(type).add(fn);
      return () => handlers.get(type).delete(fn);
    },
    emit(type, data) {
      this.emitted.push({ type, data });
      const msg = { type, data, from: self };
      for (const fn of handlers.get(type) ?? []) fn(data, msg);
      for (const peer of this.peers) peer.deliver(type, data, self);
    },
    emitLocal(type, data) {
      this.local.push({ type, data });
    },
    deliver(type, data, from) {
      for (const fn of handlers.get(type) ?? []) fn(data, { type, data, from });
    },
  };
  return bus;
}

function mockAt(now = MONDAY_MORNING, self = AVA) {
  const bus = fakeBus(self);
  const calendar = new MockCalendar({ bus, self, now: () => new Date(now) });
  return { bus, calendar };
}

/** Two phones whose buses deliver to each other, like the BroadcastChannel does. */
function phones(now = MONDAY_MORNING) {
  const a = fakeBus(AVA);
  const b = fakeBus(BO);
  a.peers.push(b);
  b.peers.push(a);
  const clock = () => new Date(now);
  return {
    a, b,
    ava: new MockCalendar({ bus: a, self: AVA, now: clock }),
    bo: new MockCalendar({ bus: b, self: BO, now: clock }),
  };
}

const rejectsWith = (promise, status, code) => assert.rejects(promise, (error) => {
  assert.equal(error.status, status);
  if (code) assert.equal(error.code, code);
  return true;
});

const personal = (over = {}) => ({
  persona_id: AVA,
  title: 'Dentist',
  starts_at: '2026-11-12T16:00:00Z',
  ends_at: '2026-11-12T17:00:00Z',
  ...over,
});

// ---------------------------------------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------------------------------------

test('the seed expands to aware UTC times using the seed offset', () => {
  const { events, agenda, conferenceMode, weekStartsAt, weekEndsAt } = expandSeed(SEED);
  assert.equal(events.length, SEED.events.length);
  const byId = Object.fromEntries(events.map((e) => [e.event_id, e]));
  assert.equal(byId['evt-ava-keynote'].starts_at, '2026-11-09T16:00:00Z');
  assert.equal(byId['evt-ava-keynote'].ends_at, '2026-11-09T17:00:00Z');
  assert.equal(byId['evt-ava-otel'].starts_at, '2026-11-09T20:30:00Z');
  assert.equal(byId['evt-ava-priya'].starts_at, '2026-11-10T22:00:00Z');
  assert.equal(byId['evt-ava-dinner'].starts_at, '2026-11-10T01:30:00Z', '18:30 MST is the next UTC day');
  assert.equal(byId['evt-ava-dinner'].ends_at, '2026-11-10T03:00:00Z');
  assert.equal(weekStartsAt, '2026-11-09T07:00:00Z');
  assert.equal(weekEndsAt, '2026-11-16T07:00:00Z');
  assert.deepEqual(conferenceMode, { [AVA]: true, [BO]: true });
  const talk = agenda.find((item) => item.talk.talk_id === 'talk-ebpf-zero-code');
  assert.equal(talk.talk.starts_at, '2026-11-09T22:30:00Z');
  assert.equal(talk.ends_at, '2026-11-09T23:00:00Z');
});

test('seed events get the contract defaults', () => {
  const { events } = expandSeed(SEED);
  const keynote = events.find((e) => e.event_id === 'evt-ava-keynote');
  assert.deepEqual(
    { ...keynote, starts_at: undefined, ends_at: undefined },
    {
      event_id: 'evt-ava-keynote', persona_id: AVA, kind: 'talk', title: 'Opening keynotes', starts_at: undefined,
      ends_at: undefined, location: 'Main hall', status: 'confirmed', capture: true, source: 'seed', talk_id: null,
      meeting_id: null, with_persona_ids: [], responses: {}, note: null,
    },
  );
});

test('every seeded persona is one of the twelve conference personas', () => {
  assert.equal(PERSONA_IDS.length, 12);
  for (const event of SEED.events) assert.ok(PERSONA_IDS.includes(event.persona_id), event.persona_id);
});

test('overlap is half-open: touching events do not overlap', () => {
  const a = { starts_at: '2026-11-09T16:00:00Z', ends_at: '2026-11-09T17:00:00Z' };
  assert.equal(overlap(a, { starts_at: '2026-11-09T16:30:00Z', ends_at: '2026-11-09T17:30:00Z' }), true);
  assert.equal(overlap(a, { starts_at: '2026-11-09T17:00:00Z', ends_at: '2026-11-09T18:00:00Z' }), false);
  assert.equal(overlap(a, { starts_at: '2026-11-09T15:00:00Z', ends_at: '2026-11-09T16:00:00Z' }), false);
  assert.equal(overlap(a, { starts_at: '2026-11-09T16:10:00Z', ends_at: '2026-11-09T16:20:00Z' }), true);
});

test('mergeBusy sorts and joins overlapping and touching blocks', () => {
  const merged = mergeBusy([
    { starts_at: '2026-11-09T18:00:00Z', ends_at: '2026-11-09T19:00:00Z' },
    { starts_at: '2026-11-09T16:00:00Z', ends_at: '2026-11-09T17:00:00Z' },
    { starts_at: '2026-11-09T16:30:00Z', ends_at: '2026-11-09T17:30:00Z' },
    { starts_at: '2026-11-09T17:30:00Z', ends_at: '2026-11-09T17:45:00Z' },
    { starts_at: '2026-11-09T20:00:00Z', ends_at: '2026-11-09T20:00:00Z' },
  ]);
  assert.deepEqual(merged, [
    { starts_at: '2026-11-09T16:00:00Z', ends_at: '2026-11-09T17:45:00Z' },
    { starts_at: '2026-11-09T18:00:00Z', ends_at: '2026-11-09T19:00:00Z' },
  ]);
});

test('parseAware rejects naive datetimes and isoUtc drops a zero fraction', () => {
  assert.throws(() => parseAware('2026-11-09T10:00:00'), (e) => e.status === 422);
  assert.throws(() => parseAware('not a date'), (e) => e.status === 422);
  assert.throws(() => parseAware(42), (e) => e.status === 422);
  assert.equal(parseAware('2026-11-09T10:00:00-07:00'), Date.parse('2026-11-09T17:00:00Z'));
  assert.equal(isoUtc(Date.parse('2026-11-09T17:00:00Z')), '2026-11-09T17:00:00Z');
});

test('firstMutualSlot rounds up to the 15-minute grid and honours working hours', () => {
  const options = { busy: [], weekStart: '2026-11-09', utcOffset: '-07:00', minutes: 30 };
  assert.deepEqual(
    firstMutualSlot({ ...options, notBefore: '2026-11-09T16:07:00Z' }),
    { starts_at: '2026-11-09T16:15:00Z', ends_at: '2026-11-09T16:45:00Z' },
  );
  assert.equal(
    firstMutualSlot({ ...options, notBefore: '2026-11-09T16:15:00Z' }).starts_at,
    '2026-11-09T16:15:00Z',
    'a boundary start is kept',
  );
  assert.equal(
    firstMutualSlot({ ...options, notBefore: '2026-11-09T02:00:00Z' }).starts_at,
    '2026-11-09T16:00:00Z',
    'before 09:00 local the first slot is 09:00',
  );
  assert.equal(
    firstMutualSlot({ ...options, notBefore: '2026-11-10T00:45:00Z' }).starts_at,
    '2026-11-10T16:00:00Z',
    'after 17:30 local the next day starts at 09:00',
  );
});

test('firstMutualSlot skips weekends and meetings that would end after 18:00', () => {
  const options = { busy: [], weekStart: '2026-11-09', utcOffset: '-07:00', minutes: 30 };
  // Friday 17:45 local: a 30-minute meeting would end at 18:15, and Saturday/Sunday are not working days.
  assert.equal(firstMutualSlot({ ...options, notBefore: '2026-11-14T00:45:00Z' }), null);
  assert.equal(firstMutualSlot({ ...options, notBefore: '2026-11-13T00:30:00Z' }).starts_at, '2026-11-13T00:30:00Z',
    'Thursday 17:30 local fits exactly');
});

test('firstMutualSlot avoids busy blocks from both people', () => {
  const busy = [
    { starts_at: '2026-11-09T16:00:00Z', ends_at: '2026-11-09T17:00:00Z' },
    { starts_at: '2026-11-09T17:00:00Z', ends_at: '2026-11-09T17:20:00Z' },
  ];
  const slot = firstMutualSlot({
    busy, notBefore: '2026-11-09T15:00:00Z', weekStart: '2026-11-09', utcOffset: '-07:00', minutes: 30,
  });
  assert.equal(slot.starts_at, '2026-11-09T17:30:00Z', '10:20 would overlap, so the grid gives 10:30');
});

// ---------------------------------------------------------------------------------------------------------
// MockCalendar: reads
// ---------------------------------------------------------------------------------------------------------

test('the mock exposes the same methods as the live client, as own properties', () => {
  const { calendar } = mockAt();
  const names = Object.keys(liveCalendar(async () => null)).sort();
  assert.deepEqual(Object.keys(calendar).sort(), names);
  const spread = { ...calendar };
  for (const name of names) assert.equal(typeof spread[name], 'function', name);
  assert.equal(calendar.exportUrl(AVA), null);
});

test('view returns the persona week sorted, with the zone, flags and server clock', async () => {
  const { calendar } = mockAt();
  const view = await calendar.view(AVA);
  assert.equal(view.persona_id, AVA);
  assert.equal(view.timezone, 'America/Denver');
  assert.equal(view.week_start, '2026-11-09');
  assert.equal(view.start, '2026-11-09');
  assert.equal(view.days, 7);
  assert.equal(view.now, MONDAY_MORNING);
  assert.equal(view.conference_mode, true);
  assert.deepEqual(view.events.map((e) => e.event_id), [
    'evt-ava-keynote', 'evt-ava-otel', 'evt-ava-ebpf', 'evt-ava-edge', 'evt-ava-dinner', 'evt-ava-priya', 'evt-ava-bo',
  ]);
  const starts = view.events.map((e) => e.starts_at);
  assert.deepEqual(starts, [...starts].sort());
  assert.ok(view.events.every((e) => e.persona_id === AVA));
});

test('view windows by local day and breaks ties by title', async () => {
  const { calendar } = mockAt();
  const wednesday = await calendar.view(AVA, { start: '2026-11-11', days: 1 });
  assert.deepEqual(wednesday.events.map((e) => e.event_id), ['evt-ava-bo']);
  const monday = await calendar.view(AVA, { start: '2026-11-09', days: 1 });
  assert.equal(monday.events.length, 5, 'the 18:30 dinner is still Monday locally although it is Tuesday in UTC');
  await calendar.create(personal({
    title: 'Aardvark', starts_at: '2026-11-09T16:00:00Z', ends_at: '2026-11-09T16:30:00Z',
  }));
  const tie = (await calendar.view(AVA, { start: '2026-11-09', days: 1 })).events.slice(0, 2).map((e) => e.title);
  assert.deepEqual(tie, ['Aardvark', 'Opening keynotes']);
});

test('view validates start and days, and unknown personas are 404', async () => {
  const { calendar } = mockAt();
  await rejectsWith(calendar.view(AVA, { start: '2026-02-31' }), 422);
  await rejectsWith(calendar.view(AVA, { start: 'tomorrow' }), 422);
  await rejectsWith(calendar.view(AVA, { days: 0 }), 422);
  await rejectsWith(calendar.view(AVA, { days: 15 }), 422);
  await rejectsWith(calendar.view('nobody.here'), 404, 'unknown_persona');
  const sam = await calendar.view(SAM);
  assert.deepEqual(sam.events, []);
  assert.equal(sam.conference_mode, false);
});

test('responses are deep copies: screens cannot mutate the replica', async () => {
  const { calendar } = mockAt();
  const view = await calendar.view(AVA);
  view.events[0].title = 'Hacked';
  view.events.pop();
  view.conference_mode = false;
  const again = await calendar.view(AVA);
  assert.equal(again.events[0].title, 'Opening keynotes');
  assert.equal(again.events.length, 7);
  assert.equal(again.conference_mode, true);
});

// ---------------------------------------------------------------------------------------------------------
// MockCalendar: create / update / remove
// ---------------------------------------------------------------------------------------------------------

test('create adds a confirmed personal event the owner can see', async () => {
  const { calendar } = mockAt();
  const { event, conflicts } = await calendar.create(personal({ title: '  Dentist  ', location: ' Downtown ' }));
  assert.match(event.event_id, /^evt-[0-9a-f]{12}$/);
  assert.equal(event.title, 'Dentist');
  assert.equal(event.location, 'Downtown');
  assert.equal(event.kind, 'personal');
  assert.equal(event.source, 'user');
  assert.equal(event.status, 'confirmed');
  assert.equal(event.capture, false);
  assert.deepEqual(conflicts, []);
  const view = await calendar.view(AVA);
  assert.ok(view.events.some((e) => e.event_id === event.event_id));
  const bo = await calendar.view(BO);
  assert.ok(!bo.events.some((e) => e.event_id === event.event_id));
});

test('create reports overlapping events as conflicts without failing', async () => {
  const { calendar } = mockAt();
  const { conflicts } = await calendar.create(personal({
    starts_at: '2026-11-09T16:30:00Z', ends_at: '2026-11-09T17:30:00Z',
  }));
  assert.deepEqual(conflicts, ['evt-ava-keynote']);
  const touching = await calendar.create(personal({
    starts_at: '2026-11-09T17:00:00Z', ends_at: '2026-11-09T17:30:00Z',
  }));
  assert.ok(!touching.conflicts.includes('evt-ava-keynote'), 'ending exactly when the next event starts is not a conflict');
});

test('create validates title, location, capture, datetimes and the conference week', async () => {
  const { calendar } = mockAt();
  await rejectsWith(calendar.create(personal({ title: '   ' })), 422);
  await rejectsWith(calendar.create(personal({ title: 'x'.repeat(121) })), 422);
  await rejectsWith(calendar.create(personal({ location: 'x'.repeat(81) })), 422);
  await rejectsWith(calendar.create(personal({ capture: 'yes' })), 422);
  await rejectsWith(calendar.create(personal({ starts_at: '2026-11-12T10:00:00' })), 422);
  await rejectsWith(calendar.create(personal({ ends_at: '2026-11-12T16:00:00Z' })), 422);
  await rejectsWith(calendar.create(personal({ ends_at: '2026-11-12T15:00:00Z' })), 422);
  await rejectsWith(calendar.create(personal({ ends_at: '2026-11-13T05:00:01Z' })), 422, 'too_long');
  await rejectsWith(calendar.create(personal({
    starts_at: '2026-11-09T06:59:00Z', ends_at: '2026-11-09T08:00:00Z',
  })), 422, 'outside_week');
  await rejectsWith(calendar.create(personal({
    starts_at: '2026-11-16T06:00:00Z', ends_at: '2026-11-16T07:30:00Z',
  })), 422, 'outside_week');
  await rejectsWith(calendar.create(personal({ persona_id: 'nobody.here' })), 404, 'unknown_persona');
  const ok = await calendar.create(personal({
    starts_at: '2026-11-09T07:00:00Z', ends_at: '2026-11-09T19:00:00Z',
  }));
  assert.equal(ok.event.title, 'Dentist', 'exactly 12 hours from the first instant of the week is allowed');
});

test('a person can hold at most 200 events', async () => {
  const { calendar } = mockAt();
  const have = (await calendar.view(AVA)).events.length;
  for (let i = have; i < 200; i += 1) await calendar.create(personal({ title: `Block ${i}` }));
  await rejectsWith(calendar.create(personal({ title: 'One too many' })), 409, 'calendar_full');
});

test('update changes capture on any event, and the rest only on the owner own events', async () => {
  const { calendar } = mockAt();
  const toggled = await calendar.update('evt-ava-keynote', { persona_id: AVA, capture: false });
  assert.equal(toggled.capture, false);
  assert.equal((await calendar.view(AVA)).events[0].capture, false);

  await rejectsWith(calendar.update('evt-ava-keynote', { persona_id: AVA, title: 'Renamed' }), 409, 'not_editable');
  await rejectsWith(calendar.update('evt-ava-keynote', { persona_id: AVA, capture: true, location: 'Elsewhere' }), 409);
  await rejectsWith(calendar.update('evt-ava-keynote', { persona_id: AVA }), 422);
  await rejectsWith(calendar.update('evt-ava-keynote', { persona_id: AVA, capture: 'yes' }), 422);

  const { event } = await calendar.create(personal());
  const edited = await calendar.update(event.event_id, {
    persona_id: AVA, title: 'Physio', location: 'Clinic', ends_at: '2026-11-12T18:00:00Z',
  });
  assert.equal(edited.title, 'Physio');
  assert.equal(edited.location, 'Clinic');
  assert.equal(edited.ends_at, '2026-11-12T18:00:00Z');
  await rejectsWith(calendar.update(event.event_id, { persona_id: AVA, ends_at: '2026-11-12T15:00:00Z' }), 422);
  await rejectsWith(calendar.update(event.event_id, { persona_id: AVA, title: '' }), 422);
});

test('another persona event is never revealed: update, remove and respond answer 404', async () => {
  const { calendar } = mockAt();
  await rejectsWith(calendar.update('evt-bo-keynote', { persona_id: AVA, capture: false }), 404, 'event_not_found');
  await rejectsWith(calendar.remove('evt-bo-keynote', AVA), 404, 'event_not_found');
  await rejectsWith(calendar.respond('evt-bo-ava', { persona_id: AVA, response: 'accept' }), 404, 'event_not_found');
  await rejectsWith(calendar.update('evt-missing', { persona_id: AVA, capture: false }), 404);
});

test('remove deletes user and conference events only', async () => {
  const { calendar } = mockAt();
  const { event } = await calendar.create(personal());
  assert.equal(await calendar.remove(event.event_id, AVA), null);
  assert.ok(!(await calendar.view(AVA)).events.some((e) => e.event_id === event.event_id));
  await rejectsWith(calendar.remove(event.event_id, AVA), 404);

  assert.equal(await calendar.remove('evt-ava-otel', AVA), null, 'a talk added from the agenda is removable');
  await rejectsWith(calendar.remove('evt-ava-keynote', AVA), 409, 'not_deletable');
  await rejectsWith(calendar.remove('evt-ava-dinner', AVA), 409, 'not_deletable');
  await rejectsWith(calendar.remove('evt-ava-priya', AVA), 409, 'not_deletable');
  await rejectsWith(calendar.remove('evt-ava-bo', AVA), 409, 'not_deletable');
});

// ---------------------------------------------------------------------------------------------------------
// MockCalendar: respond / conference mode
// ---------------------------------------------------------------------------------------------------------

test('both people accepting confirms the meeting on every copy', async () => {
  const { calendar } = mockAt();
  const first = await calendar.respond('evt-ava-bo', { persona_id: AVA, response: 'accept' });
  assert.equal(first.status, 'proposed');
  assert.equal(first.responses[AVA], 'accepted');
  assert.equal(first.responses[BO], 'pending');
  const boWhileWaiting = (await calendar.view(BO)).events.find((e) => e.event_id === 'evt-bo-ava');
  assert.deepEqual(boWhileWaiting.responses, { [AVA]: 'accepted', [BO]: 'pending' }, 'responses match on every copy');

  const second = await calendar.respond('evt-bo-ava', { persona_id: BO, response: 'accept' });
  assert.equal(second.status, 'confirmed');
  const avaCopy = (await calendar.view(AVA)).events.find((e) => e.event_id === 'evt-ava-bo');
  const boCopy = (await calendar.view(BO)).events.find((e) => e.event_id === 'evt-bo-ava');
  assert.equal(avaCopy.status, 'confirmed');
  assert.equal(boCopy.status, 'confirmed');
  assert.deepEqual(avaCopy.responses, { [AVA]: 'accepted', [BO]: 'accepted' });
  assert.deepEqual(boCopy.responses, avaCopy.responses);
});

test('declining marks every copy declined and frees the slot for both', async () => {
  const { calendar } = mockAt();
  const declined = await calendar.respond('evt-bo-ava', { persona_id: BO, response: 'decline' });
  assert.equal(declined.status, 'declined');
  assert.equal(declined.responses[BO], 'declined');
  assert.ok(!(await calendar.view(AVA)).events.some((e) => e.event_id === 'evt-ava-bo'));
  assert.ok(!(await calendar.view(BO)).events.some((e) => e.event_id === 'evt-bo-ava'));
  const busy = await calendar.freebusy(AVA, '2026-11-11T00:00:00-07:00', '2026-11-12T00:00:00-07:00');
  assert.deepEqual(busy.busy, [], 'the declined slot is free again');
  await rejectsWith(calendar.respond('evt-ava-bo', { persona_id: AVA, response: 'accept' }), 409, 'meeting_closed');
});

test('respond only applies to meetings and accepts only accept or decline', async () => {
  const { calendar } = mockAt();
  await rejectsWith(calendar.respond('evt-ava-keynote', { persona_id: AVA, response: 'accept' }), 409, 'not_a_meeting');
  await rejectsWith(calendar.respond('evt-ava-bo', { persona_id: AVA, response: 'maybe' }), 422);
  const already = await calendar.respond('evt-ava-priya', { persona_id: AVA, response: 'accept' });
  assert.equal(already.status, 'confirmed', 'accepting a confirmed meeting changes nothing');
});

test('conference mode is per person and sets capture on talks added afterwards', async () => {
  const { calendar } = mockAt();
  assert.deepEqual(await calendar.setConferenceMode({ persona_id: SAM, enabled: true }), { persona_id: SAM, enabled: true });
  assert.equal((await calendar.view(SAM)).conference_mode, true);
  assert.equal((await calendar.view(AVA)).conference_mode, true);
  const { event } = await calendar.addTalk({ persona_id: SAM, talk_id: 'talk-platform-golden-paths' });
  assert.equal(event.capture, true);
  await calendar.setConferenceMode({ persona_id: SAM, enabled: false });
  const second = await calendar.addTalk({ persona_id: SAM, talk_id: 'talk-hipaa-k8s' });
  assert.equal(second.event.capture, false);
  const existing = (await calendar.view(SAM)).events.find((e) => e.event_id === event.event_id);
  assert.equal(existing.capture, true, 'existing events are not rewritten');
  await rejectsWith(calendar.setConferenceMode({ persona_id: SAM, enabled: 'on' }), 422);
  await rejectsWith(calendar.setConferenceMode({ persona_id: 'nobody.here', enabled: true }), 404);
});

// ---------------------------------------------------------------------------------------------------------
// MockCalendar: capture on a talk is a plain update
// ---------------------------------------------------------------------------------------------------------

test('capture can be turned off and on again for one session', async () => {
  const { calendar } = mockAt();
  await calendar.update('evt-ava-edge', { persona_id: AVA, capture: false });
  const off = (await calendar.view(AVA)).events.find((e) => e.event_id === 'evt-ava-edge');
  assert.equal(off.capture, false);
  await calendar.update('evt-ava-edge', { persona_id: AVA, capture: true });
  const on = (await calendar.view(AVA)).events.find((e) => e.event_id === 'evt-ava-edge');
  assert.equal(on.capture, true);
});

// ---------------------------------------------------------------------------------------------------------
// MockCalendar: agenda
// ---------------------------------------------------------------------------------------------------------

test('agenda lists the seed sorted by start and marks talks already on the calendar', async () => {
  const { calendar } = mockAt();
  const agenda = await calendar.agenda(AVA);
  assert.equal(agenda.source, 'seed');
  assert.equal(agenda.query, '');
  assert.equal(agenda.timezone, 'America/Denver');
  assert.equal(agenda.items.length, SEED.agenda.length);
  const starts = agenda.items.map((i) => i.talk.starts_at);
  assert.deepEqual(starts, [...starts].sort());
  const flags = Object.fromEntries(agenda.items.map((i) => [i.talk.talk_id, i.in_calendar]));
  assert.equal(flags['talk-ebpf-zero-code'], true);
  assert.equal(flags['talk-ebpf-edge'], true);
  assert.equal(flags['talk-ebpf-cost'], false);
  const item = agenda.items[0];
  assert.deepEqual(Object.keys(item).sort(), ['ends_at', 'in_calendar', 'talk']);
  assert.equal(Date.parse(item.ends_at) - Date.parse(item.talk.starts_at), 30 * 60 * 1000);
});

test('agenda matches words case-insensitively across title, track, room and speakers', async () => {
  const { calendar } = mockAt();
  const ids = async (q) => (await calendar.agenda(AVA, q)).items.map((i) => i.talk.talk_id).sort();
  assert.deepEqual(await ids('EBPF'), ['talk-ebpf-cost', 'talk-ebpf-edge', 'talk-ebpf-zero-code']);
  assert.deepEqual(await ids('ebpf robots'), ['talk-ebpf-edge']);
  assert.deepEqual(await ids('priya'), ['talk-ebpf-cost'], 'speakers are searched');
  assert.deepEqual(await ids('opentelemetry'), ['talk-otel-collector-scale', 'talk-otel-regulated']);
  assert.deepEqual(await ids('security hipaa'), ['talk-hipaa-k8s', 'talk-supply-chain', 'talk-zero-trust-mesh']);
  assert.deepEqual(await ids('  Guardrails  '), ['talk-ai-agents-guardrails'], 'the query is trimmed');
  assert.deepEqual(await ids('no such talk'), []);
  assert.ok(!(await ids('ai')).includes('talk-supply-chain'), "'ai' is a word, not a substring of 'chain'");
  assert.deepEqual(await ids('ai'), ['talk-agent-protocols', 'talk-ai-agents-guardrails']);
  assert.deepEqual(await ids('zero-code'), ['talk-ebpf-zero-code'], 'hyphenated queries split into words');
  assert.deepEqual(tokenize('Zero-trust, AI Agents!'), ['zero', 'trust', 'ai', 'agents']);
  await rejectsWith(calendar.agenda(AVA, 'x'.repeat(101)), 422);
  await rejectsWith(calendar.agenda('nobody.here'), 404);
});

test('addTalk creates a 30-minute conference event at the room, reports conflicts and refuses duplicates', async () => {
  const { calendar } = mockAt();
  const { event, conflicts } = await calendar.addTalk({ persona_id: AVA, talk_id: 'talk-supply-chain' });
  assert.equal(event.kind, 'talk');
  assert.equal(event.source, 'conference');
  assert.equal(event.status, 'confirmed');
  assert.equal(event.talk_id, 'talk-supply-chain');
  assert.equal(event.location, 'Room A');
  assert.equal(event.starts_at, '2026-11-09T23:00:00Z');
  assert.equal(event.ends_at, '2026-11-09T23:30:00Z');
  assert.equal(event.capture, true, 'Ava is in conference mode');
  assert.deepEqual(conflicts, ['evt-ava-edge'], 'the 16:00 talk overlaps the other 16:00 session, not the one ending at 16:00');
  const agenda = await calendar.agenda(AVA, 'supply');
  assert.equal(agenda.items[0].in_calendar, true);
  await rejectsWith(calendar.addTalk({ persona_id: AVA, talk_id: 'talk-supply-chain' }), 409, 'already_added');
  await rejectsWith(calendar.addTalk({ persona_id: AVA, talk_id: 'talk-nope' }), 404, 'unknown_talk');
  await rejectsWith(calendar.addTalk({ persona_id: 'nobody.here', talk_id: 'talk-supply-chain' }), 404, 'unknown_persona');
});

// ---------------------------------------------------------------------------------------------------------
// MockCalendar: propose
// ---------------------------------------------------------------------------------------------------------

test('propose books the first mutual slot and creates a templated copy for each person', async () => {
  const { calendar } = mockAt();
  const proposal = await calendar.propose({ persona_id: AVA, with_persona_id: SAM });
  assert.equal(proposal.created, true);
  assert.equal(proposal.status, 'proposed');
  assert.match(proposal.meeting_id, /^mtg-[0-9a-f]{12}$/);
  assert.equal(proposal.starts_at, '2026-11-09T17:00:00Z', 'Ava keynote runs 09:00-10:00, so 10:00 local is first');
  assert.equal(proposal.ends_at, '2026-11-09T17:30:00Z');
  const mine = proposal.event;
  assert.equal(mine.persona_id, AVA);
  assert.equal(mine.kind, 'meeting');
  assert.equal(mine.source, 'agent');
  assert.equal(mine.title, 'Coffee with Sam');
  assert.equal(mine.location, 'Lobby café');
  assert.deepEqual(mine.with_persona_ids, [SAM]);
  assert.deepEqual(mine.responses, { [AVA]: 'accepted', [SAM]: 'pending' });
  assert.equal(mine.note, 'Proposed by your agent · waiting for Sam');
  const theirs = (await calendar.view(SAM)).events.find((e) => e.meeting_id === proposal.meeting_id);
  assert.equal(theirs.title, 'Coffee with Ava');
  assert.equal(theirs.persona_id, SAM);
  assert.equal(theirs.status, 'proposed');
  assert.equal(theirs.note, "Ava's agent proposed this · tap to confirm");
  assert.deepEqual(theirs.responses, mine.responses);
});

test('propose is deterministic for a fixed clock and supports meetings and not_before', async () => {
  const first = await mockAt().calendar.propose({ persona_id: AVA, with_persona_id: SAM, purpose: 'meeting', duration_minutes: 45 });
  const second = await mockAt().calendar.propose({ persona_id: AVA, with_persona_id: SAM, purpose: 'meeting', duration_minutes: 45 });
  assert.equal(first.starts_at, second.starts_at);
  assert.equal(first.event.title, 'Meeting with Sam');
  assert.equal(first.event.location, 'Meeting room 2');
  assert.equal(Date.parse(first.ends_at) - Date.parse(first.starts_at), 45 * 60 * 1000);

  const tuesday = await mockAt().calendar.propose({
    persona_id: AVA, with_persona_id: SAM, not_before: '2026-11-10T09:00:00-07:00',
  });
  assert.equal(tuesday.starts_at, '2026-11-10T16:00:00Z');
  const past = await mockAt().calendar.propose({
    persona_id: AVA, with_persona_id: SAM, not_before: '2026-11-01T00:00:00Z',
  });
  assert.equal(past.starts_at, '2026-11-09T17:00:00Z', 'a not_before in the past never beats the clock');
});

test('propose with a seeded partner returns the existing meeting with created false', async () => {
  const { calendar } = mockAt();
  const proposal = await calendar.propose({ persona_id: AVA, with_persona_id: BO });
  assert.equal(proposal.created, false);
  assert.equal(proposal.meeting_id, 'mtg-ava-bo');
  assert.equal(proposal.status, 'proposed');
  assert.equal(proposal.starts_at, '2026-11-11T17:00:00Z');
  assert.equal(proposal.event.event_id, 'evt-ava-bo');
  const priya = await calendar.propose({ persona_id: 'lumenly.priya', with_persona_id: AVA });
  assert.equal(priya.created, false);
  assert.equal(priya.status, 'confirmed');
  assert.equal((await calendar.view(AVA)).events.filter((e) => e.kind === 'meeting').length, 2, 'nothing new was created');
});

test('propose twice for the same pair does not double-book', async () => {
  const { calendar } = mockAt();
  const first = await calendar.propose({ persona_id: AVA, with_persona_id: SAM });
  const again = await calendar.propose({ persona_id: SAM, with_persona_id: AVA });
  assert.equal(again.created, false);
  assert.equal(again.meeting_id, first.meeting_id);
});

test('a declined proposal frees its slot and the same pair can be proposed again', async () => {
  const { calendar } = mockAt();
  const first = await calendar.propose({ persona_id: AVA, with_persona_id: SAM });
  await calendar.respond(first.event.event_id, { persona_id: AVA, response: 'decline' });
  const retry = await calendar.propose({ persona_id: AVA, with_persona_id: SAM });
  assert.equal(retry.created, true);
  assert.equal(retry.starts_at, first.starts_at);
  assert.notEqual(retry.meeting_id, first.meeting_id);
});

test('propose answers 409 no_mutual_slot when the invitee is fully booked', async () => {
  const { calendar } = mockAt();
  for (const day of ['09', '10', '11', '12', '13']) {
    await calendar.create({
      persona_id: SAM, title: 'Booked', starts_at: `2026-11-${day}T09:00:00-07:00`, ends_at: `2026-11-${day}T18:00:00-07:00`,
    });
  }
  await rejectsWith(calendar.propose({ persona_id: AVA, with_persona_id: SAM }), 409, 'no_mutual_slot');
  const late = mockAt('2026-11-14T00:45:00Z').calendar;
  await rejectsWith(late.propose({ persona_id: AVA, with_persona_id: SAM }), 409, 'no_mutual_slot');
});

test('propose validates the personas, the duration and the purpose', async () => {
  const { calendar } = mockAt();
  await rejectsWith(calendar.propose({ persona_id: AVA, with_persona_id: AVA }), 422);
  await rejectsWith(calendar.propose({ persona_id: AVA, with_persona_id: SAM, duration_minutes: 20 }), 422);
  await rejectsWith(calendar.propose({ persona_id: AVA, with_persona_id: SAM, duration_minutes: 135 }), 422);
  await rejectsWith(calendar.propose({ persona_id: AVA, with_persona_id: SAM, duration_minutes: 0 }), 422);
  await rejectsWith(calendar.propose({ persona_id: AVA, with_persona_id: SAM, purpose: 'party' }), 422);
  await rejectsWith(calendar.propose({ persona_id: AVA, with_persona_id: SAM, not_before: '2026-11-10T09:00:00' }), 422);
  await rejectsWith(calendar.propose({ persona_id: AVA, with_persona_id: 'nobody.here' }), 404, 'unknown_persona');
  await rejectsWith(calendar.propose({ persona_id: 'nobody.here', with_persona_id: SAM }), 404, 'unknown_persona');
});

test('propose names personas that the demo cast does not include', async () => {
  const { calendar } = mockAt();
  const proposal = await calendar.propose({ persona_id: AVA, with_persona_id: 'kestrel.raj' });
  assert.equal(proposal.event.title, 'Coffee with Raj');
});

// ---------------------------------------------------------------------------------------------------------
// MockCalendar: free/busy
// ---------------------------------------------------------------------------------------------------------

test('freebusy returns merged busy blocks and nothing that identifies an event', async () => {
  const { calendar } = mockAt();
  const result = await calendar.freebusy(AVA, '2026-11-09T00:00:00-07:00', '2026-11-10T00:00:00-07:00');
  assert.deepEqual(Object.keys(result).sort(), ['busy', 'end', 'persona_id', 'start']);
  assert.equal(result.start, '2026-11-09T07:00:00Z');
  assert.equal(result.end, '2026-11-10T07:00:00Z');
  assert.deepEqual(result.busy, [
    { starts_at: '2026-11-09T16:00:00Z', ends_at: '2026-11-09T17:00:00Z' },
    { starts_at: '2026-11-09T20:30:00Z', ends_at: '2026-11-09T21:00:00Z' },
    { starts_at: '2026-11-09T22:30:00Z', ends_at: '2026-11-09T23:30:00Z' },
    { starts_at: '2026-11-10T01:30:00Z', ends_at: '2026-11-10T03:00:00Z' },
  ]);
  for (const block of result.busy) assert.deepEqual(Object.keys(block).sort(), ['ends_at', 'starts_at']);
  const text = JSON.stringify(result);
  for (const secret of ['Opening', 'keynote', 'Partner dinner', 'Room', 'evt-', 'Lobby']) {
    assert.ok(!text.includes(secret), secret);
  }
});

test('freebusy clips to the window, ignores declined events and validates its arguments', async () => {
  const { calendar } = mockAt();
  const clipped = await calendar.freebusy(AVA, '2026-11-09T16:30:00Z', '2026-11-09T20:45:00Z');
  assert.deepEqual(clipped.busy, [
    { starts_at: '2026-11-09T16:30:00Z', ends_at: '2026-11-09T17:00:00Z' },
    { starts_at: '2026-11-09T20:30:00Z', ends_at: '2026-11-09T20:45:00Z' },
  ]);
  await rejectsWith(calendar.freebusy(AVA, '2026-11-09T00:00:00', '2026-11-10T00:00:00Z'), 422);
  await rejectsWith(calendar.freebusy(AVA, '2026-11-10T00:00:00Z', '2026-11-09T00:00:00Z'), 422);
  await rejectsWith(calendar.freebusy(AVA, '2026-11-01T00:00:00Z', '2026-11-16T00:00:01Z'), 422);
  await rejectsWith(calendar.freebusy('nobody.here', '2026-11-09T00:00:00Z', '2026-11-10T00:00:00Z'), 404);
});

// ---------------------------------------------------------------------------------------------------------
// MockCalendar: replica sync between the two phones
// ---------------------------------------------------------------------------------------------------------

/** What a phone broadcast after the replicas finished their hello handshake. */
const mutations = (bus) => bus.emitted.filter((m) => m.type === 'calendar:sync' && !m.data.snapshot);

test('a mutation broadcasts calendar:sync with the changed copies', async () => {
  const { a, ava } = phones();
  const { event } = await ava.create(personal());
  const sent = mutations(a);
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0].data.events.map((e) => e.event_id), [event.event_id]);
  assert.deepEqual(sent[0].data.removed, []);
  await ava.remove(event.event_id, AVA);
  assert.deepEqual(mutations(a)[1].data.removed, [event.event_id]);
  await ava.setConferenceMode({ persona_id: AVA, enabled: false });
  assert.deepEqual(mutations(a)[2].data.conference_mode, { [AVA]: false });
  assert.equal(a.local.length, 0, 'the sender does not announce its own broadcast: announcing() does that');
});

test('the other phone applies the changes and announces calendar:changed', async () => {
  const { b, ava, bo } = phones();
  const { event } = await ava.create(personal());
  assert.deepEqual(b.local, [{ type: 'calendar:changed', data: { persona_ids: [AVA] } }]);
  const replicated = (await bo.view(AVA)).events.find((e) => e.event_id === event.event_id);
  assert.equal(replicated.title, 'Dentist');

  await ava.remove(event.event_id, AVA);
  assert.ok(!(await bo.view(AVA)).events.some((e) => e.event_id === event.event_id));

  await ava.setConferenceMode({ persona_id: AVA, enabled: false });
  assert.equal((await bo.view(AVA)).conference_mode, false);
  assert.equal(b.local.length, 3);
});

test('a meeting accepted on both phones is confirmed on both replicas', async () => {
  const { a, b, ava, bo } = phones();
  await ava.respond('evt-ava-bo', { persona_id: AVA, response: 'accept' });
  assert.equal((await bo.view(BO)).events.find((e) => e.event_id === 'evt-bo-ava').responses[AVA], 'accepted');
  assert.deepEqual(b.local.at(-1).data.persona_ids.sort(), [AVA, BO]);
  await bo.respond('evt-bo-ava', { persona_id: BO, response: 'accept' });
  for (const calendar of [ava, bo]) {
    const avaCopy = (await calendar.view(AVA)).events.find((e) => e.event_id === 'evt-ava-bo');
    const boCopy = (await calendar.view(BO)).events.find((e) => e.event_id === 'evt-bo-ava');
    assert.equal(avaCopy.status, 'confirmed');
    assert.equal(boCopy.status, 'confirmed');
  }
  assert.deepEqual(a.local.at(-1).data.persona_ids.sort(), [AVA, BO]);
});

test('a proposal made on one phone appears in the invitee replica on the other', async () => {
  const { ava, bo } = phones();
  const proposal = await ava.propose({ persona_id: AVA, with_persona_id: BO, not_before: '2026-11-12T09:00:00-07:00' });
  assert.equal(proposal.created, false, 'Ava and Bo already have a seeded coffee');
  const sam = await ava.propose({ persona_id: AVA, with_persona_id: SAM });
  const onBo = (await bo.view(SAM)).events.find((e) => e.meeting_id === sam.meeting_id);
  assert.equal(onBo.title, 'Coffee with Ava');
});

test('a replica built after the other phone has changed asks for and adopts its state', async () => {
  const a = fakeBus(AVA);
  const b = fakeBus(BO);
  a.peers.push(b);
  b.peers.push(a);
  const clock = () => new Date(MONDAY_MORNING);
  const ava = new MockCalendar({ bus: a, self: AVA, now: clock }); // Bo's phone has no replica yet
  await ava.respond('evt-ava-bo', { persona_id: AVA, response: 'accept' });
  await ava.create(personal());
  await ava.setConferenceMode({ persona_id: AVA, enabled: false });

  const bo = new MockCalendar({ bus: b, self: BO, now: clock }); // Bo opens Calendar later
  assert.equal(b.emitted[0].type, 'calendar:hello');
  const copy = (await bo.view(BO)).events.find((e) => e.event_id === 'evt-bo-ava');
  assert.equal(copy.responses[AVA], 'accepted', "Ava's answer survives");
  assert.ok((await bo.view(AVA)).events.some((e) => e.title === 'Dentist'));
  assert.equal((await bo.view(AVA)).conference_mode, false);
  assert.ok(b.local.some((m) => m.data.persona_ids.includes(AVA)), 'screens are told to refetch');

  await bo.respond('evt-bo-ava', { persona_id: BO, response: 'accept' });
  for (const calendar of [ava, bo]) {
    assert.equal((await calendar.view(AVA)).events.find((e) => e.event_id === 'evt-ava-bo').status, 'confirmed');
    assert.equal((await calendar.view(BO)).events.find((e) => e.event_id === 'evt-bo-ava').status, 'confirmed');
  }
});

test('a late replica that already changed something keeps its own change when the snapshot arrives', async () => {
  const { bus, calendar } = mockAt(MONDAY_MORNING, BO);
  const { event } = await calendar.create(personal({ persona_id: BO, title: 'Mine' }));
  const theirs = expandSeed().events.find((e) => e.event_id === 'evt-ava-keynote');
  bus.deliver('calendar:sync', { snapshot: true, events: [{ ...theirs, title: 'Theirs' }], removed: [], conference_mode: {} }, AVA);
  const view = await calendar.view(BO);
  assert.ok(view.events.some((e) => e.event_id === event.event_id), 'not replaced wholesale');
  assert.equal((await calendar.view(AVA)).events[0].title, 'Theirs');
});

test('two phones answering at the same moment both keep their answer', async () => {
  const { bus, calendar } = mockAt(MONDAY_MORNING, BO);
  const stale = clone(await calendar.view(AVA)).events.find((e) => e.event_id === 'evt-ava-bo');
  await calendar.respond('evt-bo-ava', { persona_id: BO, response: 'accept' });
  // Ava's copy arrives after Bo answered, but it was made before and says Bo is still pending.
  bus.deliver('calendar:sync', {
    events: [{ ...stale, responses: { [AVA]: 'accepted', [BO]: 'pending' } }], removed: [],
  }, AVA);
  const copy = (await calendar.view(AVA)).events.find((e) => e.event_id === 'evt-ava-bo');
  assert.deepEqual(copy.responses, { [AVA]: 'accepted', [BO]: 'accepted' });
  assert.equal(copy.status, 'confirmed');
  const mine = (await calendar.view(BO)).events.find((e) => e.event_id === 'evt-bo-ava');
  assert.equal(mine.status, 'confirmed');
});

test('mergeResponses and meetingStatus: answers beat pending, a decline beats everything', () => {
  assert.deepEqual(mergeResponses({ a: 'pending', b: 'accepted' }, { a: 'accepted', b: 'pending' }), { a: 'accepted', b: 'accepted' });
  assert.deepEqual(mergeResponses({ a: 'accepted' }, { a: 'declined' }), { a: 'declined' });
  const event = { persona_id: 'a', with_persona_ids: ['b'], status: 'proposed' };
  assert.equal(meetingStatus(event, { a: 'accepted', b: 'pending' }), 'proposed');
  assert.equal(meetingStatus(event, { a: 'accepted', b: 'accepted' }), 'confirmed');
  assert.equal(meetingStatus(event, { a: 'accepted', b: 'declined' }), 'declined');
});

test('a replica ignores its own broadcast and malformed messages', async () => {
  const { bus, calendar } = mockAt();
  const before = await calendar.view(AVA);
  const fake = { ...before.events[0], title: 'Injected' };
  bus.deliver('calendar:sync', { events: [fake], removed: [], conference_mode: {} }, AVA);
  assert.equal((await calendar.view(AVA)).events[0].title, 'Opening keynotes');
  assert.deepEqual(bus.local, []);

  bus.deliver('calendar:sync', { events: [{ event_id: 'evt-x' }, null, 'junk'], removed: ['missing'], conference_mode: { 'nobody.here': true, [BO]: 'yes' } }, BO);
  assert.deepEqual(bus.local, [], 'nothing valid, nothing announced');
  assert.equal((await calendar.view(AVA)).events.length, before.events.length);

  bus.deliver('calendar:sync', { events: [fake], removed: [], conference_mode: {} }, BO);
  assert.equal((await calendar.view(AVA)).events[0].title, 'Injected');
  assert.deepEqual(bus.local, [{ type: 'calendar:changed', data: { persona_ids: [AVA] } }]);
});

test('dispose stops the replica listening to the other phone', async () => {
  const { bus, calendar } = mockAt();
  calendar.dispose();
  const event = { ...(await calendar.view(AVA)).events[0], title: 'Ignored' };
  bus.deliver('calendar:sync', { events: [event], removed: [] }, BO);
  assert.equal((await calendar.view(AVA)).events[0].title, 'Opening keynotes');
});

// ---------------------------------------------------------------------------------------------------------
// liveCalendar: URL, method and body building
// ---------------------------------------------------------------------------------------------------------

function recorder(result = { ok: true }) {
  const calls = [];
  const fetchJson = async (url, options) => {
    calls.push({ url, ...options });
    return result;
  };
  return { calls, client: liveCalendar(fetchJson) };
}

const params = (url) => Object.fromEntries(new URL(url, 'http://phone.test').searchParams);
const pathOf = (url) => new URL(url, 'http://phone.test').pathname;

test('liveCalendar reads send GET with only the given parameters', async () => {
  const { calls, client } = recorder();
  await client.view(AVA);
  assert.equal(calls[0].url, '/api/calendar?persona_id=acme.ava');
  assert.equal(calls[0].method, undefined);
  await client.view(AVA, { start: '2026-11-10', days: 3 });
  assert.deepEqual(params(calls[1].url), { persona_id: AVA, start: '2026-11-10', days: '3' });
  await client.agenda(AVA);
  assert.equal(calls[2].url, '/api/calendar/agenda?persona_id=acme.ava');
  await client.agenda(AVA, 'eBPF tracing');
  assert.equal(pathOf(calls[3].url), '/api/calendar/agenda');
  assert.deepEqual(params(calls[3].url), { persona_id: AVA, q: 'eBPF tracing' });
  await client.freebusy(AVA, '2026-11-09T00:00:00-07:00', '2026-11-10T00:00:00-07:00');
  assert.equal(pathOf(calls[4].url), '/api/calendar/freebusy');
  assert.deepEqual(params(calls[4].url), {
    persona_id: AVA, start: '2026-11-09T00:00:00-07:00', end: '2026-11-10T00:00:00-07:00',
  });
  assert.ok(!calls[4].url.includes('+'), 'the offset sign is percent-encoded when it is a plus');
});

test('liveCalendar writes use the documented method, path and body', async () => {
  const { calls, client } = recorder();
  const body = personal();
  await client.create(body);
  assert.deepEqual(calls[0], { url: '/api/calendar/events', method: 'POST', body });
  await client.update('evt-1', { persona_id: AVA, capture: true });
  assert.deepEqual(calls[1], { url: '/api/calendar/events/evt-1', method: 'PATCH', body: { persona_id: AVA, capture: true } });
  await client.remove('evt-1', AVA);
  assert.deepEqual(calls[2], { url: '/api/calendar/events/evt-1?persona_id=acme.ava', method: 'DELETE' });
  await client.respond('evt-1', { persona_id: AVA, response: 'accept' });
  assert.deepEqual(calls[3], {
    url: '/api/calendar/events/evt-1/respond', method: 'POST', body: { persona_id: AVA, response: 'accept' },
  });
  await client.setConferenceMode({ persona_id: AVA, enabled: true });
  assert.deepEqual(calls[4], {
    url: '/api/calendar/conference-mode', method: 'PUT', body: { persona_id: AVA, enabled: true },
  });
  await client.addTalk({ persona_id: AVA, talk_id: 'talk-x' });
  assert.deepEqual(calls[5], { url: '/api/calendar/talks', method: 'POST', body: { persona_id: AVA, talk_id: 'talk-x' } });
  await client.propose({ persona_id: AVA, with_persona_id: BO });
  assert.deepEqual(calls[6], { url: '/api/calendar/propose', method: 'POST', body: { persona_id: AVA, with_persona_id: BO } });
});

test('liveCalendar encodes event ids and builds the export link', async () => {
  const { calls, client } = recorder();
  await client.update('evt a/b', { persona_id: AVA, capture: false });
  assert.equal(calls[0].url, '/api/calendar/events/evt%20a%2Fb');
  assert.equal(client.exportUrl(AVA), '/api/calendar/export.ics?persona_id=acme.ava');
});

test('liveCalendar passes through the result and the failure of the injected fetch', async () => {
  const { client } = recorder({ events: [] });
  assert.deepEqual(await client.view(AVA), { events: [] });
  const failing = liveCalendar(async () => { throw Object.assign(new Error('boom'), { status: 409 }); });
  await rejectsWith(failing.create(personal()), 409);
});

// ---------------------------------------------------------------------------------------------------------
// announcing / calendarClient / calendarErrorMessage
// ---------------------------------------------------------------------------------------------------------

test('announcing emits calendar:changed after each successful mutation only', async () => {
  const bus = fakeBus(AVA);
  const { client } = recorder({ done: true });
  const wrapped = announcing(client, bus, AVA);
  const mutations = [
    ['create', [personal()]],
    ['update', ['evt-1', { persona_id: AVA, capture: true }]],
    ['remove', ['evt-1', AVA]],
    ['respond', ['evt-1', { persona_id: AVA, response: 'accept' }]],
    ['setConferenceMode', [{ persona_id: AVA, enabled: true }]],
    ['addTalk', [{ persona_id: AVA, talk_id: 'talk-x' }]],
    ['propose', [{ persona_id: AVA, with_persona_id: BO }]],
  ];
  for (const [name, args] of mutations) {
    const before = bus.local.length;
    assert.deepEqual(await wrapped[name](...args), { done: true }, name);
    assert.equal(bus.local.length, before + 1, name);
    assert.deepEqual(bus.local.at(-1), { type: 'calendar:changed', data: { persona_ids: [AVA] } }, name);
  }
  const count = bus.local.length;
  await wrapped.view(AVA);
  await wrapped.agenda(AVA, 'x');
  await wrapped.freebusy(AVA, 'a', 'b');
  assert.equal(bus.local.length, count, 'reads do not announce');
});

test('announcing stays silent when the call fails', async () => {
  const bus = fakeBus(AVA);
  const failing = liveCalendar(async () => { throw Object.assign(new Error('nope'), { status: 422 }); });
  const wrapped = announcing(failing, bus, AVA);
  await rejectsWith(wrapped.create(personal()), 422);
  assert.deepEqual(bus.local, []);
});

test('calendarClient builds one announcing mock client per phone in mock mode', async () => {
  const bus = fakeBus(AVA);
  const ctx = { mode: 'mock', me: { id: AVA }, bus, store: {} };
  const client = calendarClient(ctx);
  assert.equal(calendarClient(ctx), client, 'cached in ctx.store');
  for (const name of Object.keys(liveCalendar(async () => null))) assert.equal(typeof client[name], 'function', name);
  assert.equal(client.exportUrl(AVA), null);
  const view = await client.view(AVA);
  assert.equal(view.persona_id, AVA);
  await client.update('evt-ava-keynote', { persona_id: AVA, capture: false });
  assert.deepEqual(bus.local.at(-1), { type: 'calendar:changed', data: { persona_ids: [AVA] } });
  assert.equal(mutations(bus).at(-1).type, 'calendar:sync');
});

test('calendarClient uses the live client in live mode', () => {
  const ctx = { mode: 'live', me: { id: AVA }, bus: fakeBus(AVA), store: {} };
  assert.match(calendarClient(ctx).exportUrl(AVA), /^\/api\/calendar\/export\.ics\?/);
});

test('calendarErrorMessage explains each status in plain words', () => {
  assert.equal(calendarErrorMessage({ status: 404 }), 'That event is no longer on your calendar.');
  assert.equal(calendarErrorMessage({ status: 409 }, 'propose'), 'No time works for both of you this week.');
  assert.equal(calendarErrorMessage({ status: 409 }), 'That change is not allowed for this event.');
  assert.equal(calendarErrorMessage({ status: 422 }), 'Check the details and try again.');
  assert.equal(calendarErrorMessage(new Error('x'), 'add the event'), 'Could not add the event. Try again.');
  assert.equal(calendarErrorMessage(null), 'Could not update the calendar. Try again.');
});

// ---------------------------------------------------------------------------------------------------------
// The Calendar screen, on a tiny fake DOM
// ---------------------------------------------------------------------------------------------------------

class FakeNode {
  constructor() { this.childNodes = []; this.parent = null; }

  append(...nodes) {
    for (const n of nodes) {
      const node = n instanceof FakeNode ? n : new FakeText(String(n));
      node.parent?.removeChild(node);
      node.parent = this;
      this.childNodes.push(node);
    }
  }

  removeChild(node) {
    this.childNodes = this.childNodes.filter((c) => c !== node);
    node.parent = null;
  }

  remove() { this.parent?.removeChild(this); }

  replaceChildren(...nodes) {
    for (const c of this.childNodes) c.parent = null;
    this.childNodes = [];
    this.append(...nodes);
  }

  get textContent() { return this.childNodes.map((c) => c.textContent).join(''); }

  set textContent(value) { this.replaceChildren(String(value)); }
}
class FakeText extends FakeNode {
  constructor(data) { super(); this.nodeType = 3; this.data = data; }

  get textContent() { return this.data; }

  set textContent(value) { this.data = String(value); }
}
class FakeElement extends FakeNode {
  constructor(tag, ns) {
    super();
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.namespaceURI = ns || null;
    this.attrs = new Map();
    this.listeners = {};
    this.dataset = {};
    this.style = { setProperty() {} };
  }

  setAttribute(k, v) { this.attrs.set(k, String(v)); }

  removeAttribute(k) { this.attrs.delete(k); }

  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }

  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }

  get hidden() { return this.attrs.has('hidden'); }

  set hidden(on) { if (on) this.attrs.set('hidden', ''); else this.attrs.delete('hidden'); }

  get disabled() { return this.attrs.has('disabled'); }

  set disabled(on) { if (on) this.attrs.set('disabled', ''); else this.attrs.delete('disabled'); }

  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }

  get connected() {
    let node = this;
    while (node.parent) node = node.parent;
    return node === fakeBody;
  }

  contains(node) {
    for (let n = node; n; n = n.parent) if (n === this) return true;
    return false;
  }

  focus() {
    if (this.disabled || !this.connected) return;
    activeElement = this;
  }

  click() { for (const fn of this.listeners.click ?? []) fn({ preventDefault() {} }); }

  matches(token) {
    if (token === '*') return true;
    if (token === '[data-focus-key]') return this.dataset.focusKey !== undefined;
    if (token.startsWith('[')) return this.getAttribute(token.slice(1, -1)) !== null;
    if (token.startsWith('.')) return (this.getAttribute('class') ?? '').split(/\s+/).includes(token.slice(1));
    return this.tagName === token.toUpperCase();
  }

  querySelectorAll(selector) {
    const tokens = selector.split(/\s+/);
    const out = [];
    const walk = (el, chain) => {
      for (const child of el.children) {
        const open = chain < tokens.length - 1 && child.matches(tokens[chain]) ? chain + 1 : chain;
        if (chain === tokens.length - 1 && child.matches(tokens[chain])) out.push(child);
        walk(child, open);
      }
    };
    walk(this, 0);
    return out;
  }
}
const fakeBody = new FakeElement('body');
const fakeOverlay = new FakeElement('div');
fakeBody.append(fakeOverlay);
let activeElement = null;

// The screen tests need a DOM, a window and unref'd timers. They are installed only around the
// "calendar screen" suite and restored afterwards: web/tests/index.js runs every file in one
// process, so leaking them would break the bus and ui tests that run in the same process.
const GLOBAL_KEYS = ['Node', 'window', 'document', 'setTimeout', 'setInterval'];
let savedGlobals = null;
const unref = (real) => (...args) => {
  const timer = real(...args);
  timer.unref?.(); // timers the screen starts (clock, poll, toast) must not keep the process alive
  return timer;
};

function installScreenFakes() {
  savedGlobals = GLOBAL_KEYS.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]);
  globalThis.Node = FakeNode;
  globalThis.window = { addEventListener() {}, removeEventListener() {} };
  globalThis.document = {
    body: fakeBody,
    createElement: (tag) => new FakeElement(tag),
    createElementNS: (ns, tag) => new FakeElement(tag, ns),
    createTextNode: (data) => new FakeText(data),
    getElementById: (id) => (id === 'overlay' ? fakeOverlay : null),
    get activeElement() { return activeElement?.connected ? activeElement : fakeBody; },
  };
  globalThis.setTimeout = unref(savedGlobals[3][1].value);
  globalThis.setInterval = unref(savedGlobals[4][1].value);
}

function restoreScreenFakes() {
  for (const [key, descriptor] of savedGlobals || []) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else delete globalThis[key];
  }
  savedGlobals = null;
}

let screen;

const cleanFocus = () => { activeElement = null; };
const byFocusKey = (root, key) => root.querySelectorAll('[data-focus-key]').find((el) => el.dataset.focusKey === key);
const tick = () => new Promise((resolve) => setImmediate(resolve));

/** A phone context wired to one replica; `now` drives the replica clock and so the screen's server clock. */
function screenCtx({ self = AVA, now = MONDAY_MORNING, day = null, wrap = (c) => c } = {}) {
  const handlers = new Map();
  const bus = {
    on(type, fn) {
      if (!handlers.has(type)) handlers.set(type, new Set());
      handlers.get(type).add(fn);
      return () => handlers.get(type).delete(fn);
    },
    emit() {},
    emitLocal(type, data) { for (const fn of handlers.get(type) ?? []) fn(data, { type, data, from: self }); },
  };
  const mock = new MockCalendar({ bus, self, now: () => new Date(now) });
  const cleanups = [];
  const ctx = {
    mode: 'mock',
    me: { id: self },
    peer: { id: BO },
    bus,
    store: { calendar: { day }, calendarClient: announcing(wrap(mock), bus, self) },
    view: {},
    onCleanup: (fn) => cleanups.push(fn),
  };
  return { ctx, bus, mock, cleanups, stop: () => cleanups.splice(0).forEach((fn) => fn()) };
}

function mountScreen(ctx) {
  const root = screen.render(ctx);
  fakeBody.append(root);
  return root;
}

describe('calendar screen', () => {
  let stopFlow = null;
  before(async () => {
    installScreenFakes();
    screen = await import('../app/screens/calendar.js');
    // Toasts go to the overlay of the app's flow (module state in flow.js). Own it here, as main.js
    // does at start-up, so toasts land in this suite's overlay even after other test files ran initFlow.
    const { initFlow } = await import('../app/flow.js');
    const { person } = await import('../app/data.js');
    const quietBus = { on: () => () => {}, emit() {}, emitLocal() {} };
    stopFlow = initFlow({
      me: person(AVA), peer: person('bluefin.bo'), store: {}, mode: 'mock', go() {}, bus: quietBus, overlay: fakeOverlay,
    });
  });
  after(() => {
    stopFlow?.();
    restoreScreenFakes();
  });

  test('phaseOf puts an event before, during or after now', () => {
    const event = { starts_at: '2026-11-09T16:00:00Z', ends_at: '2026-11-09T17:00:00Z' };
    assert.equal(screen.phaseOf(event, Date.parse('2026-11-09T15:00:00Z')), 'later');
    assert.equal(screen.phaseOf(event, Date.parse('2026-11-09T16:00:00Z')), 'now');
    assert.equal(screen.phaseOf(event, Date.parse('2026-11-09T16:59:59Z')), 'now');
    assert.equal(screen.phaseOf(event, Date.parse('2026-11-09T17:00:00Z')), 'earlier');
  });

  test('defaultDay is today inside the view and the first day otherwise', () => {
    const keys = ['2026-11-09', '2026-11-10', '2026-11-11'];
    assert.equal(screen.defaultDay(keys, keys[0], Date.parse('2026-11-10T20:00:00Z')), '2026-11-10');
    assert.equal(screen.defaultDay(keys, keys[0], Date.parse('2026-12-01T20:00:00Z')), '2026-11-09');
    // 02:00 UTC on the 10th is still the 9th in Denver
    assert.equal(screen.defaultDay(keys, keys[0], Date.parse('2026-11-10T02:00:00Z')), '2026-11-09');
  });

  test("Home's add link opens the sheet prefilled with the person, and nothing else does", () => {
    const personOf = (id) => (id === 'lumenly.priya' ? { id, name: 'Priya' } : null);
    assert.deepEqual(screen.addLinkPrefill({ add: '1', with: 'lumenly.priya' }, personOf), { title: 'Coffee with Priya' });
    assert.deepEqual(screen.addLinkPrefill({ add: '1', with: 'nobody.here' }, personOf), { title: '' });
    assert.deepEqual(screen.addLinkPrefill({ add: '1' }, personOf), { title: '' });
    assert.equal(screen.addLinkPrefill({}, personOf), null);
    assert.equal(screen.addLinkPrefill({ add: '0', with: 'lumenly.priya' }, personOf), null);
  });

  test('defaultStart rounds up to the next quarter hour today and is 09:00 on other days', () => {
    const now = Date.parse(MONDAY_MORNING); // 08:07 in Denver
    assert.equal(screen.defaultStart('2026-11-09', now), '08:15');
    assert.equal(screen.defaultStart('2026-11-10', now), '09:00');
    assert.equal(screen.defaultStart('2026-11-09', Date.parse('2026-11-10T06:55:00Z')), '09:00', 'too late in the day');
  });

  test('validateAddForm reports the first problem with its field, or the UTC window', () => {
    const week = { weekStart: Date.parse('2026-11-09T07:00:00Z'), weekEnd: Date.parse('2026-11-16T07:00:00Z') };
    const ok = { title: ' Dentist ', day: '2026-11-12', start: '09:00', minutes: '60', ...week };
    assert.deepEqual(screen.validateAddForm(ok), { starts: Date.parse('2026-11-12T16:00:00Z'), ends: Date.parse('2026-11-12T17:00:00Z') });
    assert.equal(screen.validateAddForm({ ...ok, title: '   ' }).field, 'title');
    assert.equal(screen.validateAddForm({ ...ok, start: '' }).field, 'start');
    assert.match(screen.validateAddForm({ ...ok, day: '2026-11-15', start: '23:30', minutes: '60' }).message, /fit inside this week/);
    assert.match(screen.validateAddForm({ ...ok, day: '2026-11-08' }).message, /fit inside this week/);
  });

  test('focusFallbacks fall from Accept to Decline to the day chip', () => {
    assert.deepEqual(screen.focusFallbacks('evt-1:accept', '2026-11-11'), ['evt-1:accept', 'evt-1:decline', 'day:2026-11-11']);
    assert.deepEqual(screen.focusFallbacks('evt-1:decline', '2026-11-11'), ['evt-1:decline', 'day:2026-11-11']);
  });

  test('the screen loads, selects today and renders the capture switches', async () => {
    cleanFocus();
    const { ctx, stop } = screenCtx();
    const root = mountScreen(ctx);
    await tick();
    assert.equal(byFocusKey(root, 'day:2026-11-09').getAttribute('aria-pressed'), 'true');
    assert.equal(byFocusKey(root, 'day:2026-11-10').getAttribute('aria-pressed'), 'false');
    assert.equal(ctx.store.calendar.day, '2026-11-09');
    assert.ok(byFocusKey(root, 'evt-ava-otel:capture'), 'a later talk has its Auto-transcribe switch');
    const agenda = root.querySelectorAll('.calendar-agenda')[0];
    assert.equal(agenda.getAttribute('aria-live'), null, 'the re-rendered agenda is not a live region');
    assert.ok(root.querySelectorAll('.event-note').every((el) => el.getAttribute('aria-live') === null));
    assert.equal(root.querySelectorAll('[role]').filter((el) => el.getAttribute('role') === 'status' && el.getAttribute('class') === 'visually-hidden').length, 1);
    stop();
  });

  test('a scheduled row shows the event note, such as who the agents said you are going with', async () => {
    cleanFocus();
    const note = 'Going with Bo · suggested by your agents';
    const withNote = (view) => ({
      ...view, events: view.events.map((e) => (e.event_id === 'evt-ava-otel' ? { ...e, note } : e)),
    });
    const { ctx, stop } = screenCtx({
      wrap: (mock) => ({ ...mock, view: async (...args) => withNote(await mock.view(...args)) }),
    });
    const root = mountScreen(ctx);
    await tick();
    const notes = root.querySelectorAll('.event-note').map((el) => el.textContent);
    assert.ok(notes.some((text) => text.includes('Room B') && text.endsWith(note)), notes.join(' | '));
    stop();
  });

  test('a capture switch flips at once and reverts with a toast when the call fails', async () => {
    cleanFocus();
    const { ctx, stop } = screenCtx({
      wrap: (mock) => Object.assign(Object.create(null), { ...mock, update: async () => { throw new CalendarFail(); } }),
    });
    const root = mountScreen(ctx);
    await tick();
    const key = 'evt-ava-otel:capture';
    assert.equal(byFocusKey(root, key).getAttribute('aria-checked'), 'true');
    byFocusKey(root, key).click();
    assert.equal(byFocusKey(root, key).getAttribute('aria-checked'), 'false', 'optimistic');
    await tick();
    assert.equal(byFocusKey(root, key).getAttribute('aria-checked'), 'true', 'reverted');
    assert.match(fakeOverlay.textContent, /Could not change auto-transcribe/);
    const status = root.querySelectorAll('[role]').find((el) => el.getAttribute('role') === 'status');
    assert.match(status.textContent, /Auto-transcribe on for OpenTelemetry/);
    stop();
  });

  class CalendarFail extends Error {
    constructor() { super('boom'); this.status = 500; }
  }

  test('a response that arrives after the screen unmounted is ignored', async () => {
    cleanFocus();
    let release;
    const gate = new Promise((resolve) => { release = resolve; });
    const { ctx, stop } = screenCtx({
      wrap: (mock) => ({ ...mock, view: async (...args) => { await gate; return mock.view(...args); } }),
    });
    const root = mountScreen(ctx);
    stop(); // the person left before the calendar arrived
    release();
    await tick();
    const data = root.querySelectorAll('.calendar-data')[0];
    assert.equal(data.hidden, true, 'nothing was drawn');
    assert.equal(byFocusKey(root, 'day:2026-11-09'), undefined);
  });

  test('the error card survives a background retry and says the service is missing on a 404', async () => {
    cleanFocus();
    let calls = 0;
    const { ctx, bus, stop } = screenCtx({
      wrap: (mock) => ({
        ...mock,
        view: async () => { calls += 1; throw Object.assign(new Error('missing'), { status: 404 }); },
      }),
    });
    const root = mountScreen(ctx);
    await tick();
    const alert = () => root.querySelectorAll('[role]').find((el) => el.getAttribute('role') === 'alert');
    const first = alert();
    assert.match(first.textContent, /calendar service is not available yet/);
    assert.doesNotMatch(first.textContent, /no longer on your calendar/);
    bus.emitLocal('calendar:changed', { persona_ids: [AVA] }); // what the poll and the bus trigger
    assert.equal(root.querySelectorAll('[role]').filter((el) => el.getAttribute('role') === 'status' && el.textContent.includes('Loading')).length, 0, 'no Loading flash');
    await tick();
    assert.equal(alert(), first, 'the same card (and the focus on Retry) stays');
    assert.equal(calls, 2);
    stop();
  });

  test('after Accept the redraw moves focus to Decline instead of dropping it', async () => {
    cleanFocus();
    const { ctx, stop } = screenCtx({ day: '2026-11-11' });
    const root = mountScreen(ctx);
    await tick();
    const accept = byFocusKey(root, 'evt-ava-bo:accept');
    accept.focus();
    assert.equal(document.activeElement, accept);
    accept.click();
    assert.equal(accept.getAttribute('aria-disabled'), 'true');
    assert.equal(document.activeElement, accept, 'the busy button keeps focus until the redraw');
    await tick();
    await tick();
    assert.equal(document.activeElement.dataset.focusKey, 'evt-ava-bo:decline');
    assert.match(root.textContent, /You accepted/);
    stop();
  });

  test('after Decline the redraw moves focus to the selected day chip', async () => {
    cleanFocus();
    const { ctx, stop } = screenCtx({ day: '2026-11-11' });
    const root = mountScreen(ctx);
    await tick();
    const decline = byFocusKey(root, 'evt-ava-bo:decline');
    decline.focus();
    decline.click();
    await tick();
    await tick();
    assert.equal(document.activeElement.dataset.focusKey, 'day:2026-11-11');
    assert.equal(byFocusKey(root, 'evt-ava-bo:decline'), undefined, 'the declined card is gone');
    stop();
  });
});
