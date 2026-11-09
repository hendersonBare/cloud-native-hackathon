// Calendar · Auto-transcribe, updated to the v2 Calendar.dc.html (events on Monday and Wednesday only).
import { h, icon, bottomNav, nextId } from '../ui.js';

const CONTENT = {
  'acme.ava': {
    earlier: [
      { time: '9:00 AM', title: 'Opening keynotes', note: 'Transcribed · in Team memory' },
      { time: '1:30 PM', title: 'OpenTelemetry at Scale', note: 'Transcribed · 3 speakers named' },
    ],
    live: 'Hallway conversation',
    later: [
      { key: 'poster', time: '4:00 PM', title: 'eBPF tracing deep dive', location: 'Room 2' },
      { key: 'dinner', time: '6:30 PM', title: 'Partner dinner', location: 'Off the record' },
    ],
  },
  'bluefin.bo': {
    earlier: [
      { time: '9:00 AM', title: 'Opening keynotes', note: 'Transcribed · in Team memory' },
      { time: '1:30 PM', title: 'Hospital Platform Migration', note: 'Transcribed · 3 speakers named' },
    ],
    live: 'Platform track Q&A',
    later: [
      { key: 'poster', time: '4:00 PM', title: 'Observability cost poster session', location: 'Room 2' },
      { key: 'dinner', time: '5:00 PM', title: 'Platform team sync', location: 'Bluefin Health' },
    ],
  },
};

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const dateLabel = (day) => `${DAYS[day]}, November ${9 + day}, 2026`;

export function render(ctx) {
  const content = CONTENT[ctx.me.id];
  const st = ctx.store.calendar || (ctx.store.calendar = {
    day: 0, conf: true, poster: true, dinner: false,
  });

  const track = () => h('span', { class: 'capture-track', 'aria-hidden': 'true' },
    h('span', { class: 'capture-knob' }));

  const conferenceTitle = nextId('calendar-conference');
  const conferenceNote = nextId('calendar-conference-note');
  const conference = h('button', {
    type: 'button', class: 'conference-mode', role: 'switch',
    'aria-checked': String(st.conf), 'aria-labelledby': conferenceTitle,
    'aria-describedby': conferenceNote,
    onClick: () => {
      st.conf = !st.conf;
      conference.setAttribute('aria-checked', String(st.conf));
    },
  },
  h('span', { class: 'event-copy' },
    h('span', { id: conferenceTitle, class: 'event-title' }, 'Conference mode · KubeCon'),
    h('span', { id: conferenceNote, class: 'event-note' }, 'Auto-transcribe every session you attend')),
  track());

  const agenda = h('div', { class: 'calendar-agenda', 'aria-live': 'polite' });
  const dayButtons = DAYS.map((day, i) => h('button', {
    type: 'button', class: 'day-chip', 'aria-pressed': String(st.day === i),
    'aria-label': dateLabel(i),
    onClick: () => {
      st.day = i;
      dayButtons.forEach((button, index) => button.setAttribute('aria-pressed', String(index === i)));
      drawAgenda();
    },
  },
  h('span', { class: 'day-name' }, day.slice(0, 3)),
  h('span', { class: 'day-date' }, String(9 + i)),
  h('span', { class: `day-dot${i === 0 || i === 2 ? ' has-events' : ''}`, 'aria-hidden': 'true' })));

  function heading(text) {
    return h('h2', { class: 'eyebrow agenda-heading' }, text);
  }

  function eventCopy(title, note, titleId) {
    return h('div', { class: 'event-copy' },
      h('p', { class: 'event-title', id: titleId }, title),
      h('p', { class: 'event-note' }, note));
  }

  function eventTime(time, earlier = false) {
    return h('p', { class: `event-time tabular${earlier ? ' earlier-time' : ''}` }, time);
  }

  function captureEvent(event) {
    const titleId = nextId('calendar-event');
    const actionId = nextId('calendar-capture');
    const noteId = nextId('calendar-note');
    const noteText = () => `${event.location} · ${st[event.key] ? 'Auto-transcribe on' : 'Capture off'}`;
    const note = h('p', { class: 'event-note', id: noteId, 'aria-live': 'polite' }, noteText());
    const toggle = h('button', {
      type: 'button', class: 'capture-toggle', role: 'switch',
      'aria-checked': String(st[event.key]), 'aria-labelledby': `${actionId} ${titleId}`,
      'aria-describedby': noteId,
      onClick: () => {
        st[event.key] = !st[event.key];
        toggle.setAttribute('aria-checked', String(st[event.key]));
        note.textContent = noteText();
      },
    }, h('span', { class: 'visually-hidden', id: actionId }, 'Auto-transcribe'), track());
    return h('div', { class: 'event-row capture-row' },
      eventTime(event.time),
      h('div', { class: 'event-copy' }, h('p', { class: 'event-title', id: titleId }, event.title), note),
      toggle);
  }

  function drawAgenda() {
    const section = h('section', { class: 'day-agenda', 'aria-label': dateLabel(st.day) });
    if (st.day === 0) {
      section.append(
        heading('Earlier'),
        h('div', { class: 'event-card earlier-card' }, content.earlier.map((event) =>
          h('div', { class: 'event-row earlier-row' }, eventTime(event.time, true),
            eventCopy(event.title, event.note), icon('check', { size: 18, stroke: 2, label: 'Done' })))),
        heading('Now'),
        h('a', { class: 'live-event', href: '#/live' },
          eventTime('2:41 PM'), eventCopy(content.live, 'Picked up automatically'),
          h('span', { class: 'calendar-live-tag' },
            h('span', { class: 'calendar-live-dot', 'aria-hidden': 'true' }), 'LIVE')),
        heading('Later'),
        h('div', { class: 'event-card later-card' }, content.later.map(captureEvent)),
      );
    } else if (st.day === 2) {
      section.append(
        heading('Proposed by your agents'),
        h('a', { class: 'proposed-event', href: '#/match' },
          eventTime('10:00 AM'), eventCopy(`Coffee with ${ctx.peer.name}`, 'Both agents agreed · tap to confirm'),
          icon('chevron', { size: 18, stroke: 1.8 })),
      );
    } else {
      section.append(h('div', { class: 'calendar-empty' },
        h('p', { class: 'empty-title' }, 'Nothing scheduled'),
        h('p', { class: 'empty-note' }, 'Your agent can propose meetings into open slots')));
    }
    agenda.replaceChildren(section);
  }

  drawAgenda();

  return h('div', { class: 'screen calendar' },
    h('main', { class: 'scroll calendar-main' },
      h('header', { class: 'calendar-head' },
        h('div', { class: 'calendar-heading' },
          h('p', { class: 'eyebrow' }, 'November 2026'),
          h('h1', { class: 'serif calendar-title' }, 'Calendar')),
        // The reference's Add event control has no action in its logic block.
        h('button', { type: 'button', class: 'icon-btn calendar-add', 'aria-label': 'Add event' },
          icon('plus', { size: 20, stroke: 1.8 }))),
      conference,
      h('div', { class: 'week-strip', role: 'group', 'aria-label': 'Choose a day' }, dayButtons),
      agenda),
    bottomNav('calendar'));
}
