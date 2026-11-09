// Match summary, adapted from Match.dc.html for each demo persona.
import { h, icon, avatar, agentMark, bottomNav, eyebrow, nextId } from '../ui.js';
import { livePrivateBrief, liveSharedBrief } from './match-live.js';

const CONTENT = {
  'acme.ava': {
    shared: 'Role, hospital case study, free/busy, security whitepaper',
    lang: 'en',
    opportunities: [
      ['Zero-code tracing pilot at Bluefin', 'Bring Acme’s eBPF tracing to Bluefin’s clinical systems'],
      ['HIPAA review with Kai', 'Walk through the security whitepaper together'],
      ['Joint case study', 'Share the hospital rollout results with the community'],
    ],
    privateBrief: 'Sam promised Kai the security questionnaire before the pilot. Send it before Wednesday. Bluefin is also evaluating a competitor.',
  },
  'bluefin.bo': {
    shared: 'Role, team priorities, free/busy',
    lang: 'es',
    opportunities: [
      ['Piloto de trazas sin cambios de código en Bluefin', 'Probar eBPF de Acme en nuestros sistemas clínicos'],
      ['Revisión HIPAA con Kai', 'Revisar el documento de seguridad de Acme con Kai'],
      ['Caso de estudio conjunto', 'Compartir los resultados de nuestra migración hospitalaria'],
    ],
    privateBrief: 'Acme encaja con la migración sin cambios de código. Pide precios por nodo antes del miércoles y confirma la revisión HIPAA con Kai.',
  },
};

export function render(ctx) {
  const { me, store } = ctx;
  const encounter = store.encounter;
  const counterpartId = encounter?.initiator === me.id ? encounter.responder
    : encounter?.responder === me.id ? encounter.initiator : null;
  const counterpart = (counterpartId && ctx.person(counterpartId)) || ctx.peer;
  const content = CONTENT[me.id] || CONTENT['acme.ava'];
  const counterpartShared = CONTENT[counterpart.id]?.shared || 'Role, free/busy';
  const st = store.match || (store.match = { drafts: {} });
  const draftKey = encounter?.encounter_id || counterpart.id;
  const nextHeading = nextId('match-next');
  const summaryHeading = nextId('match-summary');
  const opportunitiesHeading = nextId('match-opportunities');
  const privateHeading = nextId('match-private');

  const confirmation = h('p', { class: 'match-confirmation', 'aria-live': 'polite', lang: 'en' },
    st.drafts[draftKey] ? 'Draft opened' : '');

  const meeting = h('section', { class: 'card-fill match-meeting', 'aria-labelledby': nextHeading },
    h('div', { class: 'row match-meeting-row' },
      h('span', { class: 'match-date tabular', 'aria-hidden': 'true' },
        h('span', { class: 'match-weekday' }, 'WED'),
        h('span', { class: 'match-day' }, '11')),
      h('div', { class: 'grow match-meeting-copy' },
        h('h2', { id: nextHeading }, 'Coffee, 10:00 AM'),
        h('p', null, 'The slot both agents agreed on'))),
    h('div', { class: 'match-actions' },
      h('button', {
        type: 'button',
        class: 'match-message',
        onClick: () => {
          st.drafts[draftKey] = true;
          confirmation.textContent = 'Draft opened';
        },
      }, `Message ${counterpart.name}`),
      h('a', { class: 'match-calendar', href: '#/calendar' }, 'Add to calendar')),
    confirmation,
  );

  const summary = h('section', { class: 'match-summary', 'aria-labelledby': summaryHeading },
    eyebrow('What the agents exchanged', { id: summaryHeading }),
    h('div', { class: 'match-shared-grid' },
      h('div', { class: 'match-shared match-shared-self' },
        h('p', { class: 'match-shared-label' }, 'You shared'),
        h('p', null, content.shared)),
      h('div', { class: 'match-shared match-shared-peer' },
        h('p', { class: 'match-shared-label' }, `${counterpart.name} shared`),
        h('p', null, counterpartShared))),
  );

  const opportunities = h('section', { class: 'match-opportunities', 'aria-labelledby': opportunitiesHeading },
    eyebrow('Collaboration opportunities', { id: opportunitiesHeading }),
    h('ol', { class: 'match-opportunity-list', lang: content.lang, role: 'list' },
      content.opportunities.map(([title, description], i) => h('li', { class: 'match-opportunity' },
        h('span', { class: 'match-number tabular', 'aria-hidden': 'true' }, String(i + 1).padStart(2, '0')),
        h('div', { class: 'grow match-opportunity-copy' },
          h('h3', null, title),
          h('p', null, description))))),
  );

  const staticPrivateBrief = h('section', {
    class: 'card-gold match-private',
    'aria-labelledby': privateHeading,
    'aria-live': 'polite',
    lang: me.lang || content.lang,
  },
  h('h2', { id: privateHeading, class: 'match-private-heading', lang: 'en' },
    icon('lock', { size: 18 }), 'Private brief · only you see this'),
  h('p', null, content.privateBrief));
  // Live mode shows the gateway's briefs instead of the scripted demo copy.
  const live = ctx.mode === 'live';
  const privateBrief = live ? livePrivateBrief(ctx) : staticPrivateBrief;

  return h('div', { class: 'screen match', lang: 'en' },
    h('header', { class: 'match-head' },
      eyebrow('Both of you opted in', { tag: 'p', gold: true }),
      h('a', { class: 'icon-btn', href: '#/home', 'aria-label': 'Close and go home' },
        icon('close', { size: 20, stroke: 1.8 }))),
    h('main', { class: 'scroll match-main' },
      h('div', { class: 'match-intro' },
        h('div', { class: 'avatar-pair match-avatars', 'aria-hidden': 'true' },
          agentMark(48, 22), avatar(counterpart.initials, counterpart.tone, 48, 16)),
        h('h1', { class: 'serif match-title' }, "It's a ", h('em', null, 'match')),
        h('p', { class: 'match-subtitle' }, `Your agent and ${counterpart.name}’s agent found real common ground.`)),
      live ? [liveSharedBrief(ctx), privateBrief] : [
        meeting,
        summary,
        opportunities,
        privateBrief,
        h('p', { class: 'match-shared-brief' },
          h('strong', null, 'Shared brief'),
          h('span', null, "Coffee Wed 10:00 AM · zero-code eBPF tracing for Bluefin's clinical systems.")),
      ]),
    bottomNav('match'),
  );
}
