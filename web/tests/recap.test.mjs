// Recap: the attended-talk selection, the fallbacks and the trip report are pure, so they are tested here.
import test from 'node:test';
import assert from 'node:assert/strict';
import { CONTENT, attendedTalks, comingUp, fallbackTalks, formatOffset, tripReport } from '../app/screens/recap.js';
import { TABS, TAB_FOR } from '../app/ui.js';

const ava = CONTENT['acme.ava'];
const NOW = Date.parse('2026-11-09T23:10:00Z'); // 4:10 PM MST

const ev = (over) => ({
  event_id: 'evt-x', persona_id: 'acme.ava', kind: 'talk', title: 'T', status: 'confirmed', capture: true,
  source: 'conference', starts_at: '2026-11-09T20:30:00Z', ends_at: '2026-11-09T21:00:00Z', ...over,
});

test('Recap replaces Calendar in the tab bar, and the calendar route still has a tab to light up', () => {
  const routes = TABS.map((tab) => tab.route);
  assert.ok(routes.includes('recap'));
  assert.ok(!routes.includes('calendar'));
  assert.equal(TABS.length, 5);
  assert.ok(routes.includes(TAB_FOR.calendar));
  assert.equal(TAB_FOR.recap, 'recap');
});

test('formatOffset writes m:ss and h:mm:ss', () => {
  assert.equal(formatOffset(38), '0:38');
  assert.equal(formatOffset(1460), '24:20');
  assert.equal(formatOffset(3723), '1:02:03');
  assert.equal(formatOffset(-5), '0:00');
});

test('attendedTalks keeps captured, started, non-declined talks, newest first, with their takeaways', () => {
  const events = [
    ev({ talk_id: 'talk-otel-regulated', starts_at: '2026-11-09T20:30:00Z', ends_at: '2026-11-09T21:00:00Z' }),
    ev({ talk_id: 'talk-ebpf-edge', starts_at: '2026-11-09T23:00:00Z', ends_at: '2026-11-09T23:30:00Z' }),
    ev({ talk_id: 'talk-ebpf-zero-code', starts_at: '2026-11-09T22:30:00Z', ends_at: '2026-11-09T23:00:00Z' }),
    ev({ talk_id: 'talk-later', starts_at: '2026-11-10T16:00:00Z', ends_at: '2026-11-10T16:30:00Z' }),
    ev({ talk_id: 'talk-no-capture', capture: false }),
    ev({ talk_id: 'talk-declined', status: 'declined' }),
    ev({ kind: 'meeting', title: 'Coffee' }),
  ];
  const talks = attendedTalks(events, NOW, ava);
  assert.deepEqual(talks.map((t) => t.takeaways.length), [3, 3, 3]);
  assert.equal(talks[0].takeaways, ava.talks['talk-ebpf-edge'].takeaways);
  assert.equal(talks[0].live, true); // 4:00-4:30 PM is running at 4:10
  assert.equal(talks[1].live, false);
  assert.equal(talks[2].takeaways, ava.talks['talk-otel-regulated'].takeaways);
});

test('a talk with no transcript is still listed, with no takeaways', () => {
  const [keynote] = attendedTalks([ev({ title: 'Opening keynotes', talk_id: undefined })], NOW, ava);
  assert.equal(keynote.title, 'Opening keynotes');
  assert.deepEqual(keynote.takeaways, []);
});

test('fallbackTalks lists every scripted talk when the calendar is unavailable', () => {
  assert.equal(fallbackTalks(ava).length, Object.keys(ava.talks).length);
  assert.ok(fallbackTalks(ava).every((t) => t.takeaways.length > 0 && t.startsAt === null));
});

test('comingUp returns the next events that have not started, soonest first', () => {
  const events = [
    ev({ title: 'B', starts_at: '2026-11-10T22:00:00Z', ends_at: '2026-11-10T22:30:00Z' }),
    ev({ title: 'A', starts_at: '2026-11-10T01:30:00Z', ends_at: '2026-11-10T03:00:00Z' }),
    ev({ title: 'Past' }),
    ev({ title: 'Declined', status: 'declined', starts_at: '2026-11-10T00:00:00Z', ends_at: '2026-11-10T00:30:00Z' }),
    ev({ title: 'C', starts_at: '2026-11-11T17:00:00Z', ends_at: '2026-11-11T17:30:00Z' }),
  ];
  assert.deepEqual(comingUp(events, NOW).map((e) => e.title), ['A', 'B']);
  assert.deepEqual(comingUp(null, NOW), []);
});

test('the trip report covers goals, cited takeaways, topics and next steps', () => {
  const me = { name: 'Ava', role: 'Solutions Engineer · Acme Observability' };
  const report = tripReport(me, ava, fallbackTalks(ava));
  assert.match(report, /^Trip report · Ava, Solutions Engineer/);
  assert.match(report, /Find a design partner in healthcare \(On track\)/);
  assert.match(report, /\(Dev · 0:38\)/);
  assert.match(report, /\(Bo · 2:41 PM\)/);
  assert.match(report, /New to you: HIPAA reviews of telemetry/);
  assert.match(report, /- Check that Sam sends Kai the security questionnaire/);
});

test("Bo's recap is in Spanish and cites only speakers by name", () => {
  const bo = CONTENT['bluefin.bo'];
  assert.equal(bo.lang, 'es');
  const report = tripReport({ name: 'Bo', role: 'Platform Lead · Bluefin Health' }, bo, fallbackTalks(bo));
  assert.match(report, /^Informe del viaje · Bo/);
  assert.match(report, /\(En camino\)/);
  for (const talk of Object.values(bo.talks)) {
    for (const item of talk.takeaways) assert.ok(Number.isInteger(item.at) && item.speaker, item.text);
  }
});
