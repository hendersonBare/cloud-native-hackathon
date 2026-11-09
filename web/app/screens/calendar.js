// Calendar: week strip, the selected day's agenda, agent proposals, and the add-event and agenda sheets.
// All data comes from calendarClient(ctx): the live /api/calendar in live mode, an in-browser replica in mock
// mode. Every time shown is Denver time, and the screen says so ("All times MST").
import { h, icon, bottomNav, nextId } from '../ui.js';
import { openSheet, toast } from '../flow.js';
import { calendarClient, calendarErrorMessage } from '../calendar-api.js';
import {
  TIMEZONE, addDays, dayKey, formatRange, formatSlot, formatTime, localToUtc, longDay, noonOf, weekdayShort, zoneLabel,
} from '../time.js';

const POLL_MS = 15000; // live mode only: pick up changes made elsewhere
const CLOCK_MS = 30000; // re-sort Earlier / Now / Later as time passes
const DEBOUNCE_MS = 250;
const WEEK_DAYS = 7;
const DURATIONS = [
  { minutes: 15, label: '15 min' },
  { minutes: 30, label: '30 min' },
  { minutes: 45, label: '45 min' },
  { minutes: 60, label: '1 hour' },
  { minutes: 90, label: '1 hour 30 min' },
  { minutes: 120, label: '2 hours' },
];

const monthFormat = new Intl.DateTimeFormat('en-US', { timeZone: TIMEZONE, month: 'long', year: 'numeric' });
const monthDayFormat = new Intl.DateTimeFormat('en-US', { timeZone: TIMEZONE, month: 'short', day: 'numeric' });
const clockFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: TIMEZONE, hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const isoZ = (ms) => new Date(ms).toISOString().replace(/\.000Z$/, 'Z');
const dayNumber = (key) => String(Number(key.slice(8)));
const durationOf = (event) => Math.round((Date.parse(event.ends_at) - Date.parse(event.starts_at)) / 60000);

/** Earlier (ended), Now (running) or Later (not started) for an event at `now` (epoch ms). */
export function phaseOf(event, now) {
  if (Date.parse(event.ends_at) <= now) return 'earlier';
  if (Date.parse(event.starts_at) <= now) return 'now';
  return 'later';
}

/** The day the strip opens on: today when it is inside the view, else the first day. */
export function defaultDay(keys, start, now) {
  const today = dayKey(new Date(now));
  return keys.includes(today) ? today : start;
}

/** The Add sheet's start time: the next quarter hour today, otherwise 09:00. */
export function defaultStart(day, now) {
  if (day === dayKey(new Date(now))) {
    const [hh, mm] = clockFormat.format(new Date(now)).split(':').map(Number);
    const rounded = Math.ceil((hh * 60 + mm + 1) / 15) * 15;
    if (rounded < 24 * 60) return `${String(Math.floor(rounded / 60)).padStart(2, '0')}:${String(rounded % 60).padStart(2, '0')}`;
  }
  return '09:00';
}

/**
 * Check the Add event form. Returns { field, message } for the first problem, or { starts, ends } (epoch ms).
 * `weekStart` and `weekEnd` bound the days the calendar covers (epoch ms).
 */
export function validateAddForm({ title, day, start, minutes, weekStart, weekEnd }) {
  if (!String(title ?? '').trim()) return { field: 'title', message: 'Enter a title for the event.' };
  if (!/^\d{2}:\d{2}$/.test(start ?? '')) return { field: 'start', message: 'Choose a start time.' };
  const starts = Date.parse(localToUtc(day, start));
  const ends = starts + Number(minutes) * 60000;
  if (!(starts >= weekStart && ends <= weekEnd)) return { field: 'start', message: 'The event must fit inside this week.' };
  return { starts, ends };
}

/** Where focus goes when the control that had it is gone after a redraw, most specific first. */
export function focusFallbacks(key, day) {
  const keys = [key];
  if (typeof key === 'string' && key.endsWith(':accept')) keys.push(`${key.slice(0, -7)}:decline`);
  keys.push(`day:${day}`);
  return keys;
}

/**
 * Run an async action without awaiting it. The calendar's async functions report their own failures
 * (toast or error card); this only makes sure nothing is left unhandled, logging the error class only.
 */
function settle(promise, what) {
  return promise.catch((err) => console.warn(`Calendar ${what} failed`, err?.name || 'Error'));
}

/** `?add=1&with=<id>` -> what the add sheet opens with, or null when the link asks for nothing. */
export function addLinkPrefill(params = {}, personOf = () => null) {
  if (params.add !== '1') return null;
  const other = params.with ? personOf(params.with) : null;
  return { title: other?.name ? `Coffee with ${other.name}` : '' };
}

function overlapNote(count) {
  return count > 0 ? `Added · overlaps ${plural(count, 'event')}` : 'Event added';
}

function track() {
  return h('span', { class: 'capture-track', 'aria-hidden': 'true' }, h('span', { class: 'capture-knob' }));
}

/** The visible time plus a screen-reader range that always carries the zone. */
function eventTime(event, { earlier = false } = {}) {
  return h('p', { class: `event-time tabular${earlier ? ' earlier-time' : ''}` },
    h('span', { 'aria-hidden': 'true' }, formatTime(event.starts_at)),
    h('span', { class: 'visually-hidden' }, formatRange(event.starts_at, event.ends_at)));
}

function eventCopy(title, note, { titleId, noteId } = {}) {
  return h('div', { class: 'event-copy' },
    h('p', { class: 'event-title', id: titleId }, title),
    note ? h('p', { class: 'event-note', id: noteId }, note) : null);
}

function heading(text) {
  return h('h2', { class: 'eyebrow agenda-heading' }, text);
}

export function render(ctx) {
  const { me, bus } = ctx;
  const api = calendarClient(ctx);
  const st = ctx.store.calendar || (ctx.store.calendar = {});
  if (typeof st.day !== 'string') st.day = null;

  let alive = true;
  let seq = 0; // bumped by every load and every local change: older responses are dropped
  let model = null; // { view, skew } once the first load succeeds
  let lastSignature = '';
  let closeSheet = null;
  const pending = new Set(); // keys of calls in flight, so a double tap cannot send twice

  ctx.onCleanup(() => {
    alive = false;
    seq += 1;
    closeSheet?.();
  });

  const nowMs = () => Date.now() + (model?.skew || 0);

  // ---------------------------------------------------------------- static frame

  // Every time on this screen is Denver wall-clock time; the header says so (review rule: never a bare time).
  const monthLabel = (date) => `${monthFormat.format(date)} · All times ${zoneLabel(date)}`;
  const monthEl = h('p', { class: 'eyebrow' }, monthLabel(new Date()));
  const addButton = h('button', {
    type: 'button', class: 'icon-btn calendar-add', 'aria-label': 'Add event', disabled: true,
    onClick: () => openAddSheet(),
  }, icon('plus', { size: 20, stroke: 1.8 }));

  // Export sits in the header so the agenda button and conference mode share one row.
  const exportUrl = api.exportUrl?.(me.id);
  const exportLink = exportUrl
    ? h('a', {
      class: 'icon-btn calendar-export', href: exportUrl, download: `rapport-${me.id}.ics`, 'aria-label': 'Export .ics',
    }, icon('upload', { size: 20, stroke: 1.8 }))
    : null;

  // Shown only once the calendar has loaded (it needs the conference_mode flag).
  const conferenceSlot = h('div', { class: 'calendar-conference-slot', hidden: true });
  const actions = h('div', { class: 'calendar-actions' },
    h('button', {
      type: 'button', class: 'btn calendar-browse', 'aria-label': 'Browse agenda', onClick: () => openAgendaSheet(),
    }, icon('search', { size: 18, stroke: 1.8 }), 'Agenda'),
    conferenceSlot);

  const stateSlot = h('div', { class: 'calendar-state-slot' });
  const stripSlot = h('div', { class: 'calendar-strip-slot' });
  // The day agenda is rebuilt on every change, so it is not a live region: short messages go here instead.
  const statusEl = h('p', { class: 'visually-hidden', role: 'status', 'aria-live': 'polite', 'aria-atomic': 'true' });
  const agendaEl = h('div', { class: 'calendar-agenda' });
  const dataEl = h('div', { class: 'calendar-data', hidden: true }, stripSlot, agendaEl);

  const main = h('main', { class: 'scroll calendar-main', 'aria-busy': 'true' },
    statusEl,
    h('header', { class: 'calendar-head' },
      h('div', { class: 'calendar-heading' },
        monthEl,
        h('h1', { class: 'serif calendar-title' }, 'Calendar')),
      h('div', { class: 'calendar-head-actions' }, exportLink, addButton)),
    actions,
    stateSlot,
    dataEl);

  let errorShown = false;

  function announce(text) {
    statusEl.textContent = '';
    statusEl.textContent = text;
  }

  // ---------------------------------------------------------------- loading and error states

  function showLoading() {
    lastSignature = '';
    errorShown = false;
    main.setAttribute('aria-busy', 'true');
    dataEl.hidden = true;
    conferenceSlot.hidden = true;
    stateSlot.replaceChildren(h('div', { class: 'calendar-state', role: 'status', 'aria-live': 'polite' },
      h('span', { class: 'calendar-pulse rp-pulse', 'aria-hidden': 'true' }),
      h('p', { class: 'empty-note' }, 'Loading your calendar')));
  }

  function showError(error) {
    lastSignature = '';
    errorShown = true;
    main.setAttribute('aria-busy', 'false');
    dataEl.hidden = true;
    conferenceSlot.hidden = true;
    stateSlot.replaceChildren(h('div', { class: 'calendar-state calendar-error', role: 'alert' },
      h('p', { class: 'empty-title' }, 'Your calendar did not load'),
      h('p', { class: 'empty-note' }, error?.status === 404
        ? 'The calendar service is not available yet.'
        : calendarErrorMessage(error, 'load your calendar')),
      h('button', { type: 'button', class: 'btn btn-sm calendar-retry', onClick: () => settle(load(), 'load') }, 'Retry')));
  }

  // ---------------------------------------------------------------- data

  async function load({ silent = false } = {}) {
    seq += 1;
    const token = seq;
    // A background retry while the error card is up keeps the card (and focus on Retry) instead of flashing Loading.
    if (!silent) showLoading();
    try {
      const view = await api.view(me.id);
      if (!alive || token !== seq) return;
      model = { view, skew: Date.parse(view.now) - Date.now() };
      addButton.disabled = false;
      draw();
      openDeepLinkedSheet();
    } catch (error) {
      if (!alive || token !== seq) return;
      if (!model) { if (!errorShown) showError(error); } // with data on screen a failed refresh keeps the last good view
      else if (!silent) toast(calendarErrorMessage(error, 'refresh your calendar'), { tone: 'error' });
    }
  }

  function dayKeys() {
    const { start, days } = model.view;
    return Array.from({ length: Math.min(days, WEEK_DAYS) }, (_, i) => addDays(start, i));
  }

  function selectedDay() {
    const keys = dayKeys();
    if (!st.day || !keys.includes(st.day)) {
      st.day = defaultDay(keys, model.view.start, nowMs());
    }
    return st.day;
  }

  function visibleEvents() {
    return model.view.events.filter((event) => event.status !== 'declined');
  }

  /** Cheap fingerprint of everything that changes the picture, so unchanged polls do not re-announce. */
  function signature() {
    const now = nowMs();
    const events = visibleEvents();
    return JSON.stringify([selectedDay(), model.view.start, model.view.conference_mode, dayKey(new Date(now)),
      events, events.map((event) => phaseOf(event, now))]);
  }

  function draw({ force = false, focus = null } = {}) {
    if (!model) return;
    const next = signature();
    if (!force && next === lastSignature && !focus) return;
    lastSignature = next;
    const active = document.activeElement;
    const focusKey = focus || (main.contains(active) ? active.dataset?.focusKey : null);

    stateSlot.replaceChildren();
    errorShown = false;
    dataEl.hidden = false;
    main.setAttribute('aria-busy', 'false');
    const day = selectedDay();
    monthEl.textContent = monthLabel(noonOf(day));
    conferenceSlot.replaceChildren(conferenceSwitch());
    conferenceSlot.hidden = false;
    stripSlot.replaceChildren(weekStrip(day));
    agendaEl.replaceChildren(dayAgenda(day));

    if (focusKey) {
      const targets = [...main.querySelectorAll('[data-focus-key]')];
      for (const key of focusFallbacks(focusKey, day)) {
        const target = targets.find((el) => el.dataset.focusKey === key);
        if (target) {
          target.focus({ preventScroll: true });
          break;
        }
      }
    }
  }

  // ---------------------------------------------------------------- conference mode

  function conferenceSwitch() {
    const on = model.view.conference_mode === true;
    const titleId = nextId('calendar-conference');
    const noteId = nextId('calendar-conference-note');
    return h('button', {
      type: 'button', class: 'conference-mode', role: 'switch', 'aria-checked': String(on),
      'aria-labelledby': titleId, 'aria-describedby': noteId, dataset: { focusKey: 'conference' },
      onClick: toggleConference,
    },
    h('span', { class: 'event-copy' },
      h('span', { id: titleId, class: 'event-title' }, 'Conference mode'),
      h('span', { id: noteId, class: 'event-note' },
        on ? 'Auto-transcribes KubeCon talks' : 'KubeCon talks are not transcribed')),
    track());
  }

  async function toggleConference() {
    if (pending.has('conference')) return;
    pending.add('conference');
    const previous = model.view.conference_mode === true;
    seq += 1;
    model.view.conference_mode = !previous;
    draw({ force: true });
    announce(`Conference mode ${previous ? 'off' : 'on'}`);
    try {
      await api.setConferenceMode({ persona_id: me.id, enabled: !previous });
    } catch (error) {
      if (alive) {
        model.view.conference_mode = previous;
        draw({ force: true });
        announce(`Conference mode ${previous ? 'on' : 'off'}`);
        toast(calendarErrorMessage(error, 'change conference mode'), { tone: 'error' });
      }
    } finally {
      pending.delete('conference');
    }
  }

  // ---------------------------------------------------------------- week strip

  function weekStrip(selected) {
    const counts = {};
    for (const event of visibleEvents()) {
      const key = dayKey(event.starts_at);
      counts[key] = (counts[key] || 0) + 1;
    }
    return h('div', { class: 'week-strip', role: 'group', 'aria-label': 'Choose a day' },
      dayKeys().map((key) => {
        const count = counts[key] || 0;
        const noon = noonOf(key);
        return h('button', {
          type: 'button', class: 'day-chip', 'aria-pressed': String(key === selected),
          'aria-label': `${longDay(noon)}, ${count ? plural(count, 'event') : 'no events'}`,
          dataset: { focusKey: `day:${key}` },
          onClick: () => {
            st.day = key;
            draw({ force: true });
            announce(`Showing ${longDay(noon)}`);
          },
        },
        h('span', { class: 'day-name' }, weekdayShort(noon)),
        h('span', { class: 'day-date' }, dayNumber(key)),
        h('span', { class: `day-dot${count ? ' has-events' : ''}`, 'aria-hidden': 'true' }));
      }));
  }

  // ---------------------------------------------------------------- the selected day

  function dayAgenda(day) {
    const now = nowMs();
    const today = dayKey(new Date(now));
    const onDay = visibleEvents().filter((event) => dayKey(event.starts_at) === day);
    const proposed = onDay.filter((event) => event.status === 'proposed');
    const regular = onDay.filter((event) => event.status !== 'proposed');
    const section = h('section', { class: 'day-agenda', 'aria-label': longDay(noonOf(day)) });
    let shown = false;

    if (proposed.length) {
      shown = true;
      section.append(heading('Proposed by your agents'), h('div', { class: 'proposed-list' }, proposed.map(proposedCard)));
    }

    if (day === today) {
      const earlier = regular.filter((event) => phaseOf(event, now) === 'earlier');
      const current = regular.filter((event) => phaseOf(event, now) === 'now');
      const later = regular.filter((event) => phaseOf(event, now) === 'later');
      if (earlier.length) {
        shown = true;
        section.append(heading('Earlier'), h('div', { class: 'event-card earlier-card' }, earlier.map(earlierRow)));
      }
      if (current.length) {
        shown = true;
        section.append(heading('Now'), h('div', { class: 'event-card later-card now-card' }, current.map(eventRow)));
      } else if (model.view.conference_mode) {
        shown = true;
        section.append(heading('Now'), liveCard(now));
      }
      if (later.length) {
        shown = true;
        section.append(heading('Later'), h('div', { class: 'event-card later-card' }, later.map(eventRow)));
      }
    } else if (regular.length) {
      shown = true;
      section.append(heading('Scheduled'), h('div', { class: 'event-card later-card' }, regular.map(eventRow)));
    }

    if (!shown) {
      section.append(h('div', { class: 'calendar-empty' },
        h('p', { class: 'empty-title' }, 'Nothing scheduled'),
        h('p', { class: 'empty-note' }, 'Your agent can propose meetings into open slots')));
    }
    return section;
  }

  function liveCard(now) {
    const title = ctx.view?.home?.live?.title || 'Live conversation';
    return h('a', { class: 'live-event', href: '#/live' },
      h('p', { class: 'event-time tabular' },
        h('span', { 'aria-hidden': 'true' }, formatTime(now)),
        h('span', { class: 'visually-hidden' }, `${formatSlot(now)} now`)),
      eventCopy(title, 'Picked up automatically'),
      h('span', { class: 'calendar-live-tag' },
        h('span', { class: 'calendar-live-dot', 'aria-hidden': 'true' }), 'LIVE'));
  }

  function earlierRow(event) {
    const note = [event.location, event.capture ? 'Auto-transcribe was on' : null].filter(Boolean).join(' · ');
    return h('div', { class: 'event-row earlier-row' },
      eventTime(event, { earlier: true }),
      eventCopy(event.title, note),
      icon('check', { size: 18, stroke: 2, label: 'Done' }));
  }

  const noteFor = (event) => [event.location, `${durationOf(event)} min`, event.capture ? 'Auto-transcribe on' : 'Capture off']
    .filter(Boolean).join(' · ');

  /** A scheduled event: time, copy, the Auto-transcribe switch, and Remove for events the person added. */
  function eventRow(event) {
    const titleId = nextId('calendar-event');
    const actionId = nextId('calendar-capture');
    const noteId = nextId('calendar-note');
    const removable = event.source === 'user' || event.source === 'conference';
    const toggle = h('button', {
      type: 'button', class: 'capture-toggle', role: 'switch', 'aria-checked': String(event.capture === true),
      'aria-labelledby': `${actionId} ${titleId}`, 'aria-describedby': noteId,
      dataset: { focusKey: `${event.event_id}:capture` },
      onClick: () => toggleCapture(event),
    }, h('span', { class: 'visually-hidden', id: actionId }, 'Auto-transcribe'), track());
    return h('div', { class: 'event-row capture-row' },
      eventTime(event),
      eventCopy(event.title, noteFor(event), { titleId, noteId }),
      toggle,
      removable
        ? h('button', {
          type: 'button', class: 'event-remove', 'aria-label': `Remove ${event.title}`,
          dataset: { focusKey: `${event.event_id}:remove` }, onClick: () => removeEvent(event),
        }, icon('close', { size: 18, stroke: 1.8 }))
        : null);
  }

  async function toggleCapture(event) {
    const key = `capture:${event.event_id}`;
    if (pending.has(key)) return;
    pending.add(key);
    const previous = event.capture === true;
    seq += 1;
    event.capture = !previous;
    draw({ force: true });
    announce(`Auto-transcribe ${previous ? 'off' : 'on'} for ${event.title}`);
    try {
      await api.update(event.event_id, { persona_id: me.id, capture: !previous });
    } catch (error) {
      if (alive) {
        event.capture = previous;
        draw({ force: true });
        announce(`Auto-transcribe ${previous ? 'on' : 'off'} for ${event.title}`);
        toast(calendarErrorMessage(error, 'change auto-transcribe'), { tone: 'error' });
      }
    } finally {
      pending.delete(key);
    }
  }

  async function removeEvent(event) {
    const key = `remove:${event.event_id}`;
    if (pending.has(key)) return;
    pending.add(key);
    try {
      await api.remove(event.event_id, me.id);
      if (!alive) return;
      seq += 1;
      model.view.events = model.view.events.filter((e) => e.event_id !== event.event_id);
      draw({ force: true, focus: `day:${selectedDay()}` });
      toast('Event removed');
    } catch (error) {
      if (alive) toast(calendarErrorMessage(error, 'remove the event'), { tone: 'error' });
    } finally {
      pending.delete(key);
    }
  }

  // ---------------------------------------------------------------- proposals

  function proposedCard(event) {
    const titleId = nextId('calendar-proposed');
    const isMeeting = event.kind === 'meeting';
    const iAccepted = event.responses?.[me.id] === 'accepted';
    const withPeer = event.with_persona_ids?.includes(ctx.peer?.id);
    const place = [event.location, `${durationOf(event)} min`].filter(Boolean).join(' · ');
    return h('article', { class: 'proposed-card', 'aria-labelledby': titleId },
      h('div', { class: 'proposed-top' },
        eventTime(event),
        h('div', { class: 'event-copy' },
          h('p', { class: 'event-title', id: titleId }, event.title),
          h('p', { class: 'event-note' }, place),
          event.note ? h('p', { class: 'event-note' }, event.note) : null)),
      isMeeting
        ? h('div', { class: 'proposed-actions' },
          iAccepted
            ? h('p', { class: 'proposed-state' }, icon('check', { size: 16, stroke: 2 }), 'You accepted')
            : h('button', {
              type: 'button', class: 'btn btn-primary btn-sm', 'aria-label': `Accept ${event.title}`,
              dataset: { focusKey: `${event.event_id}:accept` }, onClick: () => respond(event, 'accept'),
            }, 'Accept'),
          h('button', {
            type: 'button', class: 'btn btn-sm', 'aria-label': `Decline ${event.title}`,
            dataset: { focusKey: `${event.event_id}:decline` }, onClick: () => respond(event, 'decline'),
          }, 'Decline'))
        : null,
      withPeer
        ? h('a', { class: 'proposed-link', href: '#/match' }, 'See why you matched', icon('chevron', { size: 16, stroke: 1.8 }))
        : null);
  }

  async function respond(event, response) {
    const key = `respond:${event.event_id}`;
    if (pending.has(key)) return;
    pending.add(key);
    seq += 1;
    const card = [...agendaEl.querySelectorAll('.proposed-card button')]
      .filter((button) => button.dataset.focusKey?.startsWith(`${event.event_id}:`));
    // aria-disabled, not disabled: the focused button must stay focusable until the redraw moves focus on.
    for (const button of card) button.setAttribute('aria-disabled', 'true');
    try {
      const updated = await api.respond(event.event_id, { persona_id: me.id, response });
      if (!alive) return;
      toast(response === 'decline' ? 'Declined' : updated?.status === 'confirmed'
        ? `Confirmed · ${event.title}` : 'Accepted · waiting for the other person');
    } catch (error) {
      if (alive) {
        for (const button of card) button.removeAttribute('aria-disabled');
        toast(calendarErrorMessage(error, 'send your answer'), { tone: 'error' });
      }
    } finally {
      pending.delete(key);
    }
  }

  // ---------------------------------------------------------------- add event sheet

  // Home's "+" links to #/calendar?add=1&with=<persona_id>: open the sheet once, prefilled, then drop
  // the query (replaceState fires no hashchange) so a refetch or Back does not reopen it.
  let deepLinkHandled = false;
  function openDeepLinkedSheet() {
    if (deepLinkHandled || !alive) return;
    deepLinkHandled = true;
    const prefill = addLinkPrefill(ctx.route.params, ctx.person);
    if (!prefill) return;
    try { history.replaceState(null, '', '#/calendar'); } catch { /* sandboxed frame: harmless */ }
    openAddSheet(prefill);
  }

  function openAddSheet({ title = '' } = {}) {
    if (!model) return;
    const keys = dayKeys();
    const selected = selectedDay();
    const weekEnd = Date.parse(localToUtc(addDays(keys[keys.length - 1], 1), '00:00'));
    const weekStart = Date.parse(localToUtc(keys[0], '00:00'));
    const id = {
      title: nextId('add-title'), day: nextId('add-day'), start: nextId('add-start'),
      duration: nextId('add-duration'), place: nextId('add-location'), error: nextId('add-error'),
    };
    let busy = false;
    let flagged = null;

    const message = h('p', { id: id.error, class: 'cal-form-error', role: 'alert' });
    const titleInput = h('input', {
      id: id.title, class: 'cal-input', type: 'text', name: 'title', required: true, maxlength: 120,
      autocomplete: 'off', enterkeyhint: 'next', value: title,
    });
    const daySelect = h('select', { id: id.day, class: 'cal-input', name: 'day' },
      keys.map((key) => h('option', { value: key, selected: key === selected },
        `${weekdayShort(noonOf(key))}, ${monthDayFormat.format(noonOf(key))}`)));
    const startInput = h('input', {
      id: id.start, class: 'cal-input', type: 'time', name: 'start', required: true, step: 900,
      value: defaultStart(selected, nowMs()),
    });
    const durationSelect = h('select', { id: id.duration, class: 'cal-input', name: 'duration' },
      DURATIONS.map((d) => h('option', { value: d.minutes, selected: d.minutes === 30 }, d.label)));
    const placeInput = h('input', {
      id: id.place, class: 'cal-input', type: 'text', name: 'location', maxlength: 80, autocomplete: 'off',
    });

    function clearFlag() {
      if (!flagged) return;
      flagged.removeAttribute('aria-invalid');
      flagged.removeAttribute('aria-describedby');
      flagged = null;
      message.textContent = '';
    }
    function flag(field, text) {
      clearFlag();
      flagged = field;
      field.setAttribute('aria-invalid', 'true');
      field.setAttribute('aria-describedby', id.error);
      message.textContent = text;
      field.focus();
    }
    for (const field of [titleInput, startInput, daySelect, durationSelect]) field.addEventListener('input', clearFlag);

    const submit = h('button', { type: 'submit', class: 'btn btn-primary' }, 'Add event');
    const cancel = h('button', { type: 'button', class: 'btn', onClick: () => closeSheet?.() }, 'Cancel');
    const labelled = (forId, text, control, hint) => h('div', { class: 'cal-field' },
      h('label', { class: 'cal-label', for: forId }, text, hint ? h('span', { class: 'cal-hint' }, ` ${hint}`) : null),
      control);

    async function onSubmit(event) {
      event.preventDefault();
      if (busy) return;
      const title = titleInput.value.trim();
      const checked = validateAddForm({
        title, day: daySelect.value, start: startInput.value, minutes: durationSelect.value, weekStart, weekEnd,
      });
      if (checked.field) return flag(checked.field === 'title' ? titleInput : startInput, checked.message);
      const { starts, ends } = checked;
      clearFlag();
      busy = true;
      submit.disabled = true;
      submit.setAttribute('aria-busy', 'true');
      try {
        const { conflicts = [] } = await api.create({
          persona_id: me.id, title, starts_at: isoZ(starts), ends_at: isoZ(ends), location: placeInput.value.trim(),
        });
        if (!alive) return;
        st.day = daySelect.value;
        draw({ force: true });
        closeSheet?.();
        toast(overlapNote(conflicts.length));
      } catch (error) {
        if (!alive) return;
        message.textContent = calendarErrorMessage(error, 'add the event');
        busy = false;
        submit.disabled = false;
        submit.removeAttribute('aria-busy');
      }
    }

    const form = h('form', { class: 'cal-form', novalidate: true, onSubmit },
      h('h2', { class: 'serif cal-sheet-title' }, 'Add event'),
      h('p', { class: 'cal-sheet-note' }, `All times ${zoneLabel(new Date(nowMs()))}`),
      labelled(id.title, 'Title', titleInput),
      labelled(id.day, 'Day', daySelect),
      h('div', { class: 'cal-field-row' },
        labelled(id.start, 'Start', startInput),
        labelled(id.duration, 'Duration', durationSelect)),
      labelled(id.place, 'Location', placeInput, '(optional)'),
      message,
      h('div', { class: 'cal-actions' }, cancel, submit));

    closeSheet = openSheet(h('div', { class: 'cal-sheet' }, form), {
      label: 'Add event',
      onClose: () => { closeSheet = null; },
    });
  }

  // ---------------------------------------------------------------- browse agenda sheet

  function openAgendaSheet() {
    let token = 0;
    let timer = null;
    let closed = false;
    let query = '';
    let result = null; // { items, source }
    let failure = null;
    let loading = true;
    let restoreFocus = null; // data-focus-key to focus once the list is drawn again

    const searchId = nextId('agenda-search');
    const input = h('input', {
      id: searchId, class: 'cal-input', type: 'search', name: 'q', maxlength: 100, autocomplete: 'off',
      placeholder: 'Search talks, tracks, speakers',
    });
    const badge = h('span', { class: 'badge agenda-offline', hidden: true }, 'Offline agenda');
    const list = h('div', { class: 'agenda-results', 'aria-live': 'polite' });

    function addNote(item) {
      return [item.talk.room, item.talk.track].filter(Boolean).join(' · ');
    }

    function drawResults() {
      badge.hidden = !(ctx.mode === 'live' && result?.source === 'seed');
      list.setAttribute('aria-busy', String(loading));
      if (failure) {
        list.replaceChildren(h('div', { class: 'agenda-state', role: 'alert' },
          h('p', { class: 'empty-note' }, calendarErrorMessage(failure, 'load the agenda')),
          h('button', { type: 'button', class: 'btn btn-sm', onClick: () => settle(run(query), 'agenda search') }, 'Retry')));
        return;
      }
      if (!result) {
        list.replaceChildren(h('p', { class: 'empty-note agenda-state' }, 'Loading the agenda'));
        return;
      }
      if (!result.items.length) {
        list.replaceChildren(h('p', { class: 'empty-note agenda-state' }, 'No talks match that search.'));
        restoreFocus = null;
        return;
      }
      list.replaceChildren(h('ul', { class: 'agenda-list' }, result.items.map(agendaItem)));
      if (restoreFocus) {
        [...list.querySelectorAll('[data-focus-key]')].find((el) => el.dataset.focusKey === restoreFocus)?.focus({ preventScroll: true });
        restoreFocus = null;
      }
    }

    function agendaItem(item) {
      const titleId = nextId('agenda-talk');
      const added = item.in_calendar === true;
      return h('li', { class: 'agenda-item' },
        h('div', { class: 'event-copy' },
          h('p', { class: 'agenda-time tabular' }, formatSlot(item.talk.starts_at)),
          h('p', { class: 'event-title', id: titleId }, item.talk.title),
          h('p', { class: 'event-note' }, addNote(item))),
        h('button', {
          type: 'button', class: `btn btn-sm agenda-add${added ? ' is-added' : ''}`, 'aria-disabled': added ? 'true' : null,
          'aria-label': added ? `${item.talk.title} is on your calendar` : `Add ${item.talk.title} to your calendar`,
          dataset: { focusKey: `talk:${item.talk.talk_id}` },
          onClick: () => { if (!added) settle(addTalk(item), 'add talk'); },
        }, added ? icon('check', { size: 16, stroke: 2 }) : null, added ? 'Added' : 'Add'));
    }

    async function run(q) {
      token += 1;
      const mine = token;
      query = q;
      loading = true;
      failure = null;
      drawResults();
      try {
        const agenda = await api.agenda(me.id, q);
        if (closed || !alive || mine !== token) return;
        result = { items: agenda.items || [], source: agenda.source };
      } catch (error) {
        if (closed || !alive || mine !== token) return;
        failure = error;
        restoreFocus = null;
      }
      loading = false;
      drawResults();
    }

    async function addTalk(item) {
      const key = `talk:${item.talk.talk_id}`;
      if (pending.has(key)) return;
      pending.add(key);
      const button = [...list.querySelectorAll('.agenda-add')].find((b) => b.dataset.focusKey === key);
      // aria-disabled keeps focus on the button while the call runs and after the list is redrawn.
      button?.setAttribute('aria-disabled', 'true');
      restoreFocus = list.contains(document.activeElement) ? key : null;
      try {
        const { conflicts = [] } = await api.addTalk({ persona_id: me.id, talk_id: item.talk.talk_id });
        if (closed || !alive) return;
        item.in_calendar = true;
        drawResults();
        toast(overlapNote(conflicts.length));
      } catch (error) {
        if (closed || !alive) return;
        if (error?.status === 409) {
          await run(query); // a duplicate shows as Added; anything else (a full calendar) is reported
          if (closed || !alive) return;
          const fresh = result?.items.find((i) => i.talk.talk_id === item.talk.talk_id);
          toast(fresh?.in_calendar ? 'Already on your calendar' : calendarErrorMessage(error, 'add the talk'),
            fresh?.in_calendar ? {} : { tone: 'error' });
        } else {
          button?.removeAttribute('aria-disabled');
          restoreFocus = null;
          toast(calendarErrorMessage(error, 'add the talk'), { tone: 'error' });
        }
      } finally {
        pending.delete(key);
      }
    }

    input.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => settle(run(input.value.trim()), 'agenda search'), DEBOUNCE_MS);
    });

    const content = h('div', { class: 'cal-sheet' },
      h('h2', { class: 'serif cal-sheet-title' }, 'Conference agenda'),
      h('p', { class: 'cal-sheet-note' }, `All times ${zoneLabel(new Date(nowMs()))}`, badge),
      h('div', { class: 'cal-field' },
        h('label', { class: 'cal-label', for: searchId }, 'Search the agenda'),
        input),
      list,
      h('div', { class: 'cal-actions cal-actions-single' },
        h('button', { type: 'button', class: 'btn', onClick: () => closeSheet?.() }, 'Done')));

    closeSheet = openSheet(content, {
      label: 'Conference agenda',
      onClose: () => {
        closed = true;
        clearTimeout(timer);
        closeSheet = null;
      },
    });
    settle(run(''), 'agenda search');
  }

  // ---------------------------------------------------------------- refresh

  ctx.onCleanup(bus.on('calendar:changed', (data) => {
    if (!data?.persona_ids || data.persona_ids.includes(me.id)) settle(load({ silent: true }), 'refresh');
  }));
  const clock = setInterval(() => draw(), CLOCK_MS);
  ctx.onCleanup(() => clearInterval(clock));
  if (ctx.mode === 'live') {
    const poll = setInterval(() => settle(load({ silent: true }), 'refresh'), POLL_MS);
    ctx.onCleanup(() => clearInterval(poll));
  }

  settle(load(), 'load');

  return h('div', { class: 'screen calendar' }, main, bottomNav('calendar'));
}
