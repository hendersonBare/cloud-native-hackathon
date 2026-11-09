// Agent research brief, ported from Person.dc.html.
import { h, icon, avatar, topbar, bottomNav, nextId } from '../ui.js';

const CONTENT = {
  'acme.ava': {
    'bluefin.bo': {
      role: 'Platform Lead, Bluefin Health',
      focus: 'Tracing with no code changes for a hospital network, observability cost',
      atKubeCon: 'Attending “Zero-code tracing with eBPF on Kubernetes”',
      saidToday: '“We can\'t touch app code in the clinical systems”',
      why: [
        'Bluefin needs tracing without code changes',
        'Your hospital case study matches their migration',
        'Cost is their main concern, and eBPF keeps overhead low',
        "You're both at KubeCon this week",
      ],
      lang: 'en',
      sources: ['Company blog', 'Conference page', 'Your transcripts'],
    },
  },
  'bluefin.bo': {
    'acme.ava': {
      role: 'Solutions Engineer, Acme Observability',
      focus: 'Zero-code eBPF tracing, OpenTelemetry',
      atKubeCon: 'Booth 12 demos',
      saidToday: '“We cut incident time 40% at a hospital network”',
      why: [
        'Acme ya resolvió el rastreo sin cambios de código en un hospital',
        'Su caso de estudio encaja con nuestra migración',
        'Bajo costo y poca sobrecarga con eBPF',
        'Los dos están en KubeCon esta semana',
      ],
      lang: 'es',
      sources: ['Company blog', 'Conference page', 'Your transcripts'],
    },
  },
};

function fallbackContent(me, subject) {
  const spanish = me.lang === 'es';
  return {
    role: [subject.title, subject.orgName].filter(Boolean).join(', ') || subject.role,
    focus: subject.role || subject.title || 'Not yet researched',
    atKubeCon: 'Attending KubeCon',
    saidToday: 'No transcript excerpt available yet',
    why: spanish
      ? [
        `Conoce la perspectiva de ${subject.name} sobre ${subject.orgName || subject.title || 'su trabajo'}`,
        'Intercambia experiencias sobre los retos de sus equipos',
        'Explora intereses y objetivos en común',
        'Encuentra oportunidades para colaborar después de KubeCon',
      ]
      : [
        `Compare notes with ${subject.name} about ${subject.orgName || subject.title || 'their work'}`,
        'Exchange experiences about the challenges your teams face',
        'Explore shared interests and goals',
        'Find opportunities to collaborate after KubeCon',
      ],
    lang: spanish ? 'es' : 'en',
    sources: ['Public profile'],
  };
}

export function render(ctx) {
  const subjectId = ctx.route.params.id || ctx.store.speakers?.s2?.personaId;
  const subject = (subjectId && ctx.person(subjectId)) || ctx.peer;
  const content = CONTENT[ctx.me.id]?.[subject.id] || fallbackContent(ctx.me, subject);
  const briefId = nextId('person-brief');
  const whyId = nextId('person-why');
  let submitting = false;

  function requestPending() {
    const encounter = ctx.store.encounter;
    return encounter &&
      (encounter.initiator === subject.id || encounter.responder === subject.id) &&
      (encounter.status === 'waiting' || encounter.status === 'talking');
  }

  const connectLabel = h('span');
  const connect = h('button', {
    type: 'button',
    class: 'btn btn-primary person-connect',
    onClick: () => {
      if (submitting || requestPending()) return;
      submitting = true;
      drawAction();
      ctx.bus.emit('ui:connect', { from: ctx.me.id, to: subject.id, initiated_by: 'human' });
      if (ctx.store.home) ctx.store.home.talking = subject.id;
      ctx.go('exchange');
    },
  }, icon('people', { size: 20, stroke: 1.8 }), connectLabel);

  function drawAction() {
    const pending = submitting || !!requestPending();
    connect.disabled = pending;
    connectLabel.textContent = pending ? 'Request sent' : 'Connect our agents';
  }
  drawAction();
  for (const event of ['ui:connect', 'encounter:start', 'encounter:done', 'encounter:declined']) {
    ctx.onCleanup(ctx.bus.on(event, drawAction));
  }

  const rows = [
    ['Role', content.role],
    ['Focus', content.focus],
    ['At KubeCon', content.atKubeCon],
    ['Said today', content.saidToday],
  ];

  return h('div', { class: 'screen person', lang: 'en' },
    topbar({
      back: 'live',
      backLabel: 'Back to transcript',
      title: 'Brief',
      titleTag: 'p',
      right: h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'More options' },
        icon('more', { size: 20 })),
    }),
    h('main', { class: 'scroll person-main' },
      h('div', { class: 'person-identity' },
        avatar(subject.initials, subject.tone, 60, 20),
        h('div', { class: 'person-heading' },
          h('h1', { class: 'serif person-name' }, subject.name),
          h('p', { class: 'person-confirmed' }, 'Met at KubeCon · You Verified'))),
      h('section', { class: 'card person-research', 'aria-labelledby': briefId },
        h('div', { class: 'person-research-head' },
          h('span', { class: 'person-agent-mark', 'aria-hidden': 'true' }, icon('agent', { size: 16 })),
          h('h2', { id: briefId, class: 'person-research-title' }, 'Researched by your agent'),
          h('span', { class: 'badge' }, 'Public')),
        h('dl', { class: 'person-facts' }, rows.map(([label, value]) =>
          h('div', { class: 'person-fact' }, h('dt', null, label), h('dd', null, value)))),
        h('div', { class: 'person-sources', 'aria-label': 'Sources' },
          content.sources.map((source) => h('span', { class: 'pill' }, source)))),
      h('section', { class: 'card-gold person-why', 'aria-labelledby': whyId },
        h('h2', { id: whyId, class: 'eyebrow gold' }, 'Why connect'),
        h('ul', { class: 'person-reasons', lang: content.lang, role: 'list' },
          content.why.map((reason) => h('li', { class: 'person-reason' },
            h('span', { class: 'person-reason-dot', 'aria-hidden': 'true' }),
            h('span', null, reason)))))),
    h('div', { class: 'action-row', 'aria-live': 'polite' },
      h('a', { class: 'btn', href: '#/home' }, 'Not now'),
      connect),
    bottomNav('person'),
  );
}
