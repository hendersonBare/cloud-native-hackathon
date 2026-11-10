// Progress: what today taught you. Your agent checks your memory after every session you capture
// (Capture's stop button lands here and plays the check), and the day rolls up: the biggest lesson,
// everything else you learned, best interactions ranked by what you learned, promises you made and
// questions still open. Content comes from progress-model.js; every string goes in as text.
import { h, icon, avatar, bottomNav, eyebrow, nextId } from '../ui.js';
import { hashFor } from '../route.js';
import { CONTENT, LIVE_SESSION, dayProgress } from '../progress-model.js';
import { TIMEZONE, zoneLabel } from '../time.js';

const CHECK_MS = 1800;

const newMemories = (n) => `${n} new ${n === 1 ? 'memory' : 'memories'}`;

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
  // Session times are Denver wall-clock time, and the header says so (review rule: never a bare time).
  const weekday = new Date().toLocaleDateString('en-US', { weekday: 'long', timeZone: TIMEZONE });
  const liveSession = content.sessions.find((s) => s.id === LIVE_SESSION);

  const newTag = (session) => (session === fresh ? h('span', { class: 'progress-new' }, 'New') : null);
  const sessionOf = (id) => content.sessions.find((s) => s.id === id);

  // Shown only while the memory check after a stopped capture plays.
  function banner() {
    if (!checking) return null;
    return h('div', { class: 'check-banner is-checking' },
      h('span', { class: 'check-pulse rp-pulse', 'aria-hidden': 'true' }),
      h('span', { class: 'check-text' },
        h('strong', null, 'Checking your memory'),
        h('span', null, `What did ${liveSession.title} teach you?`)));
  }

  // One gold card: the biggest lesson on top, then everything else learned today as a list.
  function hero(day) {
    const lessonFrom = day.lesson ? sessionOf(day.lesson.session) : null;
    const who = lessonFrom?.with ? ctx.person(lessonFrom.with) : null;
    const rest = day.takeaways.filter((t) => t !== day.lesson);
    return h('section', { class: 'card-gold progress-hero', 'aria-labelledby': 'lesson-h' },
      h('h2', { id: 'lesson-h', class: 'eyebrow progress-hero-label' }, 'Biggest lesson today'),
      h('p', { class: 'progress-lesson' },
        day.lesson ? day.lesson.text : 'Capture a session and your first lesson shows up here.'),
      lessonFrom ? h('p', { class: 'progress-lesson-from' },
        who ? avatar(who.initials, who.tone, 22, 10) : icon('mic', { size: 16, stroke: 1.8 }),
        `From ${lessonFrom.title}, ${lessonFrom.time}`, newTag(lessonFrom.id)) : null,
      rest.length ? h('div', { class: 'progress-also' },
        h('h3', { class: 'eyebrow progress-hero-label' }, 'Also learned today'),
        h('ul', { class: 'takeaways' }, rest.map((t) => {
          const s = sessionOf(t.session);
          return h('li', { class: 'takeaway' },
            h('p', { class: 'takeaway-text' }, t.text),
            h('p', { class: 'takeaway-from' }, `${s.title} · ${s.time}`, newTag(t.session)));
        }))) : null);
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
            h('span', { class: 'best-rank tabular', 'aria-hidden': 'true' }, String(i + 1)),
            avatar(p.initials, p.tone, 40, 14),
            h('div', { class: 'grow stack', style: { gap: '1px' } },
              h('h3', { id: headingId, class: 'best-name' }, p.name, newTag(s.id)),
              h('p', { class: 'best-where' }, `${s.kind} · ${s.time}`))),
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
          h('p', { class: 'grow question-text' }, q.text, newTag(q.session)),
          h('a', { class: 'question-ask', href: hashFor('person', { id: who.id }), 'aria-label': `Ask ${who.name}: open ${who.name}'s brief` },
            avatar(who.initials, who.tone, 26, 11), `Ask ${who.name}`));
      })));
  }

  function draw() {
    const day = dayProgress(content, { liveSaved: liveSaved && !checking });
    // Sections with nothing to show return null; replaceChildren would print that as text.
    main.replaceChildren(...[
      h('header', { class: 'progress-head' },
        h('p', { class: 'eyebrow' }, `${weekday} · ${view.home?.event || 'KubeCon'} · All times ${zoneLabel()}`),
        h('h1', { class: 'serif progress-title' }, 'Your ', h('em', null, 'progress'))),
      banner(),
      hero(day),
      bestSection(day),
      promisesSection(day),
      questionsSection(day),
    ].filter(Boolean));
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
