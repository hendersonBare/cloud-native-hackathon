// Route table and hash parsing for the phone app. Pure, so it is unit-tested.

export const ROUTES = ['home', 'profile', 'calendar', 'recap', 'live', 'tag', 'memory', 'person', 'people', 'exchange', 'match', 'find', 'deepdive'];

/** '#/person?id=bluefin.bo' -> { name: 'person', params: { id: 'bluefin.bo' } }; unknown routes fall back to home. */
export function parseHash(hash) {
  const raw = String(hash || '').replace(/^#\/?/, '');
  const [path, query] = raw.split('?');
  const name = ROUTES.includes(path) ? path : 'home';
  return { name, params: Object.fromEntries(new URLSearchParams(query || '')) };
}

/** ('person', { id: 'bluefin.bo' }) -> '#/person?id=bluefin.bo' */
export function hashFor(name, params) {
  const q = params ? `?${new URLSearchParams(params)}` : '';
  return `#/${name}${q}`;
}
