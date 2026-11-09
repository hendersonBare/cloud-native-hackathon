// Home: greeting, "Ask your memory" bar, live capture card, swipeable
// opportunity deck, latest agent conversation card and up next. Ported from
// Main.dc.html (v2 design).

import { h, svg, icon, avatar, bottomNav, eyebrow } from '../ui.js';
import { hashFor } from '../route.js';

const SWIPE_AT = 80;

function partOfDay(d = new Date()) {
  const hr = d.getHours();
  if (hr < 12) return 'morning';
  if (hr < 18) return 'afternoon';
  return 'evening';
}

function fmtClock(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export function render(ctx) {
  const { me, peer, view, store, bus } = ctx;
  const content = view.home;
  const st = store.home || (store.home = {
    idx: 0,
    talking: null,
    listening: false,
  });
  // Shared with the Live screen so both show the same recording clock.
  if (!store.liveStart) store.liveStart = Date.now() - content.live.elapsedSec * 1000;
  const people = content.opportunities.map((o) => ({ ...ctx.person(o.id), topics: o.topics, chips: o.chips }));

  // Header
  const weekday = new Date().toLocaleDateString('en-US', { weekday: 'long' });
  const header = h('header', { class: 'home-head' },
    h('div', { class: 'stack', style: { gap: '4px' } },
      h('p', { class: 'eyebrow' }, `${weekday} · ${content.event}`),
      h('h1', { class: 'serif home-greeting' }, 'Good ', h('em', null, partOfDay()), me?.name ? `, ${me.name}` : ''),
    ),
    h('a', { class: 'icon-btn home-me', href: '#/profile', 'aria-label': 'Your agent identity' },
      icon('user', { size: 21 })),
  );

  // Live capture card
  const clock = h('span', { class: 'live-clock tabular', 'aria-label': 'Elapsed time' }, '00:00');
  const tickClock = () => { clock.textContent = fmtClock(Math.floor((Date.now() - store.liveStart) / 1000)); };
  tickClock();
  const clockTimer = setInterval(tickClock, 1000);
  ctx.onCleanup(() => clearInterval(clockTimer));

  const live = h('section', { class: 'card-fill live-card', 'aria-labelledby': 'live-h' },
    h('div', { class: 'live-info' },
      h('span', { class: 'live-tag' },
        h('span', { class: 'live-dot rp-pulse', 'aria-hidden': 'true' }),
        'LIVE',
        h('span', { class: 'live-sep' }, '· ', clock)),
      h('h2', { id: 'live-h', class: 'live-title' }, content.live.title),
    ),
    h('a', { class: 'live-open', href: '#/live' }, 'Open transcript'),
  );

  // Opportunity deck
  const deck = h('div', { class: 'deck' });
  const latestSlot = h('div', { class: 'latest-slot' });

  function emptyState() {
    return h('div', { class: 'deck-empty' },
      h('p', { class: 'deck-empty-title' }, "You're all caught up"),
      h('p', { class: 'muted', style: { fontSize: '14px' } }, 'Your agent keeps looking as you meet people'),
      h('button', {
        type: 'button',
        class: 'link-btn',
        onClick: () => { st.idx = 0; st.talking = null; drawDeck(true); drawLatest(); },
      }, 'Show them again'),
    );
  }

  function cardFor(p) {
    let startX = 0;
    let dx = 0;
    let dragging = false;
    let leaving = false;

    const art = h('article', {
      class: 'opp-card',
      tabindex: '0',
      'aria-label': `Opportunity: connect with ${p.name}, ${p.role}. Press right arrow to connect, left arrow to pass.`,
    });

    const apply = () => {
      art.style.transform = `translateX(${dx}px) rotate(${Math.round(dx / 2) / 10}deg)`;
      art.style.borderColor = dx > 24 ? 'var(--yes)' : dx < -24 ? 'var(--no)' : '';
    };

    const decide = (dir) => {
      if (leaving) return;
      leaving = true;
      art.style.transition = '';
      dx = dir === 'right' ? 440 : -440;
      apply();
      setTimeout(() => {
        st.idx += 1;
        if (dir === 'right') {
          st.talking = p.id;
          bus.emit('ui:connect', { from: me.id, to: p.id });
        } else {
          bus.emitLocal('ui:pass', { from: me.id, to: p.id });
        }
        drawDeck(true);
        drawLatest();
      }, 240);
    };

    art.addEventListener('pointerdown', (e) => {
      if (leaving || e.target.closest('button')) return;
      dragging = true;
      startX = e.clientX;
      dx = 0;
      art.style.transition = 'none';
      try { art.setPointerCapture(e.pointerId); } catch { /* ignore */ }
    });
    art.addEventListener('pointermove', (e) => {
      if (!dragging) return;
      dx = e.clientX - startX;
      apply();
    });
    const end = () => {
      if (!dragging) return;
      dragging = false;
      art.style.transition = '';
      if (dx > SWIPE_AT) decide('right');
      else if (dx < -SWIPE_AT) decide('left');
      else { dx = 0; apply(); }
    };
    art.addEventListener('pointerup', end);
    art.addEventListener('pointercancel', end);
    art.addEventListener('keydown', (e) => {
      if (e.target !== art) return;
      if (e.key === 'ArrowRight') { e.preventDefault(); decide('right'); }
      if (e.key === 'ArrowLeft') { e.preventDefault(); decide('left'); }
    });

    art.append(
      h('div', { class: 'row', style: { gap: '12px' } },
        avatar(p.initials, p.tone, 44, 15),
        h('div', { class: 'grow stack', style: { gap: '1px' } },
          h('p', { class: 'eyebrow gold' }, 'Connect with'),
          h('h3', { class: 'opp-name' }, p.name),
        ),
        h('div', { class: 'row', style: { gap: '2px', flex: 'none' } },
          h('button', { type: 'button', class: 'decide-btn', 'aria-label': `Pass on ${p.name}`, onClick: () => decide('left') },
            h('span', { class: 'decide-chip no', 'aria-hidden': 'true' }, icon('close', { size: 16, stroke: 2.6 }))),
          h('button', { type: 'button', class: 'decide-btn', 'aria-label': `Connect with ${p.name}`, onClick: () => decide('right') },
            h('span', { class: 'decide-chip yes', 'aria-hidden': 'true' }, icon('check', { size: 18, stroke: 2.6 }))),
        ),
      ),
      h('p', { class: 'opp-role' }, p.role),
      h('div', { class: 'opp-topics' },
        h('p', { class: 'eyebrow' }, 'Talk about'),
        h('ul', { class: 'stack' }, p.topics.map((t) => h('li', { class: 'topic' }, h('span', { class: 'topic-dot', 'aria-hidden': 'true' }), h('span', null, t)))),
      ),
    );
    return art;
  }

  function drawDeck(moveFocus) {
    const p = people[st.idx];
    if (!p) {
      deck.replaceChildren(emptyState());
      if (moveFocus) deck.querySelector('button')?.focus({ preventScroll: true });
      return;
    }
    const left = people.length - st.idx;
    const card = cardFor(p);
    deck.replaceChildren(
      h('div', { class: 'deck-back back2', 'aria-hidden': 'true', style: { opacity: left > 2 ? 1 : 0 } }),
      h('div', { class: 'deck-back back1', 'aria-hidden': 'true', style: { opacity: left > 1 ? 1 : 0 } }),
      card,
    );
    if (moveFocus) card.focus({ preventScroll: true });
  }

  function drawLatest() {
    const t = st.talking ? ctx.person(st.talking) : null;
    const who = t || ctx.person(content.agreed.with);
    const chips = (t ? content.opportunities.find((o) => o.id === t.id)?.chips : content.agreed.chips) || [];

    let badge;
    let action = null;
    if (t) {
      badge = h('span', { class: 'latest-badge talking' },
        h('span', { class: 'latest-dots', 'aria-hidden': 'true' }, h('span'), h('span'), h('span')),
        'Agents talking');
      if (t.id === peer.id) {
        action = h('a', { class: 'latest-action watch', href: '#/exchange', 'aria-label': 'Watch the agents talk' },
          icon('chevron', { size: 18, stroke: 1.9 }));
      }
    } else {
      badge = h('span', { class: 'latest-badge agreed' }, icon('check', { size: 13, stroke: 3 }), 'Agents agreed');
      // Calendar opens its Add event sheet prefilled with this person (calendar.js reads ?add=1&with=).
      action = h('a', { class: 'latest-action', href: hashFor('calendar', { add: '1', with: who.id }), 'aria-label': `Create an event with ${who.name}` },
        h('span', { class: 'decide-chip add', 'aria-hidden': 'true' }, icon('plus', { size: 18, stroke: 2.2 })));
    }

    latestSlot.replaceChildren(h('div', { class: 'latest', role: 'status', 'aria-label': 'Latest agent conversation' },
      h('div', { class: 'latest-top' },
        avatar(who.initials, who.tone, 40, 14),
        h('div', { class: 'latest-who' }, badge, h('span', { class: 'latest-name' }, who.name)),
        action),
      h('div', { class: 'latest-chips' },
        svg([['path', { d: 'M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z' }]],
          { size: 16, stroke: 1.8, label: "You'll talk about" }),
        chips.map((c) => h('span', { class: 'latest-chip' }, c))),
    ));
  }

  drawDeck(false);
  drawLatest();

  const opportunities = h('section', { class: 'stack', style: { gap: '10px' }, 'aria-labelledby': 'opp-h' },
    eyebrow('Opportunities', { id: 'opp-h' }),
    deck,
    latestSlot,
  );

  // Up next
  const upNext = h('section', { class: 'stack', style: { gap: '8px' }, 'aria-labelledby': 'next-h' },
    eyebrow('Up next', { id: 'next-h' }),
    h('a', { class: 'card upnext', href: '#/calendar' },
      content.upNext.map((e) => h('span', { class: 'upnext-row' },
        h('span', { class: 'upnext-time tabular' }, e.time),
        h('span', { class: 'grow upnext-title' }, e.title),
        h('span', { class: 'upnext-status' }, e.status)))),
  );

  // Ask bar
  const wave = h('span', { class: 'ask-wave', 'aria-hidden': 'true' },
    [0, 0.15, 0.3, 0.45].map((d) => h('span', { class: 'rp-wave', style: { animationDelay: `${d}s` } })));
  const askText = h('span', { class: 'ask-text' });
  const micBtn = h('button', { type: 'button', class: 'mic-btn' });
  const askBar = h('div', { class: 'ask-bar' },
    h('a', { class: 'ask-link', href: '#/memory' },
      icon('search', { size: 18, stroke: 1.9 }),
      askText),
    wave,
    micBtn,
  );
  const drawAsk = () => {
    const on = st.listening;
    askBar.classList.toggle('listening', on);
    askText.textContent = on ? 'Listening… ask anything you heard' : 'Ask your memory';
    wave.hidden = !on;
    micBtn.setAttribute('aria-pressed', String(on));
    micBtn.setAttribute('aria-label', on ? 'Stop listening' : 'Ask by voice');
    micBtn.replaceChildren(on ? icon('stop', { size: 16 }) : icon('mic', { size: 20, stroke: 1.9 }));
  };
  micBtn.addEventListener('click', () => { st.listening = !st.listening; drawAsk(); });
  drawAsk();

  return h('div', { class: 'screen home' },
    h('main', { class: 'scroll home-main' }, header, askBar, live, opportunities, upNext),
    bottomNav('home'),
  );
}
