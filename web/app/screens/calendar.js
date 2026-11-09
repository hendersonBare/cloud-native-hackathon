// Placeholder: replaced by the calendar screen port.
import { h, topbar, bottomNav } from '../ui.js';

export function render() {
  return h('div', { class: 'screen' },
    topbar({ title: "Calendar" }),
    h('main', { class: 'scroll pad' }, h('p', { class: 'muted' }, 'Coming soon')),
    bottomNav('calendar'),
  );
}
