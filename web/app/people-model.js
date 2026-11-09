// People directory model: pure helpers (no DOM, no network) used by the People screen.
// A "person" has the data.js person() shape plus { agent, interests }:
//   { id, name, initials, tone, org, title, lang, orgName, role, agent, interests }
// All names here are fictional; counterparty text is only ever rendered with textContent.

import { zoneLabel } from './time.js';

/** Companies that run Rapport agents in the demo (mock mode has no gateway to ask). */
export const AGENT_ORGS = Object.freeze(['acme', 'bluefin']);

const TONES = ['gold', 'steel', 'sage', 'lilac'];
const MAX_SUGGESTIONS = 3;
const MET_STATUSES = ['talking', 'done'];

/** 'Ava Chen' -> 'AC', 'Ava' -> 'A', '' -> '?'. */
export function initialsOf(name) {
  const words = String(name ?? '').trim().split(/\s+/).filter(Boolean);
  if (!words.length) return '?';
  const letters = words.length === 1 ? [words[0]] : [words[0], words[words.length - 1]];
  return letters.map((word) => Array.from(word)[0].toUpperCase()).join('');
}

/** A stable avatar tone for an id: the same id always gets the same colour family. */
export function toneFor(id) {
  let hash = 0;
  for (const char of String(id ?? '')) hash = (hash * 31 + char.codePointAt(0)) >>> 0;
  return TONES[hash % TONES.length];
}

function build({ id, name, initials, tone, org, title, lang, orgName, agent, interests }) {
  return {
    id,
    name,
    initials: initials || initialsOf(name),
    tone: tone || toneFor(id),
    org,
    title: title || '',
    lang: lang === 'es' ? 'es' : 'en',
    orgName: orgName || '',
    role: [title, orgName].filter(Boolean).join(' · '),
    agent: !!agent,
    interests: Array.isArray(interests) ? interests.filter((item) => typeof item === 'string') : [],
  };
}

/**
 * The mock-mode directory from data.js PEOPLE and ORGS.
 * `extra.interests` ({ [personaId]: string[] }) adds topics where the demo data has them.
 */
export function directoryFromLocal(people, orgs, extra = {}) {
  return Object.values(people || {}).map((p) => {
    const org = orgs?.[p.org];
    return build({
      ...p,
      orgName: org?.name || '',
      agent: AGENT_ORGS.includes(p.org),
      interests: p.interests || extra.interests?.[p.id] || [],
    });
  });
}

/**
 * The live directory from GET /api/personas ({ orgs: [Org], personas: [Persona] }).
 * `known` ({ [personaId]: { tone, initials } }) keeps avatars identical to the local demo cast.
 */
export function directoryFromGateway({ orgs, personas, known = {} } = {}) {
  const byId = new Map((orgs || []).map((org) => [org.org_id, org]));
  return (personas || []).map((p) => {
    const org = byId.get(p.org_id);
    return build({
      id: p.persona_id,
      name: p.name,
      initials: known[p.persona_id]?.initials,
      tone: known[p.persona_id]?.tone,
      org: p.org_id,
      title: p.title,
      lang: p.language,
      orgName: org?.name || '',
      agent: !!org?.agents_enabled,
      interests: p.interests,
    });
  });
}

// A clock time (2:30 PM, 9am) that is not already followed by a zone label such as MST.
// (?!\.) stops the optional trailing period from backtracking: without it, '10:00 a.m. MST'
// matched as '10:00 a.m' and came out as '10:00 a.m MST. MST'.
const BARE_TIME = /\b(\d{1,2}(?::\d{2})?\s?[AaPp]\.?[Mm]\.?)(?!\.)(?!\s?(?:[A-Z]{2,4}|[A-Z][a-z]+ Time)\b)/g;

/**
 * Agent-written text sometimes names a talk time without its zone. Append the conference
 * zone label (for the date `ref`) after each bare clock time so no time is shown without one.
 */
export function withZone(text, ref) {
  const value = String(text ?? '');
  if (!BARE_TIME.test(value)) return value;
  BARE_TIME.lastIndex = 0;
  let zone;
  try {
    zone = zoneLabel(ref ?? new Date());
  } catch {
    zone = 'MT';
  }
  return value.replace(BARE_TIME, (time) => `${time} ${zone}`);
}

function byIdMap(directory) {
  return new Map((directory || []).map((p) => [p.id, p]));
}

/**
 * Up to three "your agent suggests" entries: { id, score, why, shared, agent, talks }.
 * Prefers a ResearchResult computed for this viewer (best match first); otherwise uses the
 * persona's Home opportunities from views.json (score is null). Unknown ids and the viewer drop out.
 * `view` may be the VIEWS entry ({ home: { opportunities } }) or the home object itself.
 */
export function suggestionsFor(meId, { research, view, directory } = {}) {
  const people = byIdMap(directory);
  const usable = (id) => id !== meId && people.has(id);

  const cards = research && research.persona_id === meId && Array.isArray(research.cards) ? research.cards : [];
  const fromResearch = cards
    .map((card, index) => ({ card, index }))
    .filter(({ card }) => usable(card.persona_id))
    .sort((a, b) => (b.card.match_score ?? 0) - (a.card.match_score ?? 0) || a.index - b.index)
    .map(({ card }) => ({
      id: card.persona_id,
      score: Number.isFinite(card.match_score) ? card.match_score : null,
      why: withZone(card.why_meet || card.headline || '', card.their_talks?.[0]?.starts_at),
      shared: [...(card.shared_interests || [])],
      agent: typeof card.agent_available === 'boolean' ? card.agent_available : people.get(card.persona_id).agent,
      talks: [...(card.their_talks || [])],
    }));
  if (fromResearch.length) return fromResearch.slice(0, MAX_SUGGESTIONS);

  const opportunities = view?.home?.opportunities || view?.opportunities || [];
  return opportunities
    .filter((o) => usable(o.id))
    .map((o) => ({
      id: o.id,
      score: null,
      why: (o.topics || [])[0] || '',
      shared: [...(o.chips || [])],
      agent: people.get(o.id).agent,
      talks: [],
    }))
    .slice(0, MAX_SUGGESTIONS);
}

/**
 * Ids this viewer has met or is meeting: the other party of an encounter that is talking or
 * done, plus everyone in the viewer's non-declined meetings. Order is stable and de-duplicated.
 */
export function metIds(meId, { encounter, events } = {}) {
  const ids = [];
  const add = (id) => {
    if (typeof id === 'string' && id && id !== meId && !ids.includes(id)) ids.push(id);
  };
  if (encounter && MET_STATUSES.includes(encounter.status)) {
    if (encounter.initiator === meId) add(encounter.responder);
    else if (encounter.responder === meId) add(encounter.initiator);
  }
  for (const event of events || []) {
    if (event?.kind !== 'meeting' || event.status === 'declined') continue;
    if (event.persona_id && event.persona_id !== meId) continue;
    for (const id of event.with_persona_ids || []) add(id);
  }
  return ids;
}

function idSet(list) {
  const set = new Set();
  for (const item of list || []) set.add(typeof item === 'string' ? item : item?.id);
  return set;
}

/**
 * Filter by free text (every word must match name, title, company, interests or shared chips)
 * and the three flags. `met` is an array/Set of ids; `suggested` is an array of suggestion
 * objects (or ids). Returns a new array in the original order.
 */
export function filterPeople(people, { query = '', agentOnly = false, metOnly = false, suggestedOnly = false } = {},
  { met = [], suggested = [] } = {}) {
  const metSet = met instanceof Set ? met : idSet(met);
  const suggestedList = Array.isArray(suggested) ? suggested : [...suggested];
  const suggestedSet = idSet(suggestedList);
  const chipsById = new Map();
  for (const s of suggestedList) {
    if (s && typeof s === 'object') chipsById.set(s.id, s.shared || []);
  }
  const words = String(query).toLowerCase().split(/\s+/).filter(Boolean);

  return (people || []).filter((p) => {
    if (agentOnly && !p.agent) return false;
    if (metOnly && !metSet.has(p.id)) return false;
    if (suggestedOnly && !suggestedSet.has(p.id)) return false;
    if (!words.length) return true;
    const haystack = [p.name, p.title, p.orgName, ...(p.interests || []), ...(chipsById.get(p.id) || [])]
      .filter(Boolean).join(' ').toLowerCase();
    return words.every((word) => haystack.includes(word));
  });
}

/** Alphabetical by name (then id); returns a new array. */
export function sortPeople(people) {
  return [...(people || [])].sort((a, b) => a.name.localeCompare(b.name, 'en', { sensitivity: 'base' })
    || a.id.localeCompare(b.id));
}
