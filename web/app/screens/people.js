// People: the conference directory. Your agent's top suggestions, everyone you have met, and
// everyone else, with search and filters. Mock mode reads the demo cast; live mode reads the
// gateway (personas, and one LLM-backed research call per session) and falls back to the demo
// data with a short note when a call fails. Names, titles and "why" lines come from other
// people's agents, so they are only ever rendered as text.

import { h, icon, avatar, bottomNav, eyebrow, nextId } from '../ui.js';
import { ORGS, PEOPLE } from '../data.js';
import { hashFor } from '../route.js';
import { getPersonas, research as fetchResearch } from '../api.js';
import { calendarClient } from '../calendar-api.js';
import {
  directoryFromGateway, directoryFromLocal, filterPeople, metIds, sortPeople, suggestionsFor,
} from '../people-model.js';
import MOCK_RESEARCH from '../../mock/demo-research.json' with { type: 'json' };

const MAX_PILLS = 4;
const RESEARCH_LIMIT = 12;

const FILTERS = [
  { key: 'suggestedOnly', label: 'Suggested' },
  { key: 'agentOnly', label: 'Has an agent' },
  { key: 'metOnly', label: 'Met' },
];

function interestsFromResearch(research) {
  const map = {};
  for (const card of research?.cards || []) map[card.persona_id] = card.interests || [];
  return map;
}

function personHref(id) {
  return hashFor('person', { id, from: 'people' });
}

function roleLine(p) {
  return p.role || [p.title, p.orgName].filter(Boolean).join(' · ');
}

function plural(n) {
  return `${n} ${n === 1 ? 'person' : 'people'}`;
}

function agentBadge() {
  return h('span', { class: 'people-agent' }, icon('agent', { size: 14, stroke: 1.8 }), 'Agent available');
}

function initialState() {
  return {
    query: '',
    suggestedOnly: false,
    agentOnly: false,
    metOnly: false,
    directory: null,
    directoryFailed: false,
    directoryPromise: null,
    research: null,
    researchState: 'idle', // idle | loading | done | failed
    researchPromise: null,
    events: [],
  };
}

export function render(ctx) {
  const { me, mode } = ctx;
  const st = ctx.store.people || (ctx.store.people = {});
  for (const [key, value] of Object.entries(initialState())) {
    if (!(key in st)) st[key] = value;
  }

  const localDirectory = directoryFromLocal(PEOPLE, ORGS, { interests: interestsFromResearch(MOCK_RESEARCH) });
  if (mode !== 'live' && !st.directory) st.directory = localDirectory;

  let alive = true;
  let metSeq = 0;
  ctx.onCleanup(() => { alive = false; });

  // ---- data -------------------------------------------------------------------------------

  function loadDirectory() {
    if (st.directoryPromise) return st.directoryPromise;
    st.directoryPromise = getPersonas()
      .then((payload) => {
        const known = Object.fromEntries(localDirectory.map((p) => [p.id, { tone: p.tone, initials: p.initials }]));
        const directory = directoryFromGateway({ ...payload, known });
        if (!directory.length) throw new Error('empty directory');
        st.directory = directory;
        st.directoryFailed = false;
      })
      .catch((error) => {
        console.warn('People directory unavailable', error?.status ?? error?.name ?? 'Error');
        st.directory = localDirectory;
        st.directoryFailed = true;
      })
      .finally(() => { st.directoryPromise = null; });
    return st.directoryPromise;
  }

  function loadResearch() {
    if (st.researchPromise) return st.researchPromise;
    st.researchState = 'loading';
    st.researchPromise = fetchResearch({ persona_id: me.id, filters: {}, limit: RESEARCH_LIMIT })
      .then((result) => {
        st.research = result;
        st.researchState = 'done';
      })
      .catch((error) => {
        console.warn('People research unavailable', error?.status ?? error?.name ?? 'Error');
        st.researchState = 'failed';
      })
      .finally(() => { st.researchPromise = null; });
    return st.researchPromise;
  }

  function refreshMet() {
    const seq = ++metSeq;
    calendarClient(ctx).view(me.id)
      .then((view) => {
        if (!alive || seq !== metSeq) return;
        st.events = Array.isArray(view?.events) ? view.events : [];
        drawResults();
      })
      .catch((error) => {
        console.warn('People calendar unavailable', error?.status ?? error?.name ?? 'Error');
      });
  }

  function others() {
    return (st.directory || []).filter((p) => p.id !== me.id);
  }

  function suggestions() {
    const research = mode === 'live' ? st.research : MOCK_RESEARCH;
    return suggestionsFor(me.id, { research, view: ctx.view, directory: others() });
  }

  function metList() {
    return metIds(me.id, { encounter: ctx.store.encounter, events: st.events })
      .filter((id) => others().some((p) => p.id === id));
  }

  // ---- header, search and filters --------------------------------------------------------

  const countLine = h('p', { class: 'people-count muted' });
  const announcer = h('p', { class: 'visually-hidden', role: 'status', 'aria-live': 'polite', 'aria-atomic': 'true' });
  const searchId = nextId('people-search');

  const input = h('input', {
    id: searchId,
    class: 'people-input',
    type: 'search',
    name: 'q',
    placeholder: 'Search by name, company or topic',
    autocomplete: 'off',
    enterkeyhint: 'search',
    maxlength: 80,
    value: st.query,
    onInput: (event) => {
      st.query = event.target.value;
      drawResults();
    },
  });

  function drawChip(chip, key, label) {
    chip.setAttribute('aria-pressed', String(!!st[key]));
    chip.replaceChildren(...[st[key] ? icon('check', { size: 14, stroke: 2.4 }) : null, label].filter(Boolean));
  }

  const chips = FILTERS.map(({ key, label }) => {
    const chip = h('button', {
      type: 'button',
      class: 'toggle-chip',
      onClick: () => {
        st[key] = !st[key];
        drawChip(chip, key, label);
        drawResults();
      },
    });
    chip.dataset.filter = key;
    drawChip(chip, key, label);
    return chip;
  });

  function clearSearch() {
    st.query = '';
    for (const { key } of FILTERS) st[key] = false;
    input.value = '';
    FILTERS.forEach(({ key, label }, index) => drawChip(chips[index], key, label));
    drawResults();
    input.focus({ preventScroll: true });
  }

  // ---- live-mode status and refresh ------------------------------------------------------

  const note = h('p', { class: 'people-note muted', role: 'status', 'aria-live': 'polite' });
  const refreshLabel = h('span');
  const refresh = h('button', {
    type: 'button',
    class: 'link-btn people-refresh',
    onClick: () => {
      if (st.researchPromise || st.directoryPromise) return;
      if (st.directoryFailed) loadDirectory().then(afterLoad);
      loadResearch().then(afterLoad);
      drawMeta();
    },
  }, icon('sparkle', { size: 16, stroke: 1.8 }), refreshLabel);

  function afterLoad() {
    if (alive) drawAll();
  }

  function drawMeta() {
    const loading = !!(st.researchPromise || st.directoryPromise);
    refresh.hidden = mode !== 'live';
    refresh.disabled = loading;
    refreshLabel.textContent = loading ? 'Refreshing…' : 'Refresh suggestions';
    let text = '';
    if (mode === 'live') {
      if (st.directoryFailed) text = 'People could not be loaded, so this is the demo directory.';
      else if (loading) text = 'Your agent is looking for people to meet…';
      else if (st.researchState === 'failed') {
        text = st.research
          ? 'Could not refresh. Showing your last suggestions.'
          : 'Your agent could not refresh suggestions, so these come from your saved opportunities.';
      }
    }
    note.textContent = text;
  }

  // ---- pending connect request -----------------------------------------------------------

  const requestSlot = h('div', { class: 'people-request-slot' });

  function drawRequest() {
    const request = ctx.store.incoming;
    if (!request) {
      requestSlot.replaceChildren();
      return;
    }
    const from = (st.directory || []).find((p) => p.id === request.from) || ctx.person(request.from);
    const name = from?.name || 'Someone';
    requestSlot.replaceChildren(
      h('a', {
        class: 'card-gold people-request',
        href: hashFor('person', { id: request.from, request: request.request_id, from: 'request' }),
        'aria-label': `${name}'s agent wants to connect. Open their brief to accept or decline.`,
      },
      from ? avatar(from.initials, from.tone, 40, 14) : icon('agent', { size: 20 }),
      h('span', { class: 'people-request-text' },
        h('span', { class: 'people-name' }, `${name}'s agent wants to connect`),
        h('span', { class: 'people-role' }, 'See their brief to accept or decline')),
      icon('chevron', { size: 18, stroke: 1.9 })));
  }

  // ---- results ---------------------------------------------------------------------------

  const results = h('div', { class: 'people-results' });

  function suggestionItem(s, p) {
    const parts = [p.name, roleLine(p)];
    if (s.score != null) parts.push(`${s.score}% match`);
    if (s.agent) parts.push('agent available');
    if (s.why) parts.push(s.why);
    return h('li', null,
      h('a', { class: 'card people-card', href: personHref(p.id), 'aria-label': parts.filter(Boolean).join(', ') },
        h('span', { class: 'people-card-top' },
          avatar(p.initials, p.tone, 44, 15),
          h('span', { class: 'people-id' },
            h('span', { class: 'people-name' }, p.name),
            h('span', { class: 'people-role' }, roleLine(p))),
          s.score != null ? h('span', { class: 'people-score tabular' }, `${s.score}% match`) : null),
        s.why ? h('span', { class: 'people-why' }, s.why) : null,
        s.shared.length || s.agent
          ? h('span', { class: 'people-foot' },
            s.shared.slice(0, MAX_PILLS).map((topic) => h('span', { class: 'pill' }, topic)),
            s.agent ? agentBadge() : null)
          : null));
  }

  function rowItem(p) {
    const label = [p.name, roleLine(p), p.agent ? 'agent available' : ''].filter(Boolean).join(', ');
    return h('li', null,
      h('a', { class: 'people-row', href: personHref(p.id), 'aria-label': label },
        avatar(p.initials, p.tone, 44, 15),
        h('span', { class: 'people-id' },
          h('span', { class: 'people-name' }, p.name),
          h('span', { class: 'people-role' }, roleLine(p)),
          p.agent ? agentBadge() : null),
        icon('chevron', { size: 18, stroke: 1.9 })));
  }

  function section(title, items) {
    const id = nextId('people-section');
    return h('section', { class: 'people-section', 'aria-labelledby': id },
      eyebrow(title, { id }),
      h('ul', { class: 'people-list' }, items));
  }

  function emptyState() {
    return h('div', { class: 'people-empty' },
      h('p', { class: 'people-empty-title' }, 'No one matches'),
      h('p', { class: 'muted' }, 'Try a different name, company or topic.'),
      h('button', { type: 'button', class: 'btn btn-sm people-clear', onClick: clearSearch }, 'Clear search'));
  }

  function drawCount() {
    const pool = others();
    const agents = pool.filter((p) => p.agent).length;
    countLine.textContent = st.directory
      ? `${plural(pool.length)} at the conference · ${agents} with an agent`
      : 'Loading the directory…';
  }

  function drawResults() {
    if (!st.directory) {
      results.replaceChildren(h('p', { class: 'people-loading muted' }, 'Loading people…'));
      announcer.textContent = '';
      return;
    }
    const pool = others();
    const suggested = suggestions();
    const met = metList();
    const filtered = sortPeople(filterPeople(pool, {
      query: st.query, agentOnly: st.agentOnly, metOnly: st.metOnly, suggestedOnly: st.suggestedOnly,
    }, { met, suggested }));
    announcer.textContent = plural(filtered.length);

    if (!filtered.length) {
      results.replaceChildren(emptyState());
      return;
    }

    const visible = new Set(filtered.map((p) => p.id));
    const byId = new Map(pool.map((p) => [p.id, p]));
    const suggestedShown = suggested.filter((s) => visible.has(s.id));
    const taken = new Set(suggestedShown.map((s) => s.id));
    const metShown = filtered.filter((p) => met.includes(p.id) && !taken.has(p.id));
    for (const p of metShown) taken.add(p.id);
    const rest = filtered.filter((p) => !taken.has(p.id));

    const sections = [];
    if (suggestedShown.length) {
      sections.push(section('Your agent suggests', suggestedShown.map((s) => suggestionItem(s, byId.get(s.id)))));
    }
    if (metShown.length) sections.push(section('Met at KubeCon', metShown.map(rowItem)));
    if (rest.length) sections.push(section(sections.length ? 'Everyone else' : 'Everyone', rest.map(rowItem)));
    results.replaceChildren(...sections);
  }

  function drawAll() {
    drawRequest();
    drawMeta();
    drawCount();
    drawResults();
  }

  // ---- wiring ----------------------------------------------------------------------------

  function onBus(data, message) {
    if (!alive) return;
    if (message?.type === 'calendar:changed' && Array.isArray(data?.persona_ids) && !data.persona_ids.includes(me.id)) return;
    drawResults();
    refreshMet();
  }
  for (const type of ['calendar:changed', 'encounter:start', 'encounter:done']) {
    ctx.onCleanup(ctx.bus.on(type, onBus));
  }

  for (const type of ['request:incoming', 'request:cleared']) {
    ctx.onCleanup(ctx.bus.on(type, () => { if (alive) drawRequest(); }));
  }

  drawAll();
  refreshMet();
  if (mode === 'live') {
    if (!st.directory) loadDirectory().then(afterLoad);
    if (st.researchState === 'idle') loadResearch().then(afterLoad);
    else if (st.researchPromise) st.researchPromise.then(afterLoad);
    drawMeta();
  }

  return h('div', { class: 'screen people' },
    h('main', { class: 'scroll people-main' },
      h('header', { class: 'people-head' },
        h('p', { class: 'eyebrow' }, 'At KubeCon'),
        h('h1', { class: 'serif people-title' }, 'People'),
        countLine),
      h('div', { class: 'people-search', role: 'search' },
        h('label', { class: 'visually-hidden', for: searchId }, 'Search people'),
        h('span', { class: 'people-search-icon' }, icon('search', { size: 18, stroke: 1.9 })),
        input),
      h('div', { class: 'people-filters', role: 'group', 'aria-label': 'Filter people' }, chips),
      requestSlot,
      h('div', { class: 'people-meta' }, note, refresh),
      announcer,
      results),
    bottomNav('people'),
  );
}
