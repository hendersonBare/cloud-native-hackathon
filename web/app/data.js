// Demo cast and per-persona screen content. All people and companies are
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

// Per-persona content for each screen. Screens add their own keys here
// (keep them under the screen's name, e.g. VIEWS[id].calendar).
export const VIEWS = {
  'acme.ava': {
    home: {
      event: 'KubeCon',
      live: { title: 'Hallway conversation', elapsedSec: 252 },
      opportunities: [
        { id: 'kestrel.mia', topics: ['Low-overhead tracing at the edge', 'eBPF on small clusters', 'Robots that run Kubernetes'] },
        { id: 'bluefin.bo', topics: ['Tracing with no code changes', 'Cutting observability costs', 'A hospital platform migration'] },
        { id: 'harborline.lena', topics: ['Cutting incident time', 'Rolling out OpenTelemetry', 'Compliance for telemetry data'] },
      ],
      peerBanner: { body: 'Comparing notes on eBPF tracing · tap to watch' },
      agreed: { with: 'lumenly.priya', title: 'Priya · agents agreed', body: 'eBPF overhead numbers · Coffee Tue 3:00 PM' },
      upNext: [
        { time: '3:30 PM', title: 'Zero-code tracing with eBPF', status: 'Transcribing' },
        { time: '6:30 PM', title: 'Partner dinner', status: 'Capture off' },
      ],
    },
  },
  'bluefin.bo': {
    home: {
      event: 'KubeCon',
      live: { title: 'Platform track Q&A', elapsedSec: 98 },
      opportunities: [
        { id: 'tidewater.sofia', topics: ['A 30% smaller cloud bill', 'FinOps for Kubernetes', 'Right-sizing clusters'] },
        { id: 'acme.ava', topics: ['Zero-code eBPF tracing', 'A hospital rollout: 40% faster incidents', 'OpenTelemetry on Kubernetes'] },
        { id: 'lumenly.priya', topics: ['Cloud spend without blind spots', 'eBPF without the overhead', 'Running a small platform team'] },
      ],
      peerBanner: { body: 'Comparing notes on tracing costs · tap to watch' },
      agreed: { with: 'tidewater.sofia', title: 'Sofia · agents agreed', body: 'FinOps dashboards · Coffee Tue 10:00 AM' },
      upNext: [
        { time: '3:30 PM', title: 'Zero-code tracing with eBPF', status: 'Transcribing' },
        { time: '5:00 PM', title: 'Platform team sync', status: 'Capture off' },
      ],
    },
  },
};
