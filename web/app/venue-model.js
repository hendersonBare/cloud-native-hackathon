// Venue geometry: GPS to floor-plan metres, which room a point is in, and the walking route
// between two people. Pure (no DOM), so it is unit-tested and shared by the find screen and the
// mock (venue-mock.js). The backend (src/rapport_venue/geometry.py) implements the same rules and
// its tests pin the same numbers.
//
// Coordinates are metres on the floor plan: origin at the south-west corner, x east, y north.
// Routes leave a room by its door, walk along the corridor's centre line and enter the other
// room by its door. Rounding uses Math.round (half up), which matches floor(n + 0.5) in Python
// for the non-negative values used here.

const M_PER_DEG = 111320;
const COMPASS = ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west'];

const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));
export const round1 = (n) => Math.round(n * 10) / 10;

/** GPS degrees to floor-plan metres (equirectangular; fine across a building). */
export function geoToVenue(venue, lat, lng) {
  const { lat: lat0, lng: lng0 } = venue.geo;
  return {
    x: (lng - lng0) * M_PER_DEG * Math.cos((lat0 * Math.PI) / 180),
    y: (lat - lat0) * M_PER_DEG,
  };
}

/** Clamp a point into the venue, or null when it is more than outside_margin_m outside it. */
export function placeOnSite(venue, x, y) {
  const m = venue.outside_margin_m;
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  if (x < -m || y < -m || x > venue.width_m + m || y > venue.height_m + m) return null;
  return { x: round1(clamp(x, 0, venue.width_m)), y: round1(clamp(y, 0, venue.height_m)) };
}

export function corridorOf(venue) {
  return venue.rooms.find((r) => r.corridor);
}

/** The room a point is in. Rooms win over the corridor on a shared edge; anything else is the corridor. */
export function roomAt(venue, x, y) {
  const inside = (r) => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h;
  return venue.rooms.find((r) => !r.corridor && inside(r)) || corridorOf(venue);
}

const dist = (p, q) => Math.hypot(q[0] - p[0], q[1] - p[1]);

/** Degrees clockwise from north, 0..359. */
export function bearing(p, q) {
  const deg = (Math.atan2(q[0] - p[0], q[1] - p[1]) * 180) / Math.PI;
  return Math.round((deg + 360) % 360) % 360;
}

export function compass(deg) {
  return COMPASS[Math.round(deg / 45) % 8];
}

/** Waypoints [x, y] from a to b (points with x and y), consecutive duplicates removed. */
export function route(venue, a, b) {
  const ra = roomAt(venue, a.x, a.y);
  const rb = roomAt(venue, b.x, b.y);
  const pts = [[a.x, a.y]];
  if (ra.id !== rb.id) {
    const cy = venue.corridor_y;
    if (ra.corridor) pts.push([a.x, cy]);
    else pts.push(ra.door, [ra.door[0], cy]);
    if (rb.corridor) pts.push([b.x, cy]);
    else pts.push([rb.door[0], cy], rb.door);
  }
  pts.push([b.x, b.y]);
  return pts.filter((p, i) => i === 0 || dist(pts[i - 1], p) > 0.01).map(([x, y]) => [x, y]);
}

/**
 * Turn-by-turn legs, as data (the screen words them):
 * same_room | leave {room_id} -> walk {direction east|west, metres} -> enter {room_id}, then arrive {metres, compass}.
 */
export function legs(venue, a, b, pts = route(venue, a, b)) {
  const ra = roomAt(venue, a.x, a.y);
  const rb = roomAt(venue, b.x, b.y);
  const out = [];
  if (ra.id === rb.id) {
    out.push({ kind: 'same_room', room_id: ra.id });
  } else {
    if (!ra.corridor) out.push({ kind: 'leave', room_id: ra.id });
    const startX = ra.corridor ? a.x : ra.door[0];
    const endX = rb.corridor ? b.x : rb.door[0];
    const dx = endX - startX;
    if (Math.abs(dx) >= 1) {
      out.push({ kind: 'walk', room_id: corridorOf(venue).id, direction: dx > 0 ? 'east' : 'west', meters: Math.round(Math.abs(dx)) });
    }
    if (!rb.corridor) out.push({ kind: 'enter', room_id: rb.id });
  }
  const last = pts.length > 1 ? pts[pts.length - 2] : pts[0];
  const end = pts[pts.length - 1];
  out.push({ kind: 'arrive', meters: Math.round(dist(last, end)), compass: compass(bearing(last, end)) });
  return out;
}

/** Everything the map needs between two placed points. */
export function directions(venue, a, b) {
  const pts = route(venue, a, b);
  let length = 0;
  for (let i = 1; i < pts.length; i += 1) length += dist(pts[i - 1], pts[i]);
  const deg = bearing([a.x, a.y], [b.x, b.y]);
  return {
    route: pts,
    distance_m: Math.round(length),
    bearing_deg: deg,
    compass: compass(deg),
    legs: legs(venue, a, b, pts),
  };
}

/** The venue fields a client may see: no check-in spots, no sharing flags, no GPS anchor. */
export function publicVenue(venue) {
  const { id, name, width_m: widthM, height_m: heightM, corridor_y: corridorY, rooms } = venue;
  return {
    id, name, width_m: widthM, height_m: heightM, corridor_y: corridorY,
    rooms: rooms.map((r) => ({ id: r.id, name: r.name, x: r.x, y: r.y, w: r.w, h: r.h, door: r.door, corridor: !!r.corridor })),
  };
}
