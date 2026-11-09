// Deep dive (live mode): what the gateway prepared after a right swipe. deep_dive_started shows
// "Researching…", deep_dive_ready the summary, plan and the agent's decision, agent_decision the
// outcome. Events are stored by live-events.js in store.gateway; this screen redraws on
// 'deepdive:update'. Every server string is rendered as a text node through h().
import { h, avatar, topbar, bottomNav, eyebrow, nextId } from '../ui.js';
import { decisionMessage } from '../live-events.js';
import { list, waiting } from './match-live.js';

function titled(title, items, label) {
  const body = list(items, label);
  return body ? [h('p', { class: 'eyebrow' }, title), body] : [];
}

/** The agent's call, in words: the outcome, then its reason and checks. */
export function decisionBlock(subject, dive, decided) {
  const decision = dive?.decision;
  const action = decided?.action || decision?.action;
  if (!action) return null;
  const confidence = typeof decision?.confidence === 'number' ? `${Math.round(decision.confidence * 100)}% sure` : null;
  return h('section', { class: 'card-gold deepdive-decision', 'aria-live': 'polite' },
    h('p', { class: 'eyebrow gold' }, 'Your agent’s decision'),
    h('p', { class: 'deepdive-outcome' }, decisionMessage(action, subject.id) || `Decision: ${action}`),
    decision?.reason ? h('p', null, decision.reason) : null,
    confidence ? h('p', { class: 'deepdive-confidence' }, confidence) : null,
    list(decision?.checks, 'Checks'));
}

function diveBody(subject, dive, decided) {
  const plan = dive.plan || {};
  const sources = (Array.isArray(dive.citations) ? dive.citations : [])
    .map((c) => (typeof c?.title === 'string' ? c.title : null)).filter(Boolean);
  return [
    h('p', { class: 'deepdive-summary' }, dive.summary),
    decisionBlock(subject, dive, decided),
    ...titled('Goals', plan.goals, 'Goals'),
    ...titled('What you can offer', plan.offers, 'Offers'),
    ...titled('Questions to ask', plan.questions, 'Questions'),
    ...titled('Watch-outs', plan.watch_outs, 'Watch-outs'),
    plan.opener ? h('p', { class: 'eyebrow' }, 'Opener') : null,
    plan.opener ? h('p', { class: 'deepdive-opener' }, plan.opener) : null,
    ...titled('Sources', sources, 'Sources'),
  ];
}

export function render(ctx) {
  const gateway = ctx.store.gateway || {};
  const subjectId = ctx.route.params.id || gateway.researching;
  const subject = (subjectId && ctx.person(subjectId)) || ctx.peer;
  const heading = nextId('deepdive-body');
  const body = h('div', { class: 'deepdive-body', 'aria-live': 'polite' });
  const card = h('section', { class: 'deepdive-card', 'aria-labelledby': heading },
    eyebrow('Research', { id: heading }), body);

  function draw() {
    const state = ctx.store.gateway || {};
    const dive = state.deepDives?.[subject.id];
    const decided = state.decisions?.[subject.id];
    card.setAttribute('lang', dive?.language || ctx.me.lang || 'en');
    if (ctx.mode !== 'live') {
      body.replaceChildren(waiting('Deep dives appear here in live mode.'));
    } else if (!dive) {
      body.replaceChildren(
        h('p', { class: 'deepdive-researching rp-pulse' }, `Researching ${subject.name}…`),
        decided ? decisionBlock(subject, null, decided) : null);
    } else {
      body.replaceChildren(...diveBody(subject, dive, decided).filter(Boolean));
    }
  }
  draw();
  ctx.onCleanup(ctx.bus.on('deepdive:update', (data) => {
    if (!data?.target || data.target === subject.id) draw();
  }));

  return h('div', { class: 'screen deepdive', lang: 'en' },
    topbar({ back: 'home', backLabel: 'Back to home', title: 'Deep dive' }),
    h('main', { class: 'scroll deepdive-main' },
      h('div', { class: 'row deepdive-who' },
        avatar(subject.initials, subject.tone, 44, 15),
        h('div', { class: 'grow stack', style: { gap: '1px' } },
          h('h2', { class: 'deepdive-name' }, subject.name),
          h('p', { class: 'muted' }, subject.role))),
      card),
    bottomNav('deepdive'));
}
