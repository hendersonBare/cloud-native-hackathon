// Placeholder: replaced by the profile screen port.
import { h, topbar, bottomNav } from '../ui.js';

export function render() {
  return h('div', { class: 'screen' },
    topbar({ title: "Agent identity" }),
    h('main', { class: 'scroll pad' }, h('p', { class: 'muted' }, 'Coming soon')),
    bottomNav('profile'),
  );
}
