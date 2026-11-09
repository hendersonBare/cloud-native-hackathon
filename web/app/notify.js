// Push-style notification banner at the top of the phone (like iOS). It is a
// polite live region with two real buttons: open (the whole banner) and
// dismiss. It never steals focus. Swiping it up also dismisses it.
// All text goes in through h(), so names and messages stay plain text.

import { h, icon } from './ui.js';

const SWIPE_DISMISS = -30;

/**
 * showNotification(root, { title, body, cta, avatarEl, onOpen, onDismiss })
 * Returns close(): removes the banner without calling either callback.
 */
export function showNotification(root, { title, body, cta, avatarEl, onOpen, onDismiss } = {}) {
  let closed = false;
  let startY = null;

  const close = () => {
    if (closed) return;
    closed = true;
    el.remove();
  };
  const open = () => { if (closed) return; close(); onOpen?.(); };
  const dismiss = () => { if (closed) return; close(); onDismiss?.(); };

  const main = h('button', { type: 'button', class: 'notice-main', onClick: open },
    h('span', { class: 'notice-app' },
      h('span', { class: 'notice-app-icon', 'aria-hidden': 'true' }, icon('agent', { size: 12, stroke: 2 })),
      h('span', { class: 'notice-app-name' }, 'Rapport'),
      h('span', { class: 'notice-time' }, 'now')),
    h('span', { class: 'notice-row' },
      avatarEl || null,
      h('span', { class: 'notice-text' },
        h('span', { class: 'notice-title' }, title || ''),
        body ? h('span', { class: 'notice-body' }, body) : null,
        cta ? h('span', { class: 'notice-cta' }, cta, icon('chevron', { size: 14, stroke: 2 })) : null)),
  );
  const dismissBtn = h('button', {
    type: 'button', class: 'notice-dismiss', 'aria-label': 'Dismiss notification', onClick: dismiss,
  }, icon('close', { size: 14, stroke: 2.2 }));

  const el = h('div', { class: 'notice', role: 'status', 'aria-live': 'polite' }, main, dismissBtn);

  el.addEventListener('pointerdown', (e) => { startY = e.clientY; });
  el.addEventListener('pointerup', (e) => {
    if (startY !== null && e.clientY - startY < SWIPE_DISMISS) dismiss();
    startY = null;
  });
  el.addEventListener('keydown', (e) => { if (e.key === 'Escape') dismiss(); });

  root.append(el);
  return close;
}
