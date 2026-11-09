// Live capture: diarized hallway conversation and saved conference session.
import { h, icon, svg, topbar, bottomNav } from '../ui.js';

const CONTENT = {
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
  'bluefin.bo': {
    lines: [
      ['s2', 'Our zero-code eBPF tracing works without application changes.'],
      ['you', 'That fits our hospital migration. Can we keep our OpenTelemetry pipeline?'],
      ['s2', 'Yes. A hospital rollout using this approach cut incident time by 40%.'],
      ['you', 'Observability cost is the main concern. We’re evaluating another vendor too.'],
      ['s2', 'Let’s measure the tracing volume and overhead in a small pilot.'],
      ['you', 'Kai needs to sign off on HIPAA. We’re waiting for Sam’s security questionnaire.'],
      ['s2', 'I’ll follow up with Sam so Kai has it before the pilot review.'],
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

  function appendLines() {
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
    pillText.textContent = saved ? 'SAVED' : `${st.paused ? 'PAUSED' : 'REC'} ${elapsed(store.liveStart)}`;
  }

  function drawFooter() {
    const saved = st.mode === 'session';
    // The design shows no status line while recording; it stays as a screen-reader live region.
    const status = h('p', { class: saved ? 'capture-status' : 'capture-status visually-hidden', role: 'status', 'aria-live': 'polite' },
      icon('memory', { size: 14, stroke: 1.8 }),
      saved ? 'Saved · speakers matched to the program'
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
    const mark = h('button', {
      type: 'button', class: 'capture-mark',
      onClick: () => {
        if (!st.moments) st.moments = [];
        st.moments.push({ elapsed: Date.now() - store.liveStart, line: st.revealed });
        status.replaceChildren(icon('check', { size: 14 }), `Moment marked at ${elapsed(store.liveStart)}`);
      },
    }, svg([['path', { d: 'M6 3h12v18l-6-4-6 4z' }]], { size: 16, stroke: 2 }), 'Mark moment');
    const stop = h('button', {
      type: 'button', class: 'capture-round capture-stop', 'aria-label': 'Stop and save',
      onClick: () => { st.paused = true; st.saved = true; ctx.go('memory'); },
    }, icon('stop', { size: 16 }));
    footer.replaceChildren(status, h('div', { class: 'capture-controls' }, pause, mark, stop));
  }

  function drawMode() {
    const conversation = st.mode === 'conversation';
    conversationButton.setAttribute('aria-pressed', String(conversation));
    sessionButton.setAttribute('aria-pressed', String(!conversation));
    tickClock();
    const heading = h('div', { class: 'capture-heading' },
      h('h2', { class: 'serif' }, conversation ? 'Hallway conversation' : 'Zero-code tracing with eBPF on Kubernetes'),
      h('p', null, conversation ? 'Expo hall · started 2:41 PM'
        : 'Talk · Room B · Mon 3:30 PM · started from your calendar'));
    if (conversation) {
      main.replaceChildren(h('div', { class: 'capture-content' }, heading, log,
        h('a', { class: 'capture-brief', href: '#/person' }, icon('sparkle', { size: 18 }),
          h('span', null, `Brief me on ${peer.name}`), icon('chevron', { size: 18 }))));
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
    if (st.mode !== 'conversation' || st.paused || st.revealed >= content.lines.length) return;
    const nearBottom = main.scrollHeight - main.scrollTop - main.clientHeight < 64;
    st.revealed += 1;
    appendLines();
    if (nearBottom) main.scrollTop = main.scrollHeight;
  }, 2500);
  ctx.onCleanup(() => clearInterval(revealTimer));

  return h('div', { class: 'screen live', lang: 'en' },
    topbar({ title: 'Capture', backLabel: 'Back to home', right: pill }),
    modes, main, footer, bottomNav('live'));
}
