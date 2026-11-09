// Agent research brief, ported from Person.dc.html. Designed pairs keep their hand-written
// copy; other people are briefed from the viewer's research card when there is one. A
// "Meet in person" card finds a coffee slot through the calendar. Research text comes from
// other people's agents, so it is only ever rendered as text.
import { h, icon, avatar, topbar, bottomNav, nextId } from '../ui.js';
import { calendarClient, calendarErrorMessage } from '../calendar-api.js';
import { formatSlot } from '../time.js';
import { AGENT_ORGS, metIds, withZone } from '../people-model.js';
import { toast } from '../flow.js';
import { mockResearchFor } from '../mock-research.js';

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

function slotLabel(value) {
  try {
    return formatSlot(value);
  } catch {
    return 'a time to be confirmed';
  }
}

/** The viewer's research card for this person, from the cache the People screen keeps. */
function researchCard(ctx, subjectId) {
  const research = ctx.mode === 'live' ? ctx.store.people?.research : mockResearchFor(ctx.me.id);
  if (!research || research.persona_id !== ctx.me.id) return null;
  return (research.cards || []).find((card) => card.persona_id === subjectId) || null;
}

function contentFromCard(card, me) {
  const spanish = me.lang === 'es';
  const talk = card.their_talks?.[0];
  const why = [withZone(card.why_meet, talk?.starts_at)];
  if (card.shared_interests?.length) {
    why.push(`${spanish ? 'Intereses en común' : 'Shared interests'}: ${card.shared_interests.join(', ')}`);
  }
  return {
    role: [card.title, card.org_name].filter(Boolean).join(', '),
    focus: card.headline,
    atKubeCon: talk ? `Speaking: ${talk.title} · ${slotLabel(talk.starts_at)}` : 'Attending KubeCon',
    saidToday: 'No transcript excerpt available yet',
    why: why.filter(Boolean),
    lang: spanish ? 'es' : 'en',
    sources: ['Public profile', 'Your agent', ...(card.company_history?.length ? ['Your notes'] : [])],
  };
}

/** The person this brief is about. Only a missing id falls back to the peer; an unknown id is null. */
function findSubject(ctx, id) {
  if (!id) return ctx.peer;
  return ctx.person(id) || ctx.store.people?.directory?.find((p) => p.id === id) || null;
}

function hasAgent(ctx, subject) {
  const entry = ctx.store.people?.directory?.find((p) => p.id === subject.id);
  return entry ? !!entry.agent : AGENT_ORGS.includes(subject.org);
}

function notFound(ctx) {
  return h('div', { class: 'screen person', lang: 'en' },
    topbar({ back: 'people', backLabel: 'Back to people', title: 'Brief', titleTag: 'p' }),
    h('main', { class: 'scroll person-main' },
      h('div', { class: 'person-missing' },
        h('h1', { class: 'serif person-name' }, 'Person not found'),
        h('p', { class: 'muted' }, 'We could not find that person in the conference directory.'),
        h('a', { class: 'btn btn-primary', href: '#/people' }, 'Open People'))),
    bottomNav('person'),
  );
}

export function render(ctx) {
  const subjectId = ctx.route.params.id || ctx.store.speakers?.s2?.personaId;
  const subject = findSubject(ctx, subjectId);
  if (!subject) return notFound(ctx);
  const fromPeople = ctx.route.params.from === 'people';
  const fromRequest = ctx.route.params.from === 'request';
  const designed = CONTENT[ctx.me.id]?.[subject.id];
  const card = designed ? null : researchCard(ctx, subject.id);
  const content = designed || (card && contentFromCard(card, ctx.me)) || fallbackContent(ctx.me, subject);
  const met = metIds(ctx.me.id, { encounter: ctx.store.encounter, events: ctx.store.people?.events })
    .includes(subject.id);
  const confirmedLine = designed ? 'Met at KubeCon · You Verified' : met ? 'Met at KubeCon' : 'At KubeCon';
  const briefId = nextId('person-brief');
  const whyId = nextId('person-why');
  let submitting = false;

  function requestPending() {
    const encounter = ctx.store.encounter;
    return encounter &&
      (encounter.initiator === subject.id || encounter.responder === subject.id) &&
      (encounter.status === 'waiting' || encounter.status === 'talking');
  }

  /** A connect request from this person that is waiting for my answer (set by flow.js). */
  function incomingRequest() {
    const request = ctx.store.incoming;
    return request && request.from === subject.id ? request : null;
  }

  const agentAvailable = hasAgent(ctx, subject);
  const connectLabel = h('span');
  const connect = h('button', {
    type: 'button',
    class: 'btn btn-primary person-connect',
    onClick: () => {
      if (submitting || requestPending() || incomingRequest()) return;
      submitting = true;
      drawAction();
      ctx.bus.emit('ui:connect', { from: ctx.me.id, to: subject.id, initiated_by: 'human' });
      if (ctx.store.home) ctx.store.home.talking = subject.id;
      ctx.go('exchange');
    },
  }, icon('people', { size: 20, stroke: 1.8 }), connectLabel);

  function respond(accept) {
    const request = incomingRequest();
    if (!request) return;
    ctx.bus.emitLocal('ui:respond', { request_id: request.request_id, accept });
    if (!accept) ctx.go('home');
  }
  const decline = h('button', { type: 'button', class: 'btn person-decline', onClick: () => respond(false) }, 'Decline');
  const accept = h('button', { type: 'button', class: 'btn btn-primary person-accept', onClick: () => respond(true) },
    icon('check', { size: 20, stroke: 2 }), 'Accept');
  const notNow = h('a', { class: 'btn', href: '#/home' }, 'Not now');
  const noAgent = h('p', { class: 'person-no-agent' },
    `No Rapport agent at ${subject.orgName || 'this company'} yet`);
  const requestSlot = h('div', { class: 'person-request-slot' });
  const actionRow = h('div', { class: 'action-row', 'aria-live': 'polite' });
  let actionMode = null;

  function drawAction() {
    const incoming = incomingRequest();
    const mode = incoming ? 'respond' : agentAvailable ? 'connect' : 'none';
    if (mode !== actionMode) {
      actionMode = mode;
      if (mode === 'respond') actionRow.replaceChildren(decline, accept);
      else actionRow.replaceChildren(notNow, mode === 'connect' ? connect : noAgent);
      requestSlot.replaceChildren(...(incoming
        ? [h('p', { class: 'person-request' }, icon('agent', { size: 16 }),
          incoming.initiated_by === 'agent'
            ? `${subject.name}'s agent wants to connect. Accept to let your agents talk.`
            : `${subject.name} wants your agents to talk. Accept to let them meet.`)]
        : []));
    }
    const pending = submitting || !!requestPending();
    connect.disabled = pending;
    connectLabel.textContent = pending ? 'Request sent' : 'Connect our agents';
  }
  drawAction();
  for (const event of ['ui:connect', 'encounter:start', 'encounter:done', 'encounter:declined',
    'request:incoming', 'request:cleared']) {
    ctx.onCleanup(ctx.bus.on(event, drawAction));
  }

  // ---- Meet in person (calendar) -------------------------------------------------------
  // The buttons are created once and updated in place, so keyboard focus survives a pending
  // state. They use aria-disabled (not disabled) while busy for the same reason.
  const meetId = nextId('person-meet');
  const meet = {
    phase: 'loading', meeting: null, notice: null, error: null, pending: false, confirming: false, key: null,
  };
  const meetMain = h('div', { class: 'person-meet-main' });
  const meetError = h('p', { class: 'person-meet-error', role: 'alert' });
  meetError.hidden = true;
  const meetBody = h('div', { class: 'person-meet-body', 'aria-live': 'polite' }, meetMain, meetError);
  let meetNotice = null;
  let alive = true;
  let meetSeq = 0;
  ctx.onCleanup(() => { alive = false; });

  const findLabel = h('span');
  const findBtn = h('button', {
    type: 'button',
    class: 'btn btn-sm person-meet-btn',
    disabled: subject.id === ctx.me.id,
    onClick: () => findTime(),
  }, icon('calendar', { size: 18, stroke: 1.8 }), findLabel);
  const confirmLabel = h('span');
  const confirmBtn = h('button', {
    type: 'button',
    class: 'btn btn-sm btn-primary person-meet-btn',
    onClick: () => confirmMeeting(),
  }, icon('check', { size: 18, stroke: 2 }), confirmLabel);
  const calendarLink = h('a', { class: 'btn btn-sm person-meet-link', href: '#/calendar' }, 'Open calendar');

  function myResponse(event) {
    return event.responses?.[ctx.me.id];
  }

  function statusLine(event) {
    if (event.status === 'confirmed') return 'Confirmed';
    if (myResponse(event) === 'pending') return 'Waiting for you to confirm';
    if (event.note && !/tap to confirm/i.test(event.note)) return event.note;
    return `Waiting for ${subject.name}`;
  }

  function noticeFor(event) {
    const { notice } = meet;
    return notice && event && notice.eventId === event.event_id && notice.status === event.status ? notice : null;
  }

  function buildMeetMain() {
    meetNotice = null;
    if (meet.phase === 'loading') {
      return [h('p', { class: 'person-meet-text muted' }, 'Checking your calendar…')];
    }
    const event = meet.meeting;
    if (!event) {
      return [
        h('p', { class: 'person-meet-text muted' },
          `Your agent will look for a free 30-minute coffee with ${subject.name}.`),
        findBtn,
      ];
    }
    const confirmed = event.status === 'confirmed';
    const notice = noticeFor(event);
    const parts = [];
    if (notice) {
      meetNotice = h('p', { class: 'person-meet-notice', tabindex: '-1' },
        icon('check', { size: 16, stroke: 2.2 }), notice.text);
      parts.push(meetNotice);
    } else {
      parts.push(
        h('p', { class: 'person-meet-title' }, event.title),
        h('p', { class: 'person-meet-time tabular' }, slotLabel(event.starts_at)),
        h('p', { class: `person-meet-status${confirmed ? ' confirmed' : ''}` },
          icon(confirmed ? 'check' : 'clock', { size: 15, stroke: 2 }), statusLine(event)));
    }
    if (myResponse(event) === 'pending' && event.status !== 'declined') parts.push(confirmBtn);
    parts.push(calendarLink);
    return parts;
  }

  function drawMeet() {
    const event = meet.meeting;
    const key = meet.phase === 'loading' ? 'loading' : !event ? 'find' : [
      'meeting', event.event_id, event.status, event.starts_at, event.note, myResponse(event), !!noticeFor(event),
    ].join('|');
    if (key !== meet.key) {
      meet.key = key;
      // Rebuilding removes the pressed button; keep keyboard focus inside the card.
      const active = globalThis.document?.activeElement;
      const hadFocus = !!active && meetMain.contains(active);
      meetMain.replaceChildren(...buildMeetMain());
      if (hadFocus) (meetNotice || (active.isConnected ? active : calendarLink)).focus({ preventScroll: true });
    }
    findLabel.textContent = meet.pending ? 'Finding a time…' : 'Find a time';
    findBtn.setAttribute('aria-disabled', String(meet.pending));
    findBtn.setAttribute('aria-busy', String(meet.pending));
    confirmLabel.textContent = meet.confirming ? 'Confirming…' : 'Confirm';
    confirmBtn.setAttribute('aria-disabled', String(meet.confirming));
    confirmBtn.setAttribute('aria-busy', String(meet.confirming));
    meetError.textContent = meet.error || '';
    meetError.hidden = !meet.error;
  }

  /** The earliest meeting with this person that has not ended yet (the scheduler reuses only those). */
  function existingMeeting(view) {
    const now = Date.parse(view?.now) || Date.now();
    return (view?.events || [])
      .filter((event) => event.kind === 'meeting' && event.status !== 'declined'
        && (event.with_persona_ids || []).includes(subject.id) && Date.parse(event.ends_at) > now)
      .sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at))[0] || null;
  }

  function loadMeet() {
    const seq = ++meetSeq;
    calendarClient(ctx).view(ctx.me.id)
      .then((view) => {
        if (!alive || seq !== meetSeq) return;
        meet.phase = 'ready';
        meet.error = null;
        meet.meeting = existingMeeting(view);
        drawMeet();
      })
      .catch((error) => {
        if (!alive || seq !== meetSeq) return;
        console.warn('Person calendar unavailable', error?.status ?? error?.name ?? 'Error');
        meet.phase = 'ready';
        meet.error = 'Could not load your calendar. Try again.';
        drawMeet();
      });
  }

  function findTime() {
    if (meet.pending || subject.id === ctx.me.id) return;
    meet.pending = true;
    meet.error = null;
    drawMeet();
    calendarClient(ctx).propose({
      persona_id: ctx.me.id, with_persona_id: subject.id, purpose: 'coffee', duration_minutes: 30,
    }).then((proposal) => {
      if (!alive) return;
      meet.pending = false;
      meet.meeting = proposal.event;
      const slot = slotLabel(proposal.starts_at);
      const text = proposal.created === false
        ? 'Already on your calendar'
        : `Coffee proposed for ${slot} · waiting for ${subject.name}`;
      meet.notice = { eventId: proposal.event?.event_id, status: proposal.event?.status, text };
      drawMeet();
      toast(proposal.created === false ? `Already on your calendar · ${slot}` : `Coffee proposed with ${subject.name}`);
    }).catch((error) => {
      if (!alive) return;
      meet.pending = false;
      meet.error = calendarErrorMessage(error, 'propose');
      drawMeet();
      toast(meet.error, { tone: 'error' });
    });
  }

  function confirmMeeting() {
    const event = meet.meeting;
    if (meet.confirming || !event) return;
    meet.confirming = true;
    meet.error = null;
    drawMeet();
    calendarClient(ctx).respond(event.event_id, { persona_id: ctx.me.id, response: 'accept' })
      .then((updated) => {
        if (!alive) return;
        meet.confirming = false;
        meet.meeting = updated;
        const text = updated.status === 'confirmed'
          ? `Confirmed for ${slotLabel(updated.starts_at)}`
          : `You accepted · waiting for ${subject.name}`;
        meet.notice = { eventId: updated.event_id, status: updated.status, text };
        drawMeet();
        toast(updated.status === 'confirmed' ? `Coffee with ${subject.name} confirmed` : 'You accepted');
      })
      .catch((error) => {
        if (!alive) return;
        meet.confirming = false;
        meet.error = calendarErrorMessage(error, 'confirm');
        drawMeet();
        toast(meet.error, { tone: 'error' });
      });
  }

  drawMeet();
  loadMeet();
  ctx.onCleanup(ctx.bus.on('calendar:changed', (data) => {
    if (Array.isArray(data?.persona_ids) && !data.persona_ids.includes(ctx.me.id)) return;
    loadMeet();
  }));

  const rows = [
    ['Role', content.role],
    ['Focus', content.focus],
    ['At KubeCon', content.atKubeCon],
    ['Said today', content.saidToday],
  ];

  return h('div', { class: 'screen person', lang: 'en' },
    topbar({
      back: fromPeople ? 'people' : fromRequest ? 'home' : 'live',
      backLabel: fromPeople ? 'Back to people' : fromRequest ? 'Back to home' : 'Back to transcript',
      title: 'Brief',
      titleTag: 'p',
      right: h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'More options' },
        icon('more', { size: 20 })),
    }),
    h('main', { class: 'scroll person-main' },
      requestSlot,
      h('div', { class: 'person-identity' },
        avatar(subject.initials, subject.tone, 60, 20),
        h('div', { class: 'person-heading' },
          h('h1', { class: 'serif person-name' }, subject.name),
          h('p', { class: 'person-confirmed' }, confirmedLine))),
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
            h('span', null, reason))))),
      h('section', { class: 'card person-meet', 'aria-labelledby': meetId },
        h('div', { class: 'person-research-head' },
          h('span', { class: 'person-agent-mark', 'aria-hidden': 'true' }, icon('calendar', { size: 16 })),
          h('h2', { id: meetId, class: 'person-research-title' }, 'Meet in person')),
        meetBody)),
    actionRow,
    bottomNav('person'),
  );
}
