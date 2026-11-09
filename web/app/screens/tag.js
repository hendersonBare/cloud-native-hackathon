// Placeholder: replaced by the tag screen port.
import { h, topbar, bottomNav } from '../ui.js';

export function render() {
  return h('div', { class: 'screen' },
    topbar({ title: "Change a speaker" }),
    h('main', { class: 'scroll pad' }, h('p', { class: 'muted' }, 'Coming soon')),
    bottomNav('tag'),
  );
}
