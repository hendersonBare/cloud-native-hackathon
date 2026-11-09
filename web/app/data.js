// Demo cast; per-persona Home content is in views.json. All people and companies are
// fictional (see src/rapport_common/data/personas.json). Screens read from
// here in mock mode; live mode overlays gateway data on top.

export const ORGS = {
  acme: { id: 'acme', name: 'Acme Observability', short: 'Acme' },
  bluefin: { id: 'bluefin', name: 'Bluefin Health', short: 'Bluefin' },
  kestrel: { id: 'kestrel', name: 'Kestrel Robotics', short: 'Kestrel' },
  harborline: { id: 'harborline', name: 'Harborline Bank', short: 'Harborline' },
  tidewater: { id: 'tidewater', name: 'Tidewater Logistics', short: 'Tidewater' },
  lumenly: { id: 'lumenly', name: 'Lumenly Energy', short: 'Lumenly' },
};

// tone: avatar colour family (gold | steel | sage | lilac)
export const PEOPLE = {
  'acme.ava': { id: 'acme.ava', name: 'Ava', initials: 'A', tone: 'gold', org: 'acme', title: 'Solutions Engineer', lang: 'en' },
  'acme.sam': { id: 'acme.sam', name: 'Sam', initials: 'S', tone: 'sage', org: 'acme', title: 'Account Executive', lang: 'en' },
  'bluefin.bo': { id: 'bluefin.bo', name: 'Bo', initials: 'B', tone: 'steel', org: 'bluefin', title: 'Platform Lead', lang: 'es' },
  'bluefin.kai': { id: 'bluefin.kai', name: 'Kai', initials: 'K', tone: 'lilac', org: 'bluefin', title: 'Security Architect', lang: 'en' },
  'kestrel.mia': { id: 'kestrel.mia', name: 'Mia', initials: 'M', tone: 'sage', org: 'kestrel', title: 'Platform Engineer', lang: 'en' },
  'harborline.lena': { id: 'harborline.lena', name: 'Lena', initials: 'L', tone: 'lilac', org: 'harborline', title: 'SRE Manager', lang: 'en' },
  'tidewater.sofia': { id: 'tidewater.sofia', name: 'Sofia', initials: 'S', tone: 'sage', org: 'tidewater', title: 'Platform Lead', lang: 'es' },
  'lumenly.priya': { id: 'lumenly.priya', name: 'Priya', initials: 'P', tone: 'lilac', org: 'lumenly', title: 'Head of Infrastructure', lang: 'en' },
};

/** The two demo phones. */
export const DEMO = { left: 'acme.ava', right: 'bluefin.bo' };

export function person(id) {
  const p = PEOPLE[id];
  if (!p) return null;
  const org = ORGS[p.org];
  return { ...p, orgName: org?.name || '', role: `${p.title} · ${org?.name || ''}` };
}

export function peerOf(id) {
  return id === DEMO.right ? DEMO.left : DEMO.right;
}

// Per-persona Home content lives in views.json (data, not code).
export { default as VIEWS } from './views.json' with { type: 'json' };
