// Venue geometry, the mock venue API and the live client. The numbers below are the same ones the
// backend's tests pin (tests/venue in src/rapport_venue), so both sides route people identically.
import test from 'node:test';
import assert from 'node:assert/strict';
import VENUE from '../mock/venue.json' with { type: 'json' };
import {
  bearing, compass, directions, geoToVenue, placeOnSite, publicVenue, roomAt, round1,
} from '../app/venue-model.js';
import { MockVenue, VenueError } from '../app/venue-mock.js';
import { liveVenue } from '../app/venue-api.js';
import { legText } from '../app/screens/find.js';

const at = (id) => ({ x: VENUE.checkins[id][0], y: VENUE.checkins[id][1] });

test('the floor plan tiles the whole venue and every check-in is inside it', () => {
  for (let x = 0; x <= VENUE.width_m; x += 5) {
    for (let y = 0; y <= VENUE.height_m; y += 5) assert.ok(roomAt(VENUE, x, y), `${x},${y}`);
  }
  for (const [id, [x, y]] of Object.entries(VENUE.checkins)) {
    assert.ok(x >= 0 && x <= VENUE.width_m && y >= 0 && y <= VENUE.height_m, id);
  }
});

test('rooms win over the corridor on a shared edge, in file order', () => {
  assert.equal(roomAt(VENUE, 50, 40).id, 'main-hall');
  assert.equal(roomAt(VENUE, 60, 35).id, 'concourse');
  assert.equal(roomAt(VENUE, 86, 40).id, 'room-b');
});

test('a route between rooms goes door, corridor, door', () => {
  const d = directions(VENUE, at('acme.ava'), at('kestrel.mia'));
  assert.deepEqual(d.route, [[70, 18], [75, 30], [75, 35], [86, 35], [86, 40], [88, 58]]);
  assert.equal(d.distance_m, 52);
  assert.equal(d.bearing_deg, 24);
  assert.equal(d.compass, 'north-east');
  assert.deepEqual(d.legs, [
    { kind: 'leave', room_id: 'lobby-cafe' },
    { kind: 'walk', room_id: 'concourse', direction: 'east', meters: 11 },
    { kind: 'enter', room_id: 'room-b' },
    { kind: 'arrive', meters: 18, compass: 'north' },
  ]);
});

test('people in the same room get a straight line', () => {
  const d = directions(VENUE, at('acme.ava'), at('bluefin.bo'));
  assert.deepEqual(d.route, [[70, 18], [81, 21]]);
  assert.equal(d.distance_m, 11);
  assert.equal(d.bearing_deg, 75);
  assert.deepEqual(d.legs, [{ kind: 'same_room', room_id: 'lobby-cafe' }, { kind: 'arrive', meters: 11, compass: 'east' }]);
});

test('a long route across the venue', () => {
  const d = directions(VENUE, at('acme.sam'), at('lumenly.priya'));
  assert.equal(d.distance_m, 130);
  assert.equal(d.bearing_deg, 62);
  assert.deepEqual(d.legs.map((l) => l.kind), ['leave', 'walk', 'enter', 'arrive']);
  assert.equal(d.legs[1].direction, 'east');
  assert.equal(d.legs[1].meters, 79);
});

test('walking west and starting in the corridor', () => {
  const d = directions(VENUE, { x: 100, y: 36 }, at('harborline.lena'));
  assert.deepEqual(d.route, [[100, 36], [100, 35], [25, 35], [25, 40], [22, 58]]);
  assert.deepEqual(d.legs.slice(0, 2), [
    { kind: 'walk', room_id: 'concourse', direction: 'west', meters: 75 },
    { kind: 'enter', room_id: 'main-hall' },
  ]);
});

test('GPS maps to floor-plan metres, and points far outside are refused', () => {
  const g = geoToVenue(VENUE, 39.7422, -104.9985);
  assert.ok(Math.abs(g.x - 42.7987) < 0.001);
  assert.ok(Math.abs(g.y - 22.264) < 0.001);
  assert.deepEqual(placeOnSite(VENUE, g.x, g.y), { x: 42.8, y: 22.3 });
  assert.deepEqual(placeOnSite(VENUE, -10, 75), { x: 0, y: 70 }); // within the margin: clamped
  assert.equal(placeOnSite(VENUE, -16, 10), null);
  assert.equal(placeOnSite(VENUE, NaN, 10), null);
});

test('rounding is half up and bearings wrap', () => {
  assert.equal(round1(0.25), 0.3);
  assert.equal(bearing([0, 0], [0, 10]), 0);
  assert.equal(bearing([0, 0], [-10, 0]), 270);
  assert.equal(bearing([0, 0], [-0.01, 10]), 0); // 359.94 rounds to 360, which is north
  assert.equal(compass(337), 'north-west');
  assert.equal(compass(338), 'north');
});

test('the public venue leaks no check-ins, sharing flags or GPS anchor', () => {
  const pub = publicVenue(VENUE);
  assert.deepEqual(Object.keys(pub).sort(), ['corridor_y', 'height_m', 'id', 'name', 'rooms', 'width_m']);
  assert.equal(pub.rooms.length, VENUE.rooms.length);
});

// ---------------------------------------------------------------- mock API

function fakeBus() {
  const sent = [];
  const local = [];
  const listeners = new Map();
  return {
    sent, local,
    emit: (type, data) => sent.push({ type, data }),
    emitLocal: (type, data) => local.push({ type, data }),
    on: (type, fn) => { listeners.set(type, fn); return () => listeners.delete(type); },
    deliver: (type, data, from) => listeners.get(type)?.(data, { type, data, from }),
  };
}

// 39.7422, -104.9985 is inside the venue (Expo hall); 40, -105 is far outside.
const INSIDE = { lat: 39.7422, lng: -104.9985, accuracy_m: 12 };

test('directions start at the check-in spot until a GPS fix arrives', async () => {
  const api = new MockVenue({ self: 'acme.ava' });
  const before = await api.directions('acme.ava', 'kestrel.mia');
  assert.equal(before.peer_status, 'sharing');
  assert.equal(before.from.source, 'checkin');
  assert.equal(before.distance_m, 52);

  const fix = await api.updateLocation({ persona_id: 'acme.ava', ...INSIDE });
  assert.deepEqual([fix.source, fix.x, fix.y, fix.room_id, fix.accuracy_m], ['gps', 42.8, 22.3, 'expo-hall', 12]);
  const after = await api.directions('acme.ava', 'kestrel.mia');
  assert.equal(after.from.source, 'gps');
  assert.equal(after.legs[0].room_id, 'expo-hall');
});

test('a GPS fix expires after gps_ttl_s', async () => {
  let now = Date.parse('2026-11-09T21:00:00Z');
  const api = new MockVenue({ clock: () => now });
  await api.updateLocation({ persona_id: 'acme.ava', ...INSIDE });
  now += VENUE.gps_ttl_s * 1000;
  assert.equal((await api.view('acme.ava')).me.source, 'gps');
  now += 1;
  assert.equal((await api.view('acme.ava')).me.source, 'checkin');
});

test('someone not sharing reveals nothing', async () => {
  const api = new MockVenue();
  const d = await api.directions('acme.ava', 'harborline.lena');
  assert.deepEqual(
    { status: d.peer_status, to: d.to, route: d.route, distance: d.distance_m, legs: d.legs },
    { status: 'not_sharing', to: null, route: [], distance: null, legs: [] },
  );
});

test('turning sharing off forgets the GPS fix and refuses new ones', async () => {
  const api = new MockVenue();
  await api.updateLocation({ persona_id: 'acme.ava', ...INSIDE });
  assert.deepEqual(await api.setSharing({ persona_id: 'acme.ava', enabled: false }), { persona_id: 'acme.ava', enabled: false });
  await assert.rejects(api.updateLocation({ persona_id: 'acme.ava', ...INSIDE }), { status: 409, code: 'sharing_off' });
  await api.setSharing({ persona_id: 'acme.ava', enabled: true });
  assert.equal((await api.view('acme.ava')).me.source, 'checkin');
  assert.equal((await api.directions('bluefin.bo', 'acme.ava')).to.source, 'checkin');
});

test('bad requests carry the same codes as the backend', async () => {
  const api = new MockVenue();
  await assert.rejects(api.view('nobody.here'), { status: 404, code: 'unknown_persona' });
  await assert.rejects(api.directions('acme.ava', 'acme.ava'), { status: 422, code: 'same_person' });
  await assert.rejects(api.updateLocation({ persona_id: 'acme.ava', lat: 40, lng: -105 }), { status: 422, code: 'outside_venue' });
  await assert.rejects(api.updateLocation({ persona_id: 'acme.ava', ...INSIDE, accuracy_m: 101 }), { status: 422, code: 'too_inaccurate' });
  await assert.rejects(api.view('nobody.here'), VenueError);
});

test('the view sends the public venue and my own state only', async () => {
  const view = await new MockVenue().view('acme.ava');
  assert.equal(view.sharing, true);
  assert.equal(view.me.room_id, 'lobby-cafe');
  assert.equal('checkins' in view.venue, false);
  assert.equal('geo' in view.venue, false);
});

test('fixes and sharing changes sync to the other phone', async () => {
  const busA = fakeBus();
  const busB = fakeBus();
  const ava = new MockVenue({ bus: busA, self: 'acme.ava' });
  const bo = new MockVenue({ bus: busB, self: 'bluefin.bo' });
  await ava.updateLocation({ persona_id: 'acme.ava', ...INSIDE });
  const msg = busA.sent.at(-1);
  assert.equal(msg.type, 'venue:sync');
  busB.deliver(msg.type, msg.data, 'acme.ava');
  assert.equal((await bo.directions('bluefin.bo', 'acme.ava')).to.source, 'gps');
  assert.deepEqual(busB.local.at(-1), { type: 'venue:changed', data: { persona_id: 'acme.ava' } });

  await ava.setSharing({ persona_id: 'acme.ava', enabled: false });
  const off = busA.sent.at(-1);
  busB.deliver(off.type, off.data, 'acme.ava');
  assert.equal((await bo.directions('bluefin.bo', 'acme.ava')).peer_status, 'not_sharing');

  // A phone ignores its own echo.
  busA.deliver(msg.type, msg.data, 'acme.ava');
  assert.equal((await ava.view('acme.ava')).sharing, false);
});

// ---------------------------------------------------------------- live client and wording

test('the live client calls the venue API paths', async () => {
  const calls = [];
  const api = liveVenue(async (url, opts) => { calls.push([url, opts?.method || 'GET', opts?.body]); return null; });
  await api.view('acme.ava');
  await api.directions('acme.ava', 'kestrel.mia');
  await api.updateLocation({ persona_id: 'acme.ava', ...INSIDE });
  await api.setSharing({ persona_id: 'acme.ava', enabled: false });
  assert.deepEqual(calls, [
    ['/api/venue?persona_id=acme.ava', 'GET', undefined],
    ['/api/venue/directions?persona_id=acme.ava&to=kestrel.mia', 'GET', undefined],
    ['/api/venue/location', 'PUT', { persona_id: 'acme.ava', ...INSIDE, sharing_token: null }],
    ['/api/venue/sharing', 'PUT', { persona_id: 'acme.ava', enabled: false }],
  ]);
});

// A fake venue API with the server's per-device rules, for the live client's token handling.
function tokenServer(seedSharing = false) {
  const calls = [];
  let held = null;
  let sharing = seedSharing;
  let n = 0;
  const fail = (status, detail) => Object.assign(new Error(`failed with status ${status}`), { status, detail });
  const fetchJson = async (url, { method, body } = {}) => {
    calls.push([url, method, body]);
    if (url === '/api/venue/sharing') {
      if (!body.enabled) { sharing = false; held = null; return { persona_id: body.persona_id, enabled: false, sharing_token: null }; }
      if (held && body.sharing_token !== held) throw fail(403, 'shared_from_another_device');
      if (!held) held = `tok-${(n += 1)}-${'x'.repeat(20)}`;
      sharing = true;
      return { persona_id: body.persona_id, enabled: true, sharing_token: held };
    }
    if (url === '/api/venue/location') {
      if (!sharing) throw fail(409, 'sharing_off');
      if (!held || body.sharing_token !== held) throw fail(403, 'not_this_device');
      return { persona_id: body.persona_id, source: 'gps' };
    }
    return null;
  };
  return { calls, fetchJson, token: () => held, reset: () => { held = null; sharing = seedSharing; } };
}

test('live: turning sharing on keeps the token inside the client and sends it with every fix', async () => {
  const srv = tokenServer();
  const api = liveVenue(srv.fetchJson);
  const state = await api.setSharing({ persona_id: 'acme.ava', enabled: true });
  assert.deepEqual(state, { persona_id: 'acme.ava', enabled: true }, 'the screen never sees the token');
  assert.equal((await api.updateLocation({ persona_id: 'acme.ava', ...INSIDE })).source, 'gps');
  assert.equal(srv.calls.at(-1)[2].sharing_token, srv.token());
  await api.setSharing({ persona_id: 'acme.ava', enabled: true });
  assert.equal(srv.calls.at(-1)[2].sharing_token, srv.token(), 'turning it on again proves it is this device');
});

test('live: turning sharing off drops the token; the next fix is refused as sharing_off', async () => {
  const srv = tokenServer();
  const api = liveVenue(srv.fetchJson);
  await api.setSharing({ persona_id: 'acme.ava', enabled: true });
  await api.setSharing({ persona_id: 'acme.ava', enabled: false });
  assert.equal(srv.calls.at(-1)[2].sharing_token, undefined, 'turning off sends no token');
  await assert.rejects(api.updateLocation({ persona_id: 'acme.ava', ...INSIDE }), { status: 409 });
});

test('live: sharing on from the seed is claimed once by the first fix, then sent normally', async () => {
  const srv = tokenServer(true);
  const api = liveVenue(srv.fetchJson);
  assert.equal((await api.updateLocation({ persona_id: 'acme.ava', ...INSIDE })).source, 'gps');
  assert.deepEqual(srv.calls.map(([url]) => url), ['/api/venue/location', '/api/venue/sharing', '/api/venue/location']);
  await api.updateLocation({ persona_id: 'acme.ava', ...INSIDE });
  assert.equal(srv.calls.length, 4, 'no second claim');
});

test('live: reads carry the token as a header, never in the URL, once this device holds one', async () => {
  const srv = tokenServer();
  const reads = [];
  const api = liveVenue(async (url, opts) => {
    if (!opts?.method) reads.push([url, opts?.headers]);
    return srv.fetchJson(url, opts);
  });
  await api.view('acme.ava');
  await api.setSharing({ persona_id: 'acme.ava', enabled: true });
  await api.view('acme.ava');
  await api.directions('acme.ava', 'kestrel.mia');
  assert.deepEqual(reads[0], ['/api/venue?persona_id=acme.ava', undefined]);
  assert.deepEqual(reads[1], ['/api/venue?persona_id=acme.ava', { 'X-Venue-Token': srv.token() }]);
  assert.deepEqual(reads[2], ['/api/venue/directions?persona_id=acme.ava&to=kestrel.mia', { 'X-Venue-Token': srv.token() }]);
  assert.ok(reads.every(([url]) => !url.includes(srv.token())), 'the token never goes in a URL');
});

test('live: another device cannot claim sharing this device holds, and does not keep retrying', async () => {
  const srv = tokenServer();
  const mine = liveVenue(srv.fetchJson);
  await mine.setSharing({ persona_id: 'acme.ava', enabled: true });
  const other = liveVenue(srv.fetchJson);
  const before = srv.calls.length;
  await assert.rejects(other.updateLocation({ persona_id: 'acme.ava', ...INSIDE }), { status: 403 });
  assert.equal(srv.calls.length - before, 2, 'one fix, one claim, no loop');
  await assert.rejects(other.setSharing({ persona_id: 'acme.ava', enabled: true }), { status: 403 });
});

test('live: after the demo reset forgets every token, the next fix claims sharing again and goes through', async () => {
  const srv = tokenServer(true);
  const api = liveVenue(srv.fetchJson);
  await api.updateLocation({ persona_id: 'acme.ava', ...INSIDE });
  const stale = srv.token();
  srv.reset();
  assert.equal((await api.updateLocation({ persona_id: 'acme.ava', ...INSIDE })).source, 'gps');
  assert.notEqual(srv.token(), stale);
  assert.equal(srv.calls.at(-1)[2].sharing_token, srv.token());
});

test('live: if someone else took sharing over, this phone sees the refusal instead of being overridden', async () => {
  const srv = tokenServer();
  const mine = liveVenue(srv.fetchJson);
  await mine.setSharing({ persona_id: 'acme.ava', enabled: true });
  const intruder = liveVenue(srv.fetchJson);
  await intruder.setSharing({ persona_id: 'acme.ava', enabled: false });
  await intruder.setSharing({ persona_id: 'acme.ava', enabled: true });
  await assert.rejects(mine.updateLocation({ persona_id: 'acme.ava', ...INSIDE }), { status: 403 });
});

test('steps read naturally and keep numbers next to their unit', () => {
  const name = (id) => ({ 'lobby-cafe': 'Lobby café', concourse: 'Concourse', 'room-b': 'Room B' }[id]);
  const legs = directions(VENUE, at('acme.ava'), at('kestrel.mia')).legs;
  assert.deepEqual(legs.map((l) => legText(l, name, 'Mia')), [
    'Leave Lobby café by its door',
    'Walk east along the Concourse for 11 m',
    'Enter Room B',
    'Mia is about 18 m to the north',
  ]);
  assert.equal(legText({ kind: 'arrive', meters: 2, compass: 'east' }, name, 'Mia'), 'Mia is right here');
  assert.equal(legText({ kind: 'same_room', room_id: 'lobby-cafe' }, name, 'Mia'), "You're both in Lobby café");
});
