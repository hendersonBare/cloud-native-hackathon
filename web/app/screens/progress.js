// Progress: what today taught you. Your agent checks your memory after every session you capture
// (Capture's stop button lands here and plays the check), and the day rolls up: the biggest lesson,
// takeaways, best interactions ranked by what you learned, promises you made and questions still
// open. Content comes from progress-model.js; every string goes in as text.
import { h, icon, avatar, bottomNav, eyebrow, nextId } from '../ui.js';
import { hashFor } from '../route.js';
import { CONTENT, LIVE_SESSION, dayProgress, learnedIn } from '../progress-model.js';

const CHECK_MS = 1800;

const newMemories = (n) => `${n} new ${n === 1 ? 'memory' : 'memories'}`;
const memoryDelta = (s) => (s.updated ? `+${s.added} new · ${s.updated} updated` : `+${s.added} new`);

export function render(ctx) {
  const { me, store, view } = ctx;
  const content = CONTENT[me.id] || CONTENT['acme.ava'];
  const st = store.progress || (store.progress = { kept: [], shown: [] });
  const liveSaved = !!store.live?.saved;
  // The first visit after Capture saves the live session plays its memory check, once.
  let checking = liveSaved && !st.shown.includes(LIVE_SESSION);
  let fresh = null; // the session whose check just finished on this visit: its items are marked New

  const status = h('p', { class: 'visually-hidden', role: 'status', 'aria-live': 'polite', 'aria-atomic': 'true' });
  const main = h('main', { class: 'scroll progress-main' });
  const weekday = new Date().toLocaleDateString('en-US', { weekday: 'long' });
  const liveSession = content.sessions.find((s) => s.id === LIVE_SESSION);

  const newTag = (session) => (session === fresh ? h('span', { class: 'progress-new' }, 'New') : null);
  const sessionOf = (id) => content.sessions.find((s) => s.id === id);
  const sourceLabel = (s) => `${s.title} · ${s.time}`;

  function banner(day) {
    if (checking) {
      return h('div', { class: 'check-banner is-checking' },
        h('span', { class: 'check-pulse rp-pulse', 'aria-hidden': 'true' }),
        h('span', { class: 'check-text' },
          h('strong', null, 'Checking your memory'),
          h('span', null, `What did ${liveSession.title} teach you?`)));
    }
    if (day.pending.length) {
      const live = day.pending[0];
      return h('a', { class: 'check-banner is-pending', href: '#/live' },
        h('span', { class: 'check-live', 'aria-hidden': 'true' }),
        h('span', { class: 'check-text' },
          h('strong', null, `${live.title} is still live`),
          h('span', null, 'Stop the capture and Progress checks it against your memory')),
        icon('chevron', { size: 18 }));
    }
    if (!day.latest) return null;
    return h('div', { class: `check-banner${fresh ? ' is-fresh' : ''}` },
      h('span', { class: 'check-done', 'aria-hidden': 'true' }, icon('check', { size: 15, stroke: 2.6 })),
      h('span', { class: 'check-text' },
        h('strong', null, `Memory checked after ${day.latest.title}`),
        h('span', null, memoryDelta(day.latest))));
  }

  function hero(day) {
    const lessonFrom = day.lesson ? sessionOf(day.lesson.session) : null;
    const who = lessonFrom?.with ? ctx.person(lessonFrom.with) : null;
    return h('section', { class: 'card-fill progress-hero', 'aria-labelledby': 'lesson-h' },
      h('h2', { id: 'lesson-h', class: 'eyebrow progress-hero-label' }, 'Biggest lesson today'),
      day.lesson
        ? h('p', { class: 'serif progress-lesson' }, day.lesson.text)
        : h('p', { class: 'serif progress-lesson' }, 'Capture a session and your first lesson shows up here.'),
      lessonFrom ? h('p', { class: 'progress-lesson-from' },
        who ? avatar(who.initials, who.tone, 22, 10) : icon('mic', { size: 16, stroke: 1.8 }),
        `From ${lessonFrom.title}, ${lessonFrom.time}`) : null,
      h('dl', { class: 'progress-stats' },
        [[day.stats.people, 'people met'], [day.stats.sessions, 'sessions'], [day.stats.memories, 'new memories']]
          .map(([n, label]) => h('div', { class: 'progress-stat' },
            h('dt', null, label), h('dd', { class: 'serif tabular' }, String(n))))));
  }

  function takeawaysSection(day) {
    // The biggest lesson already leads the page, so the list is everything else.
    const rest = day.takeaways.filter((t) => t !== day.lesson);
    if (!rest.length) return null;
    return h('section', { class: 'stack progress-section', 'aria-labelledby': 'learn-h' },
      eyebrow('Also learned today', { id: 'learn-h' }),
      h('ol', { class: 'card takeaways' }, rest.map((t, i) => {
        const s = sessionOf(t.session);
        return h('li', { class: 'takeaway' },
          h('span', { class: 'takeaway-n serif tabular', 'aria-hidden': 'true' }, String(i + 1)),
          h('div', { class: 'grow stack', style: { gap: '4px' } },
            h('p', { class: 'takeaway-text' }, t.text),
            h('p', { class: 'takeaway-from' }, sourceLabel(s), newTag(t.session))));
      })));
  }

  function bestSection(day) {
    if (!day.best.length) return null;
    return h('section', { class: 'stack progress-section', 'aria-labelledby': 'best-h' },
      h('div', { class: 'progress-section-head' },
        eyebrow('Best interactions', { id: 'best-h' }),
        h('span', { class: 'progress-hint' }, 'Ranked by what you learned')),
      h('ol', { class: 'stack best-list' }, day.best.map((s, i) => {
        const p = ctx.person(s.with);
        const headingId = nextId('best');
        return h('li', null, h('article', { class: 'card best-card', 'aria-labelledby': headingId },
          h('div', { class: 'best-top' },
            h('span', { class: 'best-rank serif tabular', 'aria-hidden': 'true' }, String(i + 1)),
            avatar(p.initials, p.tone, 40, 14),
            h('div', { class: 'grow stack', style: { gap: '1px' } },
              h('h3', { id: headingId, class: 'best-name' }, p.name, newTag(s.id)),
              h('p', { class: 'best-where' }, `${s.kind} · ${s.time}`)),
            h('span', { class: 'best-learned' }, `${learnedIn(s)} learned`)),
          h('p', { class: 'best-headline' }, s.headline),
          h('ul', { class: 'best-points' }, (s.learned || []).map((point) => h('li', null, point))),
          h('a', { class: 'best-brief', href: hashFor('person', { id: p.id }) },
            `Open ${p.name}'s brief`, icon('chevron', { size: 16 })),
        ));
      })));
  }

  function promisesSection(day) {
    if (!day.promises.length) return null;
    const kept = day.promises.filter((p) => st.kept.includes(p.id)).length;
    const count = h('span', { class: 'progress-hint' }, `${kept} of ${day.promises.length} kept`);
    return h('section', { class: 'stack progress-section', 'aria-labelledby': 'promise-h' },
      h('div', { class: 'progress-section-head' }, eyebrow('Promises you made', { id: 'promise-h' }), count),
      h('ul', { class: 'card promises' }, day.promises.map((p) => {
        const to = ctx.person(p.to);
        const id = nextId('promise');
        const box = h('input', { type: 'checkbox', id, class: 'promise-box', checked: st.kept.includes(p.id) });
        box.addEventListener('change', () => {
          st.kept = box.checked ? [...st.kept, p.id] : st.kept.filter((k) => k !== p.id);
          const n = day.promises.filter((x) => st.kept.includes(x.id)).length;
          count.textContent = `${n} of ${day.promises.length} kept`;
        });
        return h('li', { class: 'promise' },
          box,
          h('label', { for: id, class: 'grow stack', style: { gap: '3px' } },
            h('span', { class: 'promise-text' }, p.text),
            h('span', { class: 'promise-from' }, `To ${to.name} · ${sessionOf(p.session).title}`, newTag(p.session))));
      })));
  }

  function questionsSection(day) {
    if (!day.questions.length) return null;
    return h('section', { class: 'stack progress-section', 'aria-labelledby': 'open-h' },
      eyebrow('Still open', { id: 'open-h' }),
      h('ul', { class: 'card questions' }, day.questions.map((q) => {
        const who = ctx.person(q.ask);
        return h('li', { class: 'question' },
          h('div', { class: 'grow stack', style: { gap: '3px' } },
            h('p', { class: 'question-text' }, q.text, newTag(q.session)),
            h('p', { class: 'question-why' }, q.why)),
          h('a', { class: 'question-ask', href: hashFor('person', { id: who.id }), 'aria-label': `Ask ${who.name}: open ${who.name}'s brief` },
            avatar(who.initials, who.tone, 26, 11), `Ask ${who.name}`));
      })));
  }

  function checksSection(day) {
    const rows = [...content.sessions].reverse().map((s) => {
      const isPending = day.pending.includes(s);
      const isChecking = checking && s.id === LIVE_SESSION;
      let state;
      if (isChecking) state = h('span', { class: 'check-state is-checking' }, 'Checking…');
      else if (isPending) state = h('a', { class: 'check-state is-live', href: '#/live' }, 'Live now');
      else state = h('span', { class: 'check-state' }, memoryDelta(s));
      return h('li', { class: `check-row${isPending || isChecking ? ' is-open' : ''}` },
        h('span', { class: 'check-time tabular' }, s.time),
        h('div', { class: 'grow stack', style: { gap: '3px' } },
          h('p', { class: 'check-title' }, s.title, h('span', { class: 'check-kind' }, ` · ${s.kind}`)),
          isPending || isChecking
            ? h('p', { class: 'check-headline' }, 'Checked against your memory when the capture stops')
            : h('p', { class: 'check-headline' }, s.headline),
          state));
    });
    return h('section', { class: 'stack progress-section', 'aria-labelledby': 'checks-h' },
      h('div', { class: 'progress-section-head' },
        eyebrow('Memory checks today', { id: 'checks-h' }),
        h('span', { class: 'progress-hint' }, 'After every session')),
      h('ol', { class: 'card checks' }, rows));
  }

  function draw() {
    const day = dayProgress(content, { liveSaved: liveSaved && !checking });
    main.replaceChildren(
      h('header', { class: 'progress-head' },
        h('p', { class: 'eyebrow' }, `${weekday} · ${view.home?.event || 'KubeCon'}`),
        h('h1', { class: 'serif progress-title' }, 'Your ', h('em', null, 'progress'))),
      banner(day),
      hero(day),
      takeawaysSection(day),
      bestSection(day),
      promisesSection(day),
      questionsSection(day),
      checksSection(day),
    );
  }

  draw();

  if (checking) {
    status.textContent = `Checking your memory after ${liveSession.title}`;
    const markShown = () => { if (!st.shown.includes(LIVE_SESSION)) st.shown.push(LIVE_SESSION); };
    const timer = setTimeout(() => {
      checking = false;
      fresh = LIVE_SESSION;
      markShown();
      draw();
      main.scrollTop = 0;
      status.textContent = `Memory checked after ${liveSession.title}: ${newMemories(liveSession.added)}`;
    }, CHECK_MS);
    // Leaving mid-check still counts it, so the check plays once.
    ctx.onCleanup(() => { clearTimeout(timer); markShown(); });
  }

  return h('div', { class: 'screen progress', lang: 'en' }, status, main, bottomNav('progress'));
}
