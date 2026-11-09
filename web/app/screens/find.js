// Find: walking directions to another person on the venue floor plan (#/find?with=<persona id>).
// The route comes from the venue API (venue-api.js): it starts at this phone's GPS fix when
// location sharing is on and the phone is inside the venue, else at the person's check-in spot.
// The other person shows only if they share their location. GPS fixes are sent at most every
// SEND_MS and only while this screen is open with sharing on; the server keeps floor-plan metres,
// never the raw coordinates.

import { h, avatar, bottomNav, topbar } from '../ui.js';
import { venueClient } from '../venue-api.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const POLL_MS = 5000;
const SEND_MS = 10000;
const MAX_ACCURACY_M = 100; // the venue's max_accuracy_m: weaker fixes are not sent

/** SVG element with attributes and optional text (set as textContent, never parsed). */
function s(tag, attrs = {}, text) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, String(v));
  if (text != null) el.textContent = text;
  return el;
}

function ago(iso, now = Date.now()) {
  const sec = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (sec < 60) return 'just now';
  return `${Math.round(sec / 60)} min ago`;
}

// Every promise is awaited or ends here, so a rejection never goes unhandled. Logs the error name only.
const settle = (p) => p.catch((err) => console.warn('find: request failed', err?.name || 'Error'));

const metres = (n) => `${n} m`; // no line break between the number and the unit

/** One turn-by-turn step in words. */
export function legText(leg, roomName, peerName) {
  switch (leg.kind) {
    case 'same_room': return `You're both in ${roomName(leg.room_id)}`;
    case 'leave': return `Leave ${roomName(leg.room_id)} by its door`;
    case 'walk': return `Walk ${leg.direction} along the ${roomName(leg.room_id)} for ${metres(leg.meters)}`;
    case 'enter': return `Enter ${roomName(leg.room_id)}`;
    case 'arrive': return leg.meters < 3
      ? `${peerName} is right here`
      : `${peerName} is about ${metres(leg.meters)} to the ${leg.compass}`;
    default: return '';
  }
}

const GPS_NOTES = {
  off: 'Off · nobody can find you. Your route starts at your check-in spot.',
  waiting: 'On · finding you…',
  on: null, // filled in with the accuracy
  denied: 'On · location permission is blocked, so your route starts at your check-in spot.',
  unavailable: "On · this device can't get a GPS fix, so your route starts at your check-in spot.",
  weak: 'On · the GPS signal is too weak here, so your route starts at your check-in spot.',
  outside: "On · you're not at the venue right now, so your route starts at your check-in spot.",
};

export function render(ctx) {
  const { me, route, bus } = ctx;
  const peer = ctx.person(route.params.with);

  if (!peer || peer.id === me.id) {
    return h('div', { class: 'screen find' },
      topbar({ back: 'home', backLabel: 'Back to home', title: 'Find someone' }),
      h('main', { class: 'scroll find-main' },
        h('div', { class: 'find-state' },
          h('p', { class: 'empty-title' }, 'Pick someone to find'),
          h('p', { class: 'empty-note' }, 'Open a person from Home and tap the direction button.'))),
      bottomNav('find'));
  }

  const api = venueClient(ctx);
  let alive = true;
  let venue = null;
  let rooms = new Map();
  let sharing = false;
  let gpsState = 'off';
  let accuracy = null;
  let watchId = null;
  let latestFix = null;
  let lastSent = 0;
  let sending = false;
  let sendGen = 0; // bumped when sharing stops, so a send already in flight is ignored when it lands
  let seq = 0;

  const roomName = (id) => rooms.get(id)?.name || 'the venue';

  // ---------------------------------------------------------------- static frame

  const statusEl = h('p', { class: 'find-status' }, 'Locating…');
  const freshEl = h('p', { class: 'find-fresh' });
  const summary = h('section', { class: 'find-summary', 'aria-labelledby': 'find-peer-name' },
    avatar(peer.initials, peer.tone, 44, 15),
    h('div', { class: 'grow stack', style: { gap: '2px' } },
      h('h2', { id: 'find-peer-name', class: 'find-name' }, peer.name),
      statusEl,
      freshEl));

  const mapSlot = h('figure', { class: 'find-map' });
  const legendPeer = h('span', { class: 'legend-item' }, h('span', { class: `legend-dot peer tone-${peer.tone}` }), peer.name);
  const legendRoute = h('span', { class: 'legend-item' }, h('span', { class: 'legend-line' }), 'Route');
  const legend = h('div', { class: 'find-legend', 'aria-hidden': 'true' },
    h('span', { class: 'legend-item' }, h('span', { class: 'legend-dot me' }), 'You'), legendPeer, legendRoute);
  const stepsEl = h('ol', { class: 'find-steps' });
  const stepsCard = h('section', { class: 'find-card', 'aria-labelledby': 'find-steps-h' },
    h('h2', { id: 'find-steps-h', class: 'eyebrow' }, 'Directions'),
    stepsEl);

  const shareTitle = 'find-share-title';
  const shareNote = h('span', { id: 'find-share-note', class: 'find-share-note', 'aria-live': 'polite' });
  const shareSwitch = h('button', {
    type: 'button', class: 'find-share', role: 'switch', 'aria-checked': 'false', disabled: true,
    'aria-labelledby': shareTitle, 'aria-describedby': 'find-share-note', onClick: () => settle(toggleSharing()),
  },
  h('span', { class: 'grow stack', style: { gap: '2px' } },
    h('span', { id: shareTitle, class: 'find-share-title' }, 'Share my location'),
    shareNote),
  h('span', { class: 'share-track', 'aria-hidden': 'true' }, h('span', { class: 'share-knob' })));

  const errorSlot = h('div', { class: 'find-error-slot' });

  const main = h('main', { class: 'scroll find-main', 'aria-busy': 'true' },
    summary, h('div', { class: 'find-map-wrap' }, mapSlot, legend), stepsCard, shareSwitch, errorSlot);

  // ---------------------------------------------------------------- drawing

  function drawShare() {
    shareSwitch.setAttribute('aria-checked', String(sharing));
    shareSwitch.disabled = venue == null;
    const note = gpsState === 'on'
      ? `On · your phone's GPS${accuracy != null ? `, within ${Math.round(accuracy)} m` : ''}`
      : GPS_NOTES[gpsState];
    shareNote.textContent = note;
  }

  function drawMap(dir) {
    const W = venue.width_m;
    const H = venue.height_m;
    const Y = (y) => H - y; // floor plan y points north; SVG y points down
    const peerRoom = dir.to?.room_id;
    const meRoom = dir.from.room_id;
    const label = dir.to
      ? `Floor plan. You are in ${roomName(meRoom)}. ${peer.name} is in ${roomName(peerRoom)}, ${dir.distance_m} metres away.`
      : `Floor plan. You are in ${roomName(meRoom)}. ${peer.name} is not sharing a location.`;

    const map = s('svg', {
      viewBox: `-1 -1 ${W + 2} ${H + 2}`, role: 'img', 'aria-label': label, preserveAspectRatio: 'xMidYMid meet',
    });
    for (const r of venue.rooms) {
      const cls = ['room', r.corridor ? 'corridor' : '', r.id === peerRoom ? 'is-peer' : '', r.id === meRoom ? 'is-me' : '']
        .filter(Boolean).join(' ');
      map.append(s('rect', { class: cls, x: r.x, y: Y(r.y + r.h), width: r.w, height: r.h, rx: 1.2 }));
    }
    for (const r of venue.rooms) {
      if (!r.door) continue;
      map.append(s('line', { class: 'door', x1: r.door[0] - 2.2, y1: Y(r.door[1]), x2: r.door[0] + 2.2, y2: Y(r.door[1]) }));
    }
    // Labels sit on the side away from the corridor, where routes do not run.
    for (const r of venue.rooms) {
      let cy = Y(r.y + r.h) + 4.6;
      if (r.corridor) cy = Y(r.y + r.h) + 3.4; // above the centre line that routes follow
      else if (r.y < venue.corridor_y) cy = Y(r.y) - 2.4;
      map.append(s('text', { class: r.corridor ? 'room-label corridor-label' : 'room-label', x: r.x + r.w / 2, y: cy }, r.name));
    }
    if (dir.route.length > 1) {
      map.append(s('polyline', { class: 'route', points: dir.route.map(([x, y]) => `${x},${Y(y)}`).join(' ') }));
    }
    const fx = dir.from.x;
    const fy = Y(dir.from.y);
    if (dir.from.source === 'gps' && dir.from.accuracy_m) {
      map.append(s('circle', { class: 'accuracy', cx: fx, cy: fy, r: Math.min(dir.from.accuracy_m, 30) }));
    }
    map.append(s('circle', { class: 'me-halo rp-pulse', cx: fx, cy: fy, r: 3.4 }));
    map.append(s('circle', { class: 'me-dot', cx: fx, cy: fy, r: 1.9 }));
    if (dir.to) {
      const tx = dir.to.x;
      const ty = Y(dir.to.y);
      map.append(s('circle', { class: `peer-dot tone-${peer.tone}`, cx: tx, cy: ty, r: 3 }));
      map.append(s('text', { class: 'peer-initial', x: tx, y: ty + 1.05 }, peer.initials));
    }
    mapSlot.replaceChildren(map);
  }

  function draw(dir) {
    main.setAttribute('aria-busy', 'false');
    errorSlot.replaceChildren();
    drawMap(dir);
    legendPeer.hidden = !dir.to;
    legendRoute.hidden = !(dir.route.length > 1);
    if (dir.peer_status !== 'sharing' || !dir.to) {
      statusEl.textContent = "Isn't sharing a location right now";
      freshEl.textContent = '';
      stepsEl.replaceChildren(h('li', { class: 'find-step muted' },
        `When ${peer.name} turns on location sharing, the route shows here.`));
      return;
    }
    statusEl.textContent = `${roomName(dir.to.room_id)} · ${metres(dir.distance_m)} away`;
    freshEl.textContent = dir.to.source === 'gps' && dir.to.updated_at
      ? `Live GPS · updated ${ago(dir.to.updated_at)}`
      : 'Check-in spot · not live';
    stepsEl.replaceChildren(...dir.legs.map((leg) => h('li', { class: `find-step leg-${leg.kind}` },
      legText(leg, roomName, peer.name))));
  }

  function showError() {
    main.setAttribute('aria-busy', 'false');
    errorSlot.replaceChildren(h('div', { class: 'find-state', role: 'alert' },
      h('p', { class: 'empty-title' }, 'Directions did not load'),
      h('p', { class: 'empty-note' }, 'Check your connection and try again.'),
      h('button', { type: 'button', class: 'btn btn-sm find-retry', onClick: () => settle(load()) }, 'Retry')));
  }

  // ---------------------------------------------------------------- data

  async function refresh() {
    if (!venue) return;
    const token = ++seq;
    try {
      const dir = await api.directions(me.id, peer.id);
      if (alive && token === seq) draw(dir);
    } catch {
      if (alive && token === seq) showError();
    }
  }

  async function load() {
    errorSlot.replaceChildren();
    main.setAttribute('aria-busy', 'true');
    try {
      const view = await api.view(me.id);
      if (!alive) return;
      venue = view.venue;
      rooms = new Map(venue.rooms.map((r) => [r.id, r]));
      sharing = view.sharing === true;
      if (sharing) startGps();
      drawShare();
      await refresh();
    } catch {
      if (alive) showError();
    }
  }

  // ---------------------------------------------------------------- GPS

  async function sendFix(force = false) {
    if (!latestFix || sending || !sharing) return;
    if (!force && Date.now() - lastSent < SEND_MS) return;
    sending = true;
    lastSent = Date.now();
    const gen = ++sendGen;
    const fix = latestFix;
    // Only the latest send of a screen that is still open with sharing on may change the note.
    const current = () => alive && sharing && gen === sendGen;
    try {
      await api.updateLocation({ persona_id: me.id, ...fix });
      if (current()) {
        gpsState = 'on';
        accuracy = fix.accuracy_m;
      }
    } catch (error) {
      // 422 is outside the venue (weak fixes are filtered before sending); 409 means sharing went off.
      if (current() && error?.status === 422) gpsState = 'outside';
    } finally {
      sending = false;
    }
    if (!current()) return;
    drawShare();
    await refresh();
  }

  function startGps() {
    if (watchId != null) return;
    const geo = globalThis.navigator?.geolocation;
    if (!geo) { gpsState = 'unavailable'; return; }
    gpsState = 'waiting';
    watchId = geo.watchPosition((pos) => {
      if (!alive || !sharing) return;
      const acc = pos.coords.accuracy;
      if (Number.isFinite(acc) && acc > MAX_ACCURACY_M) {
        gpsState = 'weak';
        drawShare();
        return;
      }
      const first = latestFix == null;
      latestFix = { lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy_m: Number.isFinite(acc) ? acc : null };
      settle(sendFix(first));
    }, (err) => {
      if (!alive) return;
      gpsState = err?.code === 1 ? 'denied' : 'unavailable';
      drawShare();
    }, { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 });
  }

  function stopGps() {
    if (watchId != null) globalThis.navigator?.geolocation?.clearWatch(watchId);
    watchId = null;
    latestFix = null;
    accuracy = null;
    sendGen += 1;
  }

  async function toggleSharing() {
    const next = !sharing;
    shareSwitch.disabled = true;
    try {
      await api.setSharing({ persona_id: me.id, enabled: next });
      if (!alive) return;
      sharing = next;
      if (sharing) startGps();
      else { stopGps(); gpsState = 'off'; }
    } catch {
      // keep the previous state; the switch shows it
    }
    if (!alive) return;
    drawShare();
    await refresh();
  }

  // ---------------------------------------------------------------- lifecycle

  const poll = setInterval(() => { settle(refresh()); settle(sendFix()); }, POLL_MS);
  const offChanged = bus.on('venue:changed', () => settle(refresh()));
  ctx.onCleanup(() => {
    alive = false;
    clearInterval(poll);
    offChanged();
    stopGps();
  });

  drawShare();
  settle(load());

  return h('div', { class: 'screen find' },
    topbar({ back: 'home', backLabel: 'Back to home', title: `Find ${peer.name}` }),
    main,
    bottomNav('find'));
}
