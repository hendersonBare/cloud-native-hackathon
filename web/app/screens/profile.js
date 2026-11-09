// Agent identity, role-based memory access, and local CV metadata.
import { h, svg, topbar, bottomNav, eyebrow, nextId } from '../ui.js';

const CONTENT = {
  'acme.ava': {
    name: 'Ava',
    title: 'Solutions Engineer',
    org: 'Acme Observability',
    team: 'Solutions team',
    lookingFor: 'Healthcare design partners',
    openTo: 'Coffee chats',
    represents: 'Your agent represents your work in zero-code eBPF tracing and healthcare observability.',
    topics: ['eBPF tracing', 'OpenTelemetry', 'Healthcare', 'Observability'],
    workingOn: 'Working on: a hospital network rollout with 40% faster incidents',
  },
  'bluefin.bo': {
    name: 'Bo',
    title: 'Platform Lead',
    org: 'Bluefin Health',
    team: 'Platform team',
    lookingFor: 'Zero-code tracing',
    openTo: 'Coffee chats',
    represents: 'Tu agente representa tu trabajo en la plataforma hospitalaria y el tracing sin cambios de código.',
    topics: ['eBPF tracing', 'OpenTelemetry', 'HIPAA review', 'Observability cost'],
    workingOn: 'Trabajando en: la migración de la plataforma hospitalaria',
    lang: 'es',
  },
};

const ROLES = [
  { id: 'engineer', label: 'Engineer', name: 'Platform engineer', access: [false, false, true, true] },
  { id: 'manager', label: 'Eng manager', name: 'Engineering manager', access: [false, true, true, true] },
  { id: 'admin', label: 'Org admin', name: 'Org admin', access: [true, true, true, true] },
];

export function render(ctx) {
  const content = CONTENT[ctx.me.id] || CONTENT['acme.ava'];
  const st = ctx.store.profile || (ctx.store.profile = {});
  if (!ROLES.some((role) => role.id === st.role)) st.role = 'engineer';
  let visibility = st.cv?.visibility || st.visibility || 'shareable';
  const roleHeading = h('h1', { class: 'serif profile-role-name' });
  const accessBody = h('tbody');
  const roleButtons = new Map();
  const roleId = nextId('profile-role');
  const contextId = nextId('profile-context');
  const accessId = nextId('profile-access');
  const visibilityId = nextId('profile-visibility');
  const fileId = nextId('profile-cv');

  function drawRole() {
    const selected = ROLES.find((role) => role.id === st.role);
    roleHeading.textContent = selected.name;
    for (const [id, button] of roleButtons) {
      button.setAttribute('aria-pressed', String(id === st.role));
    }
    const levels = [`Organization · ${content.org}`, 'Infrastructure', 'Platform team', 'Personal'];
    accessBody.replaceChildren(...levels.map((name, index) => h('tr', {
      class: `profile-level profile-level-${index}${selected.access[index] ? ' profile-writable' : ''}`,
    },
    h('th', { scope: 'row' }, h('span', { class: 'profile-level-name' },
      h('span', { class: 'profile-level-dot', 'aria-hidden': 'true' }), name)),
    h('td', null, selected.access[index] ? 'Read & write' : 'Read'))));
  }

  const picker = h('div', { class: 'profile-role-picker', role: 'group', 'aria-label': 'Role' },
    ROLES.map((role) => {
      const button = h('button', {
        type: 'button',
        onClick: () => { st.role = role.id; drawRole(); },
      }, role.label);
      roleButtons.set(role.id, button);
      return button;
    }));
  drawRole();

  const rings = svg([109, 84, 59, 34].map((r) => ['circle', { cx: 110, cy: 110, r }]), {
    size: 220, viewBox: '0 0 220 220', stroke: 1,
  });
  rings.setAttribute('class', 'profile-pass-rings');
  const pass = h('section', { class: 'profile-pass', 'aria-label': 'Agent pass' },
    rings,
    eyebrow('Agent pass · KubeCon', { tag: 'p', gold: true }),
    h('div', { class: 'profile-identity' },
      roleHeading,
      h('p', { class: 'profile-identity-name' }, `${content.name} · ${content.title}`),
      h('p', { class: 'profile-identity-org' }, `${content.org} · ${content.team}`),
      h('p', { class: 'profile-represents', lang: content.lang }, content.represents)),
    h('div', { class: 'profile-pass-access' },
      h('div', { class: 'profile-access-detail' }, eyebrow('Looking for', { tag: 'p' }),
        h('p', { class: 'profile-access-value' }, content.lookingFor)),
      h('div', { class: 'profile-access-detail' }, eyebrow('Open to', { tag: 'p' }),
        h('p', { class: 'profile-access-value' }, content.openTo))));

  function saveCV(filename) {
    st.cv = { filename, visibility };
    ctx.bus.emitLocal('ui:context', { filename, visibility });
  }
  const fileInput = h('input', {
    id: fileId,
    class: 'profile-file-input',
    type: 'file',
    accept: '.pdf,.md,.txt',
    'aria-label': 'Replace CV',
    onChange: (event) => {
      const file = event.target.files?.[0];
      if (!file) return;
      // Keep metadata only: never read or retain the file's contents.
      saveCV(file.name);
      event.target.value = '';
    },
  });
  const visibilityChoices = h('fieldset', { class: 'profile-visibility' },
    h('legend', { class: 'visually-hidden' }, 'CV visibility'),
    [
      ['shareable', 'Share with people I meet'],
      ['private', 'Private to my agent'],
    ].map(([value, label]) => h('label', { class: 'profile-visibility-choice' },
      h('input', {
        type: 'radio', name: visibilityId, value, checked: visibility === value,
        onChange: (event) => {
          if (!event.target.checked) return;
          visibility = value;
          st.visibility = value;
          if (st.cv) saveCV(st.cv.filename);
        },
      }), h('span', null, label))));
  const context = h('section', { class: 'profile-section', 'aria-labelledby': contextId },
    eyebrow('Context it carries', { id: contextId }),
    h('div', { class: 'profile-context-card' },
      h('div', { class: 'profile-context-heading' },
        h('span', { class: 'profile-file-icon', 'aria-hidden': 'true' }, svg([
          ['path', { d: 'M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z' }],
          ['path', { d: 'M14 3v5h5M9 13h6M9 17h6' }],
        ], { size: 19 })),
        h('p', { class: 'profile-context-title' }, 'CV'),
        h('label', { class: 'profile-file-control', for: fileId }, 'Replace', fileInput)),
      h('ul', { class: 'profile-topics', 'aria-label': 'Context topics' },
        content.topics.map((topic) => h('li', { class: 'pill' }, topic))),
      h('p', { class: 'profile-working-on', lang: content.lang }, content.workingOn),
      visibilityChoices));

  return h('div', { class: 'screen profile' },
    topbar({
      back: 'home', backLabel: 'Back to home', title: 'Agent identity', titleTag: 'p',
      right: h('button', {
        type: 'button', class: 'profile-edit', 'aria-label': 'Edit role',
        onClick: () => roleButtons.get(st.role).focus(),
      }, 'Edit'),
    }),
    h('main', { class: 'scroll profile-main' },
      pass,
      context,
      h('section', { class: 'profile-section', 'aria-labelledby': roleId },
        eyebrow('Role', { id: roleId }), picker),
      h('section', { class: 'profile-section', 'aria-labelledby': accessId },
        h('div', { class: 'profile-access-heading' },
          eyebrow('Memory access', { id: accessId })),
        h('div', { class: 'profile-access-table', 'aria-live': 'polite' },
          h('table', { 'aria-labelledby': accessId }, accessBody)))),
    bottomNav('profile'));
}
