// Placeholder: replaced by the exchange screen port.
import { h, topbar, bottomNav } from '../ui.js';

export function render() {
  return h('div', { class: 'screen' },
    topbar({ title: "Agents in conversation" }),
    h('main', { class: 'scroll pad' }, h('p', { class: 'muted' }, 'Coming soon')),
    bottomNav('exchange'),
  );
}
