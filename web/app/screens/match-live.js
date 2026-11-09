// Match screen in live mode: the briefs come from the gateway (private_brief, shared_brief),
// not from the scripted demo copy. Both sections redraw themselves when a brief arrives.
// All strings are rendered as text nodes through h().
import { h, icon, eyebrow, nextId } from '../ui.js';

export function list(items, label) {
  const rows = (Array.isArray(items) ? items : []).filter((item) => typeof item === 'string' && item);
  return rows.length ? h('ul', { class: 'match-live-list', 'aria-label': label }, rows.map((t) => h('li', null, t))) : null;
}

export function waiting(text) {
  return h('p', { class: 'match-live-waiting' }, text);
}

function privateBody(brief) {
  if (!brief) return [waiting('Your agent is still writing this brief.')];
  const starters = list(brief.conversation_starters, 'Conversation starters');
  return [
    h('p', { class: 'match-live-headline' }, brief.headline),
    list(brief.talking_points, 'Talking points'),
    brief.watch_outs?.length ? h('p', { class: 'eyebrow' }, 'Watch-outs') : null,
    list(brief.watch_outs, 'Watch-outs'),
    starters ? h('p', { class: 'eyebrow' }, 'Conversation starters') : null,
    starters,
  ];
}

export function livePrivateBrief(ctx) {
  const heading = nextId('match-private');
  const body = h('div', { class: 'match-live-body' });
  const section = h('section', {
    class: 'card-gold match-private', 'aria-labelledby': heading, 'aria-live': 'polite', lang: ctx.me.lang || 'en',
  },
  h('h2', { id: heading, class: 'match-private-heading', lang: 'en' },
    icon('lock', { size: 18 }), 'Private brief · only you see this'),
  body);
  function draw() {
    const brief = ctx.store.gateway?.privateBrief;
    section.setAttribute('lang', brief?.language || ctx.me.lang || 'en');
    body.replaceChildren(...privateBody(brief).filter(Boolean));
  }
  draw();
  ctx.onCleanup(ctx.bus.on('brief:update', draw));
  return section;
}

function sharedBody(brief) {
  if (!brief) return [waiting('The shared brief appears when both agents finish.')];
  const items = (brief.shared_items || []).map((item) => h('li', null,
    h('strong', null, item.title), item.summary ? ` — ${item.summary}` : ''));
  const declined = (brief.declined || []).map((item) => h('li', null,
    `${item.topic} was declined`, item.rule_id ? ` · ${item.rule_id}` : ''));
  const followups = (brief.followups || []).map((item) => h('li', null, item.text));
  const interests = list(brief.mutual_interests, 'Shared interests');
  return [
    h('p', { class: 'match-live-headline' }, brief.summary),
    interests,
    items.length ? h('p', { class: 'eyebrow' }, 'Shared with you') : null,
    items.length ? h('ul', { class: 'match-live-list', 'aria-label': 'Shared items' }, items) : null,
    declined.length ? h('p', { class: 'eyebrow' }, 'Declined by policy') : null,
    declined.length ? h('ul', { class: 'match-live-list', 'aria-label': 'Declined requests' }, declined) : null,
    followups.length ? h('p', { class: 'eyebrow' }, 'Follow-ups') : null,
    followups.length ? h('ul', { class: 'match-live-list', 'aria-label': 'Follow-ups' }, followups) : null,
  ];
}

export function liveSharedBrief(ctx) {
  const heading = nextId('match-shared');
  const body = h('div', { class: 'match-live-body' });
  const section = h('section', {
    class: 'match-summary match-live-shared', 'aria-labelledby': heading, 'aria-live': 'polite',
    lang: ctx.me.lang || 'en',
  },
  eyebrow('Shared brief', { id: heading }),
  body);
  function draw() {
    const brief = ctx.store.gateway?.sharedBrief;
    section.setAttribute('lang', brief?.language || ctx.me.lang || 'en');
    body.replaceChildren(...sharedBody(brief).filter(Boolean));
  }
  draw();
  ctx.onCleanup(ctx.bus.on('brief:update', draw));
  return section;
}
