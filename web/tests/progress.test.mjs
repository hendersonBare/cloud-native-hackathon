// The Progress tab's day roll-up (web/app/progress-model.js): what each memory check after a
// session adds, and how stopping the live capture changes the day.
import test, { after, before, describe } from 'node:test';
import assert from 'node:assert/strict';
import { CONTENT, LIVE_SESSION, dayProgress, learnedIn } from '../app/progress-model.js';
import { PEOPLE, person } from '../app/data.js';
import { CONTENT as CAPTURE } from '../app/screens/live.js';
import { install } from './fake-dom.mjs';

const PHONES = ['acme.ava', 'bluefin.bo'];

test('both demo phones have a day, with the live capture as one of its sessions', () => {
  for (const id of PHONES) {
    const ids = CONTENT[id].sessions.map((s) => s.id);
    assert.ok(ids.includes(LIVE_SESSION), id);
    assert.equal(new Set(ids).size, ids.length, `${id}: session ids are unique`);
    assert.ok(CAPTURE[id], `${id}: Capture has the matching conversation`);
  }
});

test('every session, takeaway, promise and question points at something real', () => {
  for (const id of PHONES) {
    const day = CONTENT[id];
    const sessions = new Set(day.sessions.map((s) => s.id));
    for (const s of day.sessions) {
      if (s.with) assert.ok(PEOPLE[s.with], `${id}/${s.id}: ${s.with}`);
      assert.ok(Number.isInteger(s.added) && Number.isInteger(s.updated), `${id}/${s.id}: counts`);
      assert.equal(day.takeaways.filter((t) => t.session === s.id && t.key).length, 1, `${id}/${s.id}: one key lesson`);
    }
    for (const item of [...day.takeaways, ...day.promises, ...day.questions]) {
      assert.ok(sessions.has(item.session), `${id}: ${item.session}`);
    }
    for (const p of day.promises) assert.ok(PEOPLE[p.to], `${id}: promise to ${p.to}`);
    for (const q of day.questions) assert.ok(PEOPLE[q.ask], `${id}: ask ${q.ask}`);
  }
});

test('before the capture stops, the live session is pending and adds nothing', () => {
  const day = dayProgress(CONTENT['acme.ava']);
  assert.deepEqual(day.pending.map((s) => s.id), [LIVE_SESSION]);
  assert.ok(!day.checked.some((s) => s.id === LIVE_SESSION));
  assert.ok(!day.takeaways.some((t) => t.session === LIVE_SESSION));
  assert.ok(!day.promises.some((p) => p.session === LIVE_SESSION));
  assert.ok(!day.best.some((s) => s.id === LIVE_SESSION));
  assert.deepEqual(day.stats, { people: 2, sessions: 3, memories: 9 });
  assert.equal(day.latest.id, 'priya');
});

test('stopping the capture checks it: the conversation tops best interactions and gives the biggest lesson', () => {
  for (const id of PHONES) {
    const before = dayProgress(CONTENT[id]);
    const after = dayProgress(CONTENT[id], { liveSaved: true });
    assert.deepEqual(after.pending, [], id);
    assert.equal(after.latest.id, LIVE_SESSION, id);
    assert.equal(after.best[0].id, LIVE_SESSION, id);
    assert.equal(after.lesson.session, LIVE_SESSION, id);
    assert.equal(after.stats.sessions, before.stats.sessions + 1, id);
    assert.equal(after.stats.people, before.stats.people + 1, id);
    const live = CONTENT[id].sessions.find((s) => s.id === LIVE_SESSION);
    assert.equal(after.stats.memories, before.stats.memories + live.added, id);
  }
});

test('best interactions are people only, most learned first, at most three', () => {
  for (const id of PHONES) {
    const { best } = dayProgress(CONTENT[id], { liveSaved: true });
    assert.ok(best.length > 0 && best.length <= 3, id);
    assert.ok(best.every((s) => s.with), id);
    for (let i = 1; i < best.length; i += 1) assert.ok(learnedIn(best[i - 1]) >= learnedIn(best[i]), id);
  }
});

test('takeaways follow the sessions you learned most from', () => {
  const { takeaways, best } = dayProgress(CONTENT['bluefin.bo'], { liveSaved: true });
  assert.equal(takeaways[0].session, best[0].id);
  assert.equal(takeaways.length, CONTENT['bluefin.bo'].takeaways.length);
});

test('an empty day has no lesson and zero stats', () => {
  const day = dayProgress({ sessions: [] });
  assert.equal(day.lesson, null);
  assert.equal(day.latest, null);
  assert.deepEqual(day.stats, { people: 0, sessions: 0, memories: 0 });
});

describe('Progress screen', () => {
  let restore;
  let render;
  before(async () => {
    restore = install();
    ({ render } = await import('../app/screens/progress.js'));
  });
  after(() => restore());

  const screen = (meId) => render({ me: person(meId), store: {}, view: {}, person, onCleanup() {} });

  test('one gold card holds the biggest lesson and every other takeaway, and nothing prints as "null"', () => {
    for (const id of PHONES) {
      const el = screen(id);
      const cards = el.byClass('progress-hero');
      assert.equal(cards.length, 1, id);
      assert.ok(cards[0].classList.contains('card-gold'), id);
      assert.equal(cards[0].byClass('takeaway').length, dayProgress(CONTENT[id]).takeaways.length - 1, id);
      assert.ok(!el.textContent.includes('null'), id);
    }
  });

  test('the live banner, day stats, learned counts, question subtext and memory checks are not shown', () => {
    const el = screen('acme.ava');
    for (const cls of ['check-banner', 'progress-stats', 'best-learned', 'question-why', 'checks']) {
      assert.equal(el.byClass(cls).length, 0, cls);
    }
    assert.ok(!el.textContent.includes('is still live'));
    assert.ok(!el.textContent.includes('Memory checks today'));
  });
});
