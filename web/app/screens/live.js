// Live capture: diarized hallway conversation and saved conference session.
// The hallway conversation plays CONTENT below until someone taps the mic; from then on it shows
// what the browser's speech recognition hears (speech.js), the speaker being whose phone's mic is on.
import { h, icon, svg, topbar, bottomNav } from '../ui.js';
import { hashFor } from '../route.js';
import { formatTime } from '../time.js';
import { emptyCapture } from '../capture-model.js';

export const CONTENT = {
  'acme.ava': {
    lines: [
      ['s2', 'We’re migrating our hospital platform. Tracing has to work without code changes.'],
      ['you', 'Acme uses zero-code eBPF tracing and exports to OpenTelemetry.'],
      ['s2', 'Observability cost is our biggest concern. We’re comparing another vendor too.'],
      ['you', 'A hospital rollout cut incident time by 40%. We can walk through the approach.'],
      ['s2', 'Kai, our Security Architect, needs to review HIPAA before a pilot.'],
      ['you', 'Sam promised Kai the security questionnaire. I’ll follow up with him.'],
      ['s2', 'Great. Let’s compare the tracing costs and plan a small pilot.'],
    ],
    session: [
      ['kestrel.mia', 'Moderator', 'How does zero-code tracing help a hospital platform migration?'],
      ['acme.ava', '', 'eBPF captures traces without changing application code; OpenTelemetry carries them onward.'],
      ['bluefin.kai', '', 'Review telemetry data for HIPAA, and measure observability cost before expanding a pilot.'],
    ],
  },
  // The same conversation as Ava's, seen from Bo's side, so two presenters can read one script
  // and both phones show the same words.
  'bluefin.bo': {
    lines: [
      ['you', 'We’re migrating our hospital platform. Tracing has to work without code changes.'],
      ['s2', 'Acme uses zero-code eBPF tracing and exports to OpenTelemetry.'],
      ['you', 'Observability cost is our biggest concern. We’re comparing another vendor too.'],
      ['s2', 'A hospital rollout cut incident time by 40%. We can walk through the approach.'],
      ['you', 'Kai, our Security Architect, needs to review HIPAA before a pilot.'],
      ['s2', 'Sam promised Kai the security questionnaire. I’ll follow up with him.'],
      ['you', 'Great. Let’s compare the tracing costs and plan a small pilot.'],
    ],
    session: [
      ['kestrel.mia', 'Moderator', 'How can teams trace a migration without changing every service?'],
      ['acme.ava', '', 'Zero-code eBPF tracing feeds an OpenTelemetry pipeline with no application changes.'],
      ['bluefin.kai', '', 'For a hospital rollout, review HIPAA and observability cost before expanding.'],
    ],
  },
};

function elapsed(start) {
  const seconds = Math.max(0, Math.floor((Date.now() - start) / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

export function render(ctx) {
  const { store, peer } = ctx;
  const content = CONTENT[ctx.me.id] || CONTENT['acme.ava'];
  const st = store.live || (store.live = {});
  if (st.mode !== 'session') st.mode = 'conversation';
  const initialCount = content.lines.length - 3;
  if (!Number.isInteger(st.revealed)) st.revealed = initialCount;
  st.revealed = Math.max(initialCount, Math.min(content.lines.length, st.revealed));
  if (store.liveStart == null) store.liveStart = Date.now() - 252000;
  if (!store.speakers) store.speakers = {};
  if (!store.speakers.s2) {
    store.speakers.s2 = { name: peer.name, personaId: peer.id, edited: false };
  }
  // Real speech (speech.js). Without speech recognition in this browser, the script plays as before.
  const speech = store.speech?.supported ? store.speech : null;
  const cap = store.capture || (store.capture = emptyCapture());

  const pillText = h('span');
  const pill = h('span', { class: 'capture-pill' },
    h('span', { class: 'capture-dot', 'aria-hidden': 'true' }), pillText);
  const conversationButton = h('button', {
    type: 'button', onClick: () => pickMode('conversation'),
  }, 'Conversation');
  const sessionButton = h('button', {
    type: 'button', onClick: () => pickMode('session'),
  }, 'Conference session');
  const modes = h('div', { class: 'capture-modes', role: 'group', 'aria-label': 'What is being captured' },
    conversationButton, sessionButton);
  const main = h('main', { class: 'scroll capture-main' });
  const footer = h('div', { class: 'capture-footer' });
  const log = h('section', {
    class: 'transcript', role: 'log', 'aria-label': 'Hallway conversation transcript',
    'aria-live': 'polite', 'aria-relevant': 'additions', lang: 'en',
  });
  let speaking = null;
  let cursor = null;
  let activeTime = null;
  let drawn = 0;

  function transcriptLine({ name, initials, tone, text, time, editable = false, tag, role }) {
    const label = editable
      ? h('a', { class: 'speaker-link', href: '#/tag', 'aria-label': `Change speaker: ${name}` },
        name, icon('edit', { size: 13, stroke: 2 }))
      : h('span', { class: 'speaker-name' }, name);
    return h('article', { class: `transcript-line${editable ? ' is-peer' : ''}` },
      h('span', { class: `speaker-avatar tone-${tone}`, 'aria-hidden': 'true' }, initials),
      h('div', { class: 'transcript-body' },
        h('div', { class: 'speaker-row' }, label,
          tag ? h('span', { class: 'speaker-tag' }, tag) : null,
          role ? h('span', { class: 'speaker-role' }, role) : null,
          h('span', { class: 'transcript-time' }, time)),
        h('p', { class: 'transcript-text' }, text)));
  }

  function speakerFor(isPeer) {
    const speaker = store.speakers.s2;
    const identity = ctx.person(speaker.personaId);
    return {
      name: isPeer ? speaker.name : 'You',
      initials: isPeer ? (identity?.initials || speaker.name.slice(0, 2).toUpperCase()) : 'You',
      tone: isPeer ? (identity?.tone || 'steel') : 'gold',
      editable: isPeer, tag: isPeer ? (speaker.edited ? 'Edited' : 'Auto') : null,
    };
  }

  // Real speech: every line from cap.lines, plus the phrase being spoken right now.
  function drawLive() {
    const rows = cap.lines.map((line) =>
      transcriptLine({ ...speakerFor(line.from !== ctx.me.id), text: line.text, time: formatTime(line.start) }));
    if (cap.interim) {
      const row = transcriptLine({ ...speakerFor(cap.interim.from !== ctx.me.id), text: cap.interim.text, time: '' });
      row.querySelector('.speaker-row').append(h('span', { class: 'speaking' },
        h('span', { class: 'capture-dot', 'aria-hidden': 'true' }), 'Speaking'));
      row.querySelector('.transcript-text').append(h('span', { class: 'transcript-cursor rp-pulse', 'aria-hidden': 'true' }));
      rows.push(row);
    }
    if (!rows.length) {
      rows.push(h('p', { class: 'transcript-empty' },
        cap.listening ? 'Listening… start talking.' : 'Tap the microphone, then start talking.'));
    }
    log.replaceChildren(...rows);
  }

  function appendLines() {
    if (cap.live) { drawLive(); return; }
    speaking?.remove();
    cursor?.remove();
    if (activeTime) activeTime.hidden = false;
    while (drawn < st.revealed) {
      const [who, text] = content.lines[drawn];
      const isPeer = who === 's2';
      const speaker = store.speakers.s2;
      const identity = ctx.person(speaker.personaId);
      log.append(transcriptLine({
        name: isPeer ? speaker.name : 'You',
        initials: isPeer ? (identity?.initials || speaker.name.slice(0, 2).toUpperCase()) : 'You',
        tone: isPeer ? (identity?.tone || 'steel') : 'gold',
        text, time: `2:${String(41 + Math.floor(drawn / 2)).padStart(2, '0')} PM`,
        editable: isPeer, tag: isPeer ? (speaker.edited ? 'Edited' : 'Auto') : null,
      }));
      drawn += 1;
    }
    if (!st.paused && st.revealed < content.lines.length) {
      speaking = h('span', { class: 'speaking' },
        h('span', { class: 'capture-dot', 'aria-hidden': 'true' }), 'Speaking');
      cursor = h('span', { class: 'transcript-cursor rp-pulse', 'aria-hidden': 'true' });
      activeTime = log.lastElementChild.querySelector('.transcript-time');
      activeTime.hidden = true;
      log.lastElementChild.querySelector('.speaker-row').append(speaking);
      log.lastElementChild.querySelector('.transcript-text').append(cursor);
    }
  }

  function tickClock() {
    const saved = st.mode === 'session';
    pill.classList.toggle('is-saved', saved);
    const recording = cap.live ? !!cap.listening : !st.paused;
    pillText.textContent = saved ? 'SAVED' : `${recording ? 'REC' : 'PAUSED'} ${elapsed(store.liveStart)}`;
  }

  function micStatus() {
    if (cap.error === 'blocked') return 'Microphone blocked: allow it in the address bar, then tap the mic';
    if (cap.error === 'no-mic') return 'No microphone found';
    if (cap.error) return 'Speech recognition stopped: tap the mic to try again';
    if (cap.listening === ctx.me.id) return 'Listening to you · live transcript';
    if (cap.listening) return `Listening to ${ctx.person(cap.listening)?.name || 'the other phone'} on their phone`;
    return cap.live ? 'Mic off · tap it when you speak' : 'Tap the mic to transcribe what you say';
  }

  let footerKey = null;
  function drawFooter() {
    const saved = st.mode === 'session';
    footerKey = [st.mode, st.paused, cap.live, cap.listening, cap.error].join('|');
    // The design shows no status line while the script records; it stays as a screen-reader live region.
    // With a microphone the status is shown, so the speakers can see whose mic is on.
    const status = h('p', {
      class: saved || speech ? 'capture-status' : 'capture-status visually-hidden', role: 'status', 'aria-live': 'polite',
    },
    icon(speech && !saved ? 'mic' : 'memory', { size: 14, stroke: 1.8 }),
    saved ? 'Saved · speakers matched to the program'
      : speech ? micStatus()
        : st.paused ? 'Capture paused · Personal memory' : 'Streaming to your Personal memory');
    if (saved) {
      footer.replaceChildren(status,
        h('a', { class: 'session-ask', href: '#/memory' }, 'Ask about this session'));
      return;
    }
    const pause = h('button', {
      type: 'button', class: 'capture-round', 'aria-label': st.paused ? 'Resume capture' : 'Pause capture',
      'aria-pressed': String(!!st.paused),
      onClick: () => {
        st.paused = !st.paused;
        appendLines(); tickClock(); drawFooter();
        footer.querySelector('button').focus({ preventScroll: true });
      },
    }, st.paused
      ? svg([['path', { d: 'm9 5 10 7-10 7z' }]], { size: 18, stroke: 2 })
      : svg([['path', { d: 'M9 5v14M15 5v14' }]], { size: 18, stroke: 2 }));
    // With speech recognition the round button is the mic: whoever's mic is on is the speaker.
    const micOn = cap.listening === ctx.me.id;
    const mic = speech && h('button', {
      type: 'button', class: `capture-round capture-mic${micOn ? ' is-on' : ''}`,
      'aria-label': micOn ? 'Stop listening' : 'Listen and transcribe as you talk', 'aria-pressed': String(micOn),
      onClick: () => { if (speech.isOn()) speech.stop(); else speech.start(); },
    }, icon('mic', { size: 20, stroke: 1.8 }));
    const mark = h('button', {
      type: 'button', class: 'capture-mark',
      onClick: () => {
        if (!st.moments) st.moments = [];
        st.moments.push({ elapsed: Date.now() - store.liveStart, line: cap.live ? cap.lines.length : st.revealed });
        status.replaceChildren(icon('check', { size: 14 }), `Moment marked at ${elapsed(store.liveStart)}`);
      },
    }, svg([['path', { d: 'M6 3h12v18l-6-4-6 4z' }]], { size: 16, stroke: 2 }), 'Mark moment');
    const stop = h('button', {
      type: 'button', class: 'capture-round capture-stop', 'aria-label': 'Stop and save',
      // Stopping saves the session; Progress then checks it against your memory (progress.js).
      onClick: () => { st.paused = true; st.saved = true; speech?.stop(); ctx.go('progress'); },
    }, icon('stop', { size: 16 }));
    const refocusMic = document.activeElement?.classList?.contains('capture-mic') && footer.contains(document.activeElement);
    footer.replaceChildren(status, h('div', { class: 'capture-controls' }, mic || pause, mark, stop));
    if (refocusMic) footer.querySelector('.capture-mic')?.focus({ preventScroll: true });
  }

  function drawMode() {
    const conversation = st.mode === 'conversation';
    conversationButton.setAttribute('aria-pressed', String(conversation));
    sessionButton.setAttribute('aria-pressed', String(!conversation));
    tickClock();
    const title = h('h2', { class: 'serif' }, conversation ? 'Hallway conversation' : 'Zero-code tracing with eBPF on Kubernetes');
    const heading = h('div', { class: 'capture-heading' },
      conversation ? title : h('div', { class: 'capture-title-row' }, title,
        h('a', {
          class: 'icon-btn capture-cal', href: hashFor('calendar', { from: 'live' }), 'aria-label': 'Open this session in your calendar',
        }, icon('calendar', { size: 20, stroke: 1.8 }))),
      h('p', null, conversation ? 'Expo hall · started 2:41 PM'
        : 'Talk · Room B · Mon 3:30 PM · started from your calendar'));
    if (conversation) {
      // Brief on whoever the speaker is now (the peer, or the person picked on #/tag).
      // A typed name with no persona has nobody to brief on, so there is no link.
      const subject = store.speakers.s2.personaId ? ctx.person(store.speakers.s2.personaId) : null;
      main.replaceChildren(h('div', { class: 'capture-content' }, heading, log,
        subject ? h('a', { class: 'capture-brief', href: hashFor('person', { id: subject.id }) },
          icon('sparkle', { size: 18 }),
          h('span', null, `Brief me on ${subject.name}`), icon('chevron', { size: 18 })) : null));
    } else {
      const sessionLog = h('section', { class: 'transcript session-transcript', 'aria-label': 'Session transcript', lang: 'en' },
        content.session.map(([id, role, text], i) => {
          const p = ctx.person(id);
          return transcriptLine({ ...p, role, text, time: `3:${32 + i * 2} PM` });
        }));
      main.replaceChildren(h('div', { class: 'capture-content' }, heading, sessionLog));
    }
    main.scrollTop = 0;
    drawFooter();
  }

  function pickMode(mode) {
    st.mode = mode;
    drawMode();
  }

  appendLines();
  drawMode();
  const clockTimer = setInterval(tickClock, 1000);
  ctx.onCleanup(() => clearInterval(clockTimer));
  const revealTimer = setInterval(() => {
    if (cap.live || st.mode !== 'conversation' || st.paused || st.revealed >= content.lines.length) return;
    const nearBottom = main.scrollHeight - main.scrollTop - main.clientHeight < 64;
    st.revealed += 1;
    appendLines();
    if (nearBottom) main.scrollTop = main.scrollHeight;
  }, 2500);
  ctx.onCleanup(() => clearInterval(revealTimer));

  // Either phone's speech or mic changes (speech.js): redraw the transcript, and the footer only when
  // whose mic is on changed, so the status isn't re-announced for every word.
  ctx.onCleanup(ctx.bus.on('capture:update', () => {
    if (st.mode !== 'conversation') return;
    const nearBottom = main.scrollHeight - main.scrollTop - main.clientHeight < 64;
    appendLines();
    tickClock();
    if (footerKey !== [st.mode, st.paused, cap.live, cap.listening, cap.error].join('|')) drawFooter();
    if (nearBottom) main.scrollTop = main.scrollHeight;
  }));
  // Leaving Capture turns this phone's mic off.
  ctx.onCleanup(() => { if (speech?.isOn()) speech.stop(); });

  return h('div', { class: 'screen live', lang: 'en' },
    topbar({ title: 'Capture', backLabel: 'Back to home', right: pill }),
    modes, main, footer, bottomNav('live'));
}
