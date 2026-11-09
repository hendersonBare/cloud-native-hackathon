// Progress: what the day taught you. After every captured session your agent checks it against
// your memory and keeps what was new; this model rolls those checks up into the day: the biggest
// lesson, takeaways, your best interactions (ranked by how much you learned), promises you made
// and questions still open. Pure (no DOM, no network), so it is unit-tested.
// All people are fictional (data.js); text is only ever rendered with textContent.

/** The session Capture is recording now. Progress counts it once Capture's stop button saves it. */
export const LIVE_SESSION = 'hallway';

/**
 * Per persona, in time order.
 * session: { id, time, title, kind, with?, added, updated, headline, learned? }
 *   added / updated: memories this session created / changed when your memory was checked.
 *   with: the person you met (talks have none); learned: what you now know about them.
 * takeaway: { session, text, key? }  key marks the session's single biggest lesson.
 * promise:  { id, session, to, text }  something you said you would do.
 * question: { session, ask, text, why }  ask is who could answer it.
 */
export const CONTENT = {
  'acme.ava': {
    sessions: [
      {
        id: 'keynote', time: '9:00 AM', title: 'eBPF tracing keynote', kind: 'Talk', added: 4, updated: 1,
        headline: 'Teams pick eBPF tracing because nobody has to change application code.',
      },
      {
        id: 'sam', time: '10:30 AM', title: 'Booth sync with Sam', kind: 'Conversation', with: 'acme.sam', added: 2, updated: 1,
        headline: "Bluefin's budget decision is in Q1.",
        learned: ['Bluefin sets its budget in Q1', 'Sam owes Kai the security questionnaire'],
      },
      {
        id: 'priya', time: '11:15 AM', title: 'Your agent met Priya', kind: 'Agent exchange', with: 'lumenly.priya',
        added: 3, updated: 1,
        headline: 'Lumenly weighs eBPF overhead against cloud spend.',
        learned: ['Wants eBPF without the overhead', 'Watches cloud spend closely', 'Runs a small platform team'],
      },
      {
        id: 'hallway', time: '2:41 PM', title: 'Hallway with Bo', kind: 'Conversation', with: 'bluefin.bo', added: 5, updated: 2,
        headline: "Cost and a HIPAA sign-off decide Bluefin's pilot.",
        learned: [
          'Tracing has to work without code changes',
          'Cost is their biggest concern, and they are comparing another vendor',
          'Kai, their Security Architect, reviews HIPAA before any pilot',
        ],
      },
    ],
    takeaways: [
      { session: 'keynote', key: true, text: 'eBPF tracing wins because nobody touches application code. The first question is always overhead.' },
      { session: 'sam', key: true, text: 'Know the buying calendar: Bluefin sets its budget in Q1, so a pilot has to start this quarter.' },
      { session: 'priya', key: true, text: 'Infrastructure leads ask about eBPF overhead before features. Lead with a measured number.' },
      { session: 'hallway', key: true, text: 'In healthcare the security review gates the pilot. Get the questionnaire to Kai before the demo.' },
      { session: 'hallway', text: 'Bluefin is comparing vendors on cost, so the price story matters as much as the technology.' },
    ],
    promises: [
      { id: 'kai-questionnaire', session: 'hallway', to: 'bluefin.kai', text: 'Follow up with Kai on the security questionnaire' },
      { id: 'bo-rollout', session: 'hallway', to: 'bluefin.bo', text: 'Walk Bo through the hospital rollout and compare tracing costs' },
      { id: 'priya-overhead', session: 'priya', to: 'lumenly.priya', text: 'Send Priya measured eBPF overhead numbers' },
    ],
    questions: [
      { session: 'hallway', ask: 'bluefin.bo', text: 'What does Bluefin spend on observability today?', why: 'Bo said cost decides, but gave no number.' },
      { session: 'priya', ask: 'lumenly.priya', text: 'How much overhead will Lumenly accept on production nodes?', why: 'Priya asked for numbers but set no limit.' },
      { session: 'keynote', ask: 'kestrel.mia', text: 'How does eBPF tracing hold up on very small clusters?', why: 'The keynote only showed large clusters. Mia runs small ones.' },
    ],
  },
  'bluefin.bo': {
    sessions: [
      {
        id: 'qa', time: '9:30 AM', title: 'Platform track Q&A', kind: 'Talk', added: 3, updated: 1,
        headline: 'Start OpenTelemetry at the collector, not in every service.',
      },
      {
        id: 'sofia', time: '11:40 AM', title: 'Your agent met Sofia', kind: 'Agent exchange', with: 'tidewater.sofia',
        added: 3, updated: 0,
        headline: "Right-sizing clusters cut Tidewater's cloud bill by 30%.",
        learned: ['Cut their cloud bill by 30%', 'Runs FinOps for Kubernetes', 'Right-sized clusters before buying tools'],
      },
      {
        id: 'kai', time: '1:15 PM', title: 'Sync with Kai', kind: 'Conversation', with: 'bluefin.kai', added: 2, updated: 0,
        headline: 'No vendor pilot starts before the HIPAA review.',
        learned: ['Reviews telemetry data for HIPAA', 'Wants the vendor security questionnaire first'],
      },
      {
        id: 'hallway', time: '2:41 PM', title: 'Hallway with Ava', kind: 'Conversation', with: 'acme.ava', added: 5, updated: 2,
        headline: "Acme traces with zero code changes and cut a hospital's incident time by 40%.",
        learned: [
          'Zero-code eBPF tracing that exports to OpenTelemetry',
          'A hospital rollout cut incident time by 40%',
          'Sam is sending Kai the security questionnaire',
        ],
      },
    ],
    takeaways: [
      { session: 'qa', key: true, text: 'Put OpenTelemetry in at the collector first. You can switch vendors later without touching services.' },
      { session: 'sofia', key: true, text: 'Right-sizing is the fastest FinOps win: Tidewater cut its cloud bill by 30% before buying anything.' },
      { session: 'kai', key: true, text: "Kai's HIPAA review is the critical path. Any vendor pilot waits on it." },
      { session: 'hallway', key: true, text: 'Zero-code eBPF tracing could cover the whole migration without touching a clinical service.' },
      { session: 'hallway', text: 'Ask Acme for the hospital case study: 40% faster incidents is the number to check.' },
    ],
    promises: [
      { id: 'ava-costs', session: 'hallway', to: 'acme.ava', text: 'Share our tracing costs with Ava so we can compare' },
      { id: 'kai-review', session: 'kai', to: 'bluefin.kai', text: "Book Kai's HIPAA review before the pilot" },
      { id: 'sofia-sizes', session: 'sofia', to: 'tidewater.sofia', text: 'Send Sofia our cluster sizes for a right-sizing check' },
    ],
    questions: [
      { session: 'hallway', ask: 'acme.ava', text: "What would Acme's tracing cost at our scale?", why: 'Ava shared results, not prices.' },
      { session: 'kai', ask: 'bluefin.kai', text: 'Does eBPF tracing capture any patient data?', why: 'Kai needs this answered for the HIPAA review.' },
      { session: 'sofia', ask: 'tidewater.sofia', text: 'Which clusters did Tidewater right-size first?', why: 'Sofia gave the result, not the order.' },
    ],
  },
};

/** How much a session taught you: memories it added plus memories it changed. */
export const learnedIn = (session) => session.added + session.updated;

/** Most learned first; ties keep time order. */
function byLearned(sessions) {
  return sessions.map((s, i) => [s, i]).sort(([a, i], [b, j]) => learnedIn(b) - learnedIn(a) || i - j).map(([s]) => s);
}

/**
 * The day so far. `liveSaved`: Capture has stopped and saved the live session, so its memory check counts.
 * Returns { checked, pending, latest, stats, lesson, takeaways, best, promises, questions }:
 *   checked / pending: sessions in time order; latest: the last checked one.
 *   lesson: the key takeaway of the session you learned most from.
 *   takeaways: every checked session's takeaways, most-learned session first.
 *   best: up to 3 sessions with a person, most learned first.
 */
export function dayProgress(content, { liveSaved = false } = {}) {
  const sessions = content?.sessions || [];
  const checked = sessions.filter((s) => s.id !== LIVE_SESSION || liveSaved);
  const pending = sessions.filter((s) => !checked.includes(s));
  const ids = new Set(checked.map((s) => s.id));
  const ranked = byLearned(checked);
  const order = new Map(ranked.map((s, i) => [s.id, i]));
  const takeaways = (content?.takeaways || [])
    .map((t, i) => [t, i])
    .filter(([t]) => ids.has(t.session))
    .sort(([a, i], [b, j]) => order.get(a.session) - order.get(b.session) || i - j)
    .map(([t]) => t);
  const people = new Set(checked.filter((s) => s.with).map((s) => s.with));
  return {
    checked,
    pending,
    latest: checked[checked.length - 1] || null,
    stats: {
      people: people.size,
      sessions: checked.length,
      memories: checked.reduce((n, s) => n + s.added, 0),
    },
    lesson: takeaways.find((t) => t.key) || takeaways[0] || null,
    takeaways,
    best: ranked.filter((s) => s.with).slice(0, 3),
    promises: (content?.promises || []).filter((p) => ids.has(p.session)),
    questions: (content?.questions || []).filter((q) => ids.has(q.session)),
  };
}
