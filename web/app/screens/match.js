// Placeholder: replaced by the match screen port.
import { h, topbar, bottomNav } from '../ui.js';

export function render() {
  return h('div', { class: 'screen' },
    topbar({ title: "It's a match" }),
    h('main', { class: 'scroll pad' }, h('p', { class: 'muted' }, 'Coming soon')),
    bottomNav('match'),
  );
}
