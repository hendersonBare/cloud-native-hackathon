// Recap: what you learned at the conference, how you're doing against your goals, and what's next.
// It replaces the Calendar tab; the calendar screen is still reachable from Home (Up next), People and
// the "Full schedule" link here, and the calendar API stays the source of truth for what you attended.
//
// - Talks attended = your calendar talks with capture on that have started (calendarClient, live or mock).
// - Each takeaway is pinned to the moment it was said: speaker + time into the recording, from the talk
//   transcripts in src/rapport_speakers/data/fixtures.json (the same index /api/speakers/search serves).
// - Goals are the ones in the person's profile (src/rapport_common/data/personas.json).
// Everything here is private to this phone; text goes in as text nodes only (ui.js h()).
import { h, icon, bottomNav, nextId } from '../ui.js';
import { openSheet, toast } from '../flow.js';
import { calendarClient } from '../calendar-api.js';
import { formatTime, weekdayShort } from '../time.js';

const EN = {
  title: ['Your ', 'recap'],
  sub: 'What you took away, and what to do next',
  report: 'Trip report',
  goals: 'Your goals',
  learned: 'What you learned',
  grew: 'How you grew',
  fresh: 'New to you',
  deeper: 'Went deeper',
  next: 'Next steps',
  comingUp: 'Coming up',
  schedule: 'Full schedule',
  loading: 'Loading your talks…',
  liveNow: 'Capturing now',
  noTakeaways: 'No transcript for this session yet.',
  talk: (n) => `${n} talk${n === 1 ? '' : 's'}`,
  conversation: (n) => `${n} conversation${n === 1 ? '' : 's'}`,
  step: (n) => `${n} next step${n === 1 ? '' : 's'}`,
  status: { done: 'Done', on_track: 'On track', progress: 'In progress', not_yet: 'Not yet' },
  reportTitle: 'Trip report',
  copy: 'Copy',
  close: 'Close',
  copied: 'Trip report copied',
  copyFailed: 'Could not copy. Select the text instead.',
  at: 'Said at',
};

const ES = {
  title: ['Tu ', 'resumen'],
  sub: 'Lo que aprendiste y lo que sigue',
  report: 'Informe del viaje',
  goals: 'Tus objetivos',
  learned: 'Lo que aprendiste',
  grew: 'Cómo creciste',
  fresh: 'Nuevo para ti',
  deeper: 'Más a fondo',
  next: 'Próximos pasos',
  comingUp: 'Lo que viene',
  schedule: 'Agenda completa',
  loading: 'Cargando tus charlas…',
  liveNow: 'Capturando ahora',
  noTakeaways: 'Aún no hay transcripción de esta sesión.',
  talk: (n) => `${n} charla${n === 1 ? '' : 's'}`,
  conversation: (n) => `${n} conversación${n === 1 ? '' : 'es'}`,
  step: (n) => `${n} próximo${n === 1 ? '' : 's'} paso${n === 1 ? '' : 's'}`,
  status: { done: 'Logrado', on_track: 'En camino', progress: 'En marcha', not_yet: 'Aún no' },
  reportTitle: 'Informe del viaje',
  copy: 'Copiar',
  close: 'Cerrar',
  copied: 'Informe copiado',
  copyFailed: 'No se pudo copiar. Selecciona el texto.',
  at: 'Dicho en',
};

// Takeaways quote or closely paraphrase one transcript segment; `at` is seconds into the recording.
export const CONTENT = {
  'acme.ava': {
    lang: 'en',
    text: EN,
    goals: [
      {
        goal: 'Find a design partner in healthcare',
        status: 'on_track',
        evidence: ['Met Bo, Platform Lead at Bluefin Health', 'Next: a small pilot once Kai signs off on HIPAA'],
      },
      {
        goal: 'Meet platform teams evaluating eBPF tracing',
        status: 'progress',
        evidence: ['Bo · Bluefin Health', 'Mia · Kestrel Robotics, runs eBPF on 200 robots', 'Priya · Lumenly Energy, coffee booked'],
      },
    ],
    talks: {
      'talk-otel-regulated': {
        title: 'OpenTelemetry in regulated industries',
        takeaways: [
          { text: 'Traces are the easiest signal to get approved: they carry timings and service names, not customer data.', speaker: 'Lena', at: 600 },
          { text: 'Ship only structured logs, with an allow-list of fields.', speaker: 'Lena', at: 1000 },
          { text: 'Run one collector gateway per region so the redaction rules live in one place auditors can read.', speaker: 'Lena', at: 1460 },
        ],
      },
      'talk-ebpf-zero-code': {
        title: 'Zero-code tracing with eBPF on Kubernetes',
        takeaways: [
          { text: 'Zero-code means no SDK, no sidecar and no redeploy: one agent per node as a DaemonSet.', speaker: 'Dev', at: 38 },
          { text: 'eBPF can’t see inside a process, so business attributes like a cart ID still need a line of SDK code.', speaker: 'Dev', at: 1100 },
          { text: 'Expect about 1–2% CPU on small nodes with the default probes; start with HTTP and DNS.', speaker: 'Dev', at: 1460 },
        ],
      },
      'talk-ebpf-edge': {
        title: 'eBPF on warehouse robots',
        takeaways: [
          { text: 'Set an overhead budget first: Kestrel allows 1% of CPU for observability on each robot.', speaker: 'Mia', at: 40 },
          { text: 'To stay under it they dropped DNS tracing and sample HTTP at 10%, but always keep errors.', speaker: 'Mia', at: 1449 },
          { text: 'Pin the kernel version across the fleet, or probes break one robot at a time.', speaker: 'Mia', at: 1300 },
        ],
      },
    },
    conversations: [
      {
        title: 'Hallway conversation with Bo',
        meta: 'Captured · 2:41 PM',
        takeaways: [
          { text: 'Bluefin is migrating a hospital platform and needs tracing with no code changes.', speaker: 'Bo', clock: '2:41 PM' },
          { text: 'Observability cost is their biggest concern, and they’re comparing another vendor.', speaker: 'Bo', clock: '2:42 PM' },
          { text: 'Kai, their Security Architect, must review HIPAA before a pilot.', speaker: 'Bo', clock: '2:43 PM' },
        ],
      },
    ],
    topics: {
      fresh: ['HIPAA reviews of telemetry', 'Log field allow-lists', 'Edge overhead budgets'],
      deeper: ['eBPF', 'OpenTelemetry', 'Kubernetes'],
    },
    next: [
      'Check that Sam sends Kai the security questionnaire',
      'Compare tracing costs with Bo and scope a small pilot',
      'Share the hospital case study (40% faster incidents) with Bluefin',
    ],
  },
  'bluefin.bo': {
    lang: 'es',
    text: ES,
    goals: [
      {
        goal: 'Encontrar trazas que no requieran cambios de código',
        status: 'on_track',
        evidence: ['Acme: trazas eBPF sin código que exportan a OpenTelemetry', 'Falta: la revisión HIPAA de Kai'],
      },
      {
        goal: 'Reducir los costos de observabilidad',
        status: 'progress',
        evidence: ['Charla de Priya: −28 % de gasto en seis meses con eBPF', 'Comparar costos de trazas con Ava'],
      },
    ],
    talks: {
      'talk-hipaa-k8s': {
        title: 'HIPAA-ready Kubernetes: what auditors ask for',
        takeaways: [
          { text: 'Los auditores siempre piden cuatro cosas: registros, cifrado, revisiones de acceso y documentación de proveedores.', speaker: 'Jonas', at: 20 },
          { text: 'Activa el registro de auditoría de Kubernetes desde el primer día y consérvalo seis años.', speaker: 'Jonas', at: 600 },
          { text: 'Pide a cada proveedor el cuestionario de seguridad completo antes de un piloto.', speaker: 'Jonas', at: 1350 },
        ],
      },
      'talk-ebpf-cost': {
        title: 'Cutting the cloud bill with eBPF',
        takeaways: [
          { text: 'eBPF cuenta peticiones y bytes por pod en el kernel: un mapa de costos sin cambiar ningún servicio.', speaker: 'Priya', at: 38 },
          { text: 'Un tercio de los despliegues casi no tenía tráfico fuera del horario laboral.', speaker: 'Priya', at: 400 },
          { text: 'Recortaron el gasto un 28 % en seis meses, y el ahorro se mantuvo porque los paneles siguieron encendidos.', speaker: 'Priya', at: 1200 },
        ],
      },
      'talk-ebpf-zero-code': {
        title: 'Zero-code tracing with eBPF on Kubernetes',
        takeaways: [
          { text: 'Sin código significa sin SDK, sin sidecar y sin volver a desplegar: un agente por nodo como DaemonSet.', speaker: 'Dev', at: 38 },
          { text: 'Exporta OTLP directamente, así que cualquier collector de OpenTelemetry sirve tal cual.', speaker: 'Dev', at: 1563 },
          { text: 'Para atributos de negocio, como el ID de un carrito, sigue haciendo falta una línea de SDK.', speaker: 'Dev', at: 1100 },
        ],
      },
    },
    conversations: [
      {
        title: 'Conversación de pasillo con Ava',
        meta: 'Capturada · 2:41 PM',
        takeaways: [
          { text: 'Acme ofrece trazas eBPF sin cambios de código que exportan a OpenTelemetry.', speaker: 'Ava', clock: '2:41 PM' },
          { text: 'En la red de un hospital redujeron un 40 % el tiempo de incidentes.', speaker: 'Ava', clock: '2:42 PM' },
          { text: 'Sam le enviará a Kai el cuestionario de seguridad.', speaker: 'Ava', clock: '2:43 PM' },
        ],
      },
    ],
    topics: {
      fresh: ['Auditorías HIPAA', 'Retención de registros', 'Mapas de costos con eBPF'],
      deeper: ['eBPF', 'Costos', 'Kubernetes'],
    },
    next: [
      'Comparar costos de trazas con Ava y planear un piloto pequeño',
      'Recibir el cuestionario de seguridad de Acme para Kai',
      'Activar el registro de auditoría antes del piloto',
    ],
  },
};

/** Seconds into a recording -> '0:38', '24:20' or '1:02:03'. */
export function formatOffset(seconds) {
  const s = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const secs = String(s % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${secs}` : `${minutes}:${secs}`;
}

/**
 * The talks you attended: calendar talks with capture on that have started by `now` (epoch ms),
 * newest first, each with its takeaways (empty when there is no transcript for it).
 */
export function attendedTalks(events, now, content) {
  return (Array.isArray(events) ? events : [])
    .filter((e) => e?.kind === 'talk' && e.capture && e.status !== 'declined' && Date.parse(e.starts_at) <= now)
    .sort((a, b) => Date.parse(b.starts_at) - Date.parse(a.starts_at))
    .map((event) => ({
      title: event.title,
      startsAt: event.starts_at,
      location: event.location || '',
      live: Date.parse(event.ends_at) > now,
      takeaways: content.talks[event.talk_id]?.takeaways || [],
    }));
}

/** Without a calendar: every talk this person has takeaways for, in the order written. */
export function fallbackTalks(content) {
  return Object.values(content.talks).map((talk) => ({
    title: talk.title, startsAt: null, location: '', live: false, takeaways: talk.takeaways,
  }));
}

/** The next `limit` events that haven't started, soonest first. */
export function comingUp(events, now, limit = 2) {
  return (Array.isArray(events) ? events : [])
    .filter((e) => e?.status !== 'declined' && Date.parse(e.starts_at) > now)
    .sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at))
    .slice(0, limit);
}

function cite(item) {
  return item.clock ? `${item.speaker} · ${item.clock}` : `${item.speaker} · ${formatOffset(item.at)}`;
}

/** Plain-text trip report: what a person sends their manager after the conference. */
export function tripReport(me, content, talks) {
  const t = content.text;
  const lines = [`${t.reportTitle} · ${me.name}, ${me.role}`, ''];
  lines.push(`${t.goals}:`);
  for (const g of content.goals) lines.push(`- ${g.goal} (${t.status[g.status]}): ${g.evidence.join('; ')}`);
  lines.push('', `${t.learned}:`);
  for (const talk of [...talks, ...content.conversations]) {
    if (!talk.takeaways.length) continue;
    lines.push(`* ${talk.title}`);
    for (const item of talk.takeaways) lines.push(`  - ${item.text} (${cite(item)})`);
  }
  lines.push('', `${t.fresh}: ${content.topics.fresh.join(', ')}`, `${t.deeper}: ${content.topics.deeper.join(', ')}`);
  lines.push('', `${t.next}:`, ...content.next.map((step) => `- ${step}`));
  return lines.join('\n');
}

const STATUS_TONE = { done: 'yes', on_track: 'yes', progress: 'gold', not_yet: 'muted' };

function takeawayList(items, t) {
  return h('ul', { class: 'recap-takeaways' }, items.map((item) => h('li', { class: 'recap-takeaway' },
    h('p', { class: 'recap-takeaway-text' }, item.text),
    h('p', { class: 'recap-cite tabular' },
      h('span', { class: 'visually-hidden' }, `${t.at} `),
      icon('mic', { size: 12, stroke: 2 }), cite(item)))));
}

function learnedCard({ title, meta, live, takeaways }, t) {
  const titleId = nextId('recap-item');
  return h('article', { class: 'card recap-card', 'aria-labelledby': titleId },
    h('div', { class: 'recap-card-head' },
      h('h3', { class: 'recap-card-title', id: titleId }, title),
      live ? h('span', { class: 'recap-live' }, h('span', { class: 'recap-live-dot rp-pulse', 'aria-hidden': 'true' }), t.liveNow) : null),
    meta ? h('p', { class: 'recap-card-meta' }, meta) : null,
    takeaways.length ? takeawayList(takeaways, t) : h('p', { class: 'recap-empty muted' }, t.noTakeaways));
}

function section(label, ...children) {
  const id = nextId('recap-section');
  return h('section', { class: 'recap-section', 'aria-labelledby': id },
    h('h2', { class: 'eyebrow', id }, label), ...children);
}

export function render(ctx) {
  const content = CONTENT[ctx.me.id] || CONTENT['acme.ava'];
  const t = content.text;
  let disposed = false;
  ctx.onCleanup(() => { disposed = true; });

  let talks = null; // null while the calendar loads
  let upcoming = [];

  const stats = h('p', { class: 'recap-stats tabular' });
  const talkList = h('div', { class: 'recap-list', 'aria-busy': 'true' }, h('p', { class: 'muted recap-loading' }, t.loading));
  const upcomingList = h('div', { class: 'recap-upcoming' });

  function drawStats() {
    const parts = [
      talks ? t.talk(talks.length) : null,
      t.conversation(content.conversations.length),
      t.step(content.next.length),
    ].filter(Boolean);
    stats.textContent = parts.join(' · ');
  }

  function drawTalks() {
    talkList.removeAttribute('aria-busy');
    const cards = talks.map((talk) => learnedCard({
      title: talk.title,
      meta: talk.startsAt ? [formatTime(talk.startsAt), talk.location].filter(Boolean).join(' · ') : '',
      live: talk.live,
      takeaways: talk.takeaways,
    }, t));
    const chats = content.conversations.map((c) => learnedCard({ ...c, live: false }, t));
    talkList.replaceChildren(...cards, ...chats);
  }

  function drawUpcoming() {
    upcomingList.replaceChildren(
      ...upcoming.map((event) => h('div', { class: 'recap-upcoming-row' },
        h('span', { class: 'recap-upcoming-time tabular' }, `${weekdayShort(event.starts_at)} ${formatTime(event.starts_at)}`),
        h('span', { class: 'recap-upcoming-title' }, event.title))),
      h('a', { class: 'recap-schedule', href: '#/calendar' },
        icon('calendar', { size: 16, stroke: 1.9 }), h('span', null, t.schedule), icon('chevron', { size: 16, stroke: 1.9 })),
    );
  }

  function openReport() {
    const report = tripReport(ctx.me, content, talks || fallbackTalks(content));
    const body = h('pre', { class: 'recap-report-text', tabindex: '0' }, report);
    let close = () => {};
    const copy = h('button', {
      type: 'button', class: 'btn btn-primary btn-sm',
      onClick: () => {
        const write = navigator.clipboard?.writeText?.(report);
        Promise.resolve(write ?? Promise.reject(new Error('clipboard unavailable')))
          .then(() => toast(t.copied))
          .catch(() => toast(t.copyFailed));
      },
    }, t.copy);
    const content2 = h('div', { class: 'recap-sheet', lang: content.lang },
      h('h2', { class: 'serif recap-sheet-title' }, t.reportTitle),
      body,
      h('div', { class: 'recap-sheet-actions' },
        h('button', { type: 'button', class: 'btn btn-sm', onClick: () => close() }, t.close), copy));
    close = openSheet(content2, { label: t.reportTitle }) || close;
  }

  drawStats();
  drawUpcoming();

  calendarClient(ctx).view(ctx.me.id)
    .then((view) => {
      if (disposed) return;
      const now = Date.parse(view?.now) || Date.now();
      const events = Array.isArray(view?.events) ? view.events : [];
      talks = attendedTalks(events, now, content);
      if (!talks.length) talks = fallbackTalks(content);
      upcoming = comingUp(events, now);
    })
    .catch((error) => {
      console.warn('Recap calendar unavailable', error?.status ?? error?.name ?? 'Error');
      if (disposed) return;
      talks = fallbackTalks(content);
      upcoming = [];
    })
    .then(() => {
      if (disposed) return;
      drawStats();
      drawTalks();
      drawUpcoming();
    });

  const goals = content.goals.map((g) => {
    const goalId = nextId('recap-goal');
    return h('article', { class: 'card recap-goal', 'aria-labelledby': goalId },
      h('div', { class: 'recap-card-head' },
        h('h3', { class: 'recap-card-title', id: goalId }, g.goal),
        h('span', { class: `recap-status tone-${STATUS_TONE[g.status] || 'muted'}` }, t.status[g.status])),
      h('ul', { class: 'recap-evidence' }, g.evidence.map((line) => h('li', null, line))));
  });

  const chips = (items, tone) => h('ul', { class: 'recap-chips' },
    items.map((item) => h('li', { class: `recap-chip tone-${tone}` }, item)));

  return h('div', { class: 'screen recap', lang: content.lang },
    h('main', { class: 'scroll recap-main' },
      h('header', { class: 'recap-head' },
        h('div', { class: 'stack recap-head-copy' },
          h('h1', { class: 'serif recap-title' }, t.title[0], h('em', null, t.title[1])),
          h('p', { class: 'recap-sub muted' }, t.sub),
          stats),
        h('button', { type: 'button', class: 'btn btn-sm recap-report', onClick: openReport },
          icon('file', { size: 17, stroke: 1.9 }), h('span', null, t.report))),
      section(t.goals, h('div', { class: 'recap-list' }, goals)),
      section(t.learned, talkList),
      section(t.grew,
        h('div', { class: 'card recap-grew' },
          h('h3', { class: 'recap-grew-label' }, t.fresh), chips(content.topics.fresh, 'gold'),
          h('h3', { class: 'recap-grew-label' }, t.deeper), chips(content.topics.deeper, 'steel'))),
      section(t.next,
        h('ul', { class: 'card recap-next' }, content.next.map((step) => h('li', { class: 'recap-next-row' },
          h('span', { class: 'recap-next-box', 'aria-hidden': 'true' }), h('span', null, step)))),
        h('h3', { class: 'eyebrow recap-coming' }, t.comingUp),
        upcomingList),
    ),
    bottomNav('recap'),
  );
}
