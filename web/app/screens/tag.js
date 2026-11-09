// Change a speaker: a transcript preview behind the speaker picker sheet.
import { h, topbar, nextId } from '../ui.js';
import { PEOPLE } from '../data.js';

const CONTENT = {
  'acme.ava': {
    otherId: 'kestrel.mia',
    detail: 'Platform Engineer · Kestrel Robotics',
    title: 'Hallway conversation',
    clock: '04:12',
    transcript: 'We want tracing with no code changes. Cost is the main concern for our hospital platform migration.',
    lang: 'en',
  },
  'bluefin.bo': {
    otherId: 'lumenly.priya',
    detail: 'Head of Infrastructure · Lumenly Energy',
    title: 'Platform track Q&A',
    clock: '01:38',
    transcript: 'Con eBPF podemos capturar trazas sin cambiar el código. En una red hospitalaria, redujimos el tiempo de los incidentes un 40%.',
    lang: 'es',
  },
};

export function render(ctx) {
  const content = CONTENT[ctx.me.id] || CONTENT['acme.ava'];
  const options = [
    { ...ctx.peer, detail: "Suggested · voice matches today's talk" },
    { ...PEOPLE[content.otherId], detail: content.detail },
  ];
  const saved = ctx.store.speakers?.s2;
  const savedOption = saved && options.find((p) => p.id === saved.personaId && p.name === saved.name);
  let pick = savedOption?.id || (saved?.name?.trim() ? 'custom' : ctx.peer.id);
  let typed = pick === 'custom' ? saved.name : '';
  let research = true;

  const headingId = nextId('tag-heading');
  const inputId = nextId('tag-name');
  const researchId = nextId('tag-research');
  const researchDetailId = nextId('tag-research-detail');
  const previewAvatar = h('span', { class: 'avatar tag-transcript-avatar', 'aria-hidden': 'true' });
  const previewName = h('span', { class: 'tag-transcript-name' });
  const previewTag = h('span', { class: 'tag-status' });
  const willName = h('span', { class: 'tag-will-name' });
  const willTag = h('span', { class: 'tag-status' });

  function chosen() {
    const custom = pick === 'custom' && typed.trim().length > 0;
    const p = options.find((option) => option.id === pick) || options[0];
    const name = custom ? typed.trim() : p.name;
    return {
      name,
      personaId: custom ? null : p.id,
      initials: custom ? name.split(/\s+/).slice(0, 2).map((word) => word.charAt(0)).join('').toUpperCase() : p.initials,
      tone: custom ? 'steel' : p.tone,
      edited: name !== ctx.peer.name,
    };
  }

  const radios = options.map((p, index) => h('button', {
    type: 'button',
    class: 'tag-option',
    role: 'radio',
    'aria-checked': 'false',
    tabindex: '-1',
    onClick: () => { pick = p.id; draw(); },
    onKeydown: (event) => {
      let next;
      if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % options.length;
      else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index + options.length - 1) % options.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = options.length - 1;
      else return;
      event.preventDefault();
      pick = options[next].id;
      draw();
      radios[next].focus();
    },
  },
  h('span', { class: `avatar tag-option-avatar tone-${p.tone}`, 'aria-hidden': 'true' }, p.initials),
  h('span', { class: 'tag-option-copy' },
    h('span', { class: 'tag-option-name' }, p.name),
    h('span', { class: 'tag-option-detail' }, p.detail)),
  h('span', { class: 'tag-radio-ring', 'aria-hidden': 'true' }, h('span', { class: 'tag-radio-dot' })),
  ));

  const input = h('input', {
    id: inputId,
    class: 'tag-name-input',
    type: 'text',
    placeholder: 'Type a name',
    value: typed,
    autocomplete: 'off',
    onInput: (event) => {
      typed = event.target.value;
      pick = typed.trim() ? 'custom' : ctx.peer.id;
      draw();
    },
  });

  const researchSwitch = h('button', {
    type: 'button',
    class: 'tag-research',
    role: 'switch',
    'aria-checked': 'true',
    'aria-labelledby': researchId,
    'aria-describedby': researchDetailId,
    onClick: () => { research = !research; draw(); },
  },
  h('span', { class: 'tag-option-copy' },
    h('span', { id: researchId, class: 'tag-option-name' }, 'Have my agent brief me on them'),
    h('span', { id: researchDetailId, class: 'tag-option-detail' }, 'Public professional sources only')),
  h('span', { class: 'tag-switch-track', 'aria-hidden': 'true' }, h('span', { class: 'tag-switch-knob' })),
  );

  const save = h('button', {
    type: 'button',
    class: 'btn btn-primary tag-save',
    onClick: () => {
      const { name, personaId, edited } = chosen();
      ctx.store.speakers = { ...(ctx.store.speakers || {}), s2: { name, personaId, edited } };
      ctx.go(research ? 'person' : 'live');
    },
  });

  function draw() {
    const selection = chosen();
    previewAvatar.textContent = selection.initials;
    previewAvatar.className = `avatar tag-transcript-avatar tone-${selection.tone}`;
    previewName.textContent = selection.name;
    previewTag.textContent = willTag.textContent = selection.edited ? 'Edited' : 'Auto';
    willName.textContent = selection.name;
    radios.forEach((radio, index) => {
      const on = selection.personaId === options[index].id;
      radio.setAttribute('aria-checked', String(on));
      radio.tabIndex = on || (selection.personaId === null && index === 0) ? 0 : -1;
    });
    input.classList.toggle('tag-custom', selection.personaId === null);
    researchSwitch.setAttribute('aria-checked', String(research));
    save.textContent = research ? 'Save & brief me' : 'Save name';
  }

  draw();

  return h('div', { class: 'screen tag' },
    topbar({
      back: 'live', backLabel: 'Back to transcript', title: 'Capture', titleTag: 'p',
      right: h('span', { class: 'tag-recording' },
        h('span', { class: 'tag-recording-dot', 'aria-hidden': 'true' }), `REC ${content.clock}`),
    }),
    h('div', { class: 'tag-transcript', 'aria-hidden': 'true' },
      h('div', { class: 'tag-transcript-heading' },
        h('p', { class: 'serif tag-transcript-title' }, content.title),
        h('p', { class: 'tag-transcript-subtitle' }, 'Expo hall · started 2:41 PM')),
      h('div', { class: 'tag-transcript-segment' }, previewAvatar,
        h('div', { class: 'tag-transcript-copy' },
          h('div', { class: 'tag-transcript-speaker' }, previewName, previewTag,
            h('span', { class: 'tag-transcript-time' }, '2:41 PM')),
          h('p', { class: 'tag-transcript-text', lang: content.lang }, content.transcript))),
    ),
    h('div', { class: 'tag-dimmer', 'aria-hidden': 'true' }),
    // This routed dialog is non-modal so the transcript back link stays operable.
    h('section', { class: 'tag-sheet', role: 'dialog', 'aria-labelledby': headingId },
      h('span', { class: 'tag-grabber', 'aria-hidden': 'true' }),
      h('div', { class: 'scroll tag-body' },
        h('div', { class: 'tag-intro' },
          h('p', { class: 'eyebrow gold' }, 'Named automatically'),
          h('h1', { id: headingId, class: 'serif tag-heading' }, "Who's ", h('em', null, 'speaking?')),
          h('p', { class: 'tag-description' }, 'Not the right person? Pick or type a name. Every segment from this voice updates.')),
        h('p', { class: 'tag-will-show', 'aria-live': 'polite', 'aria-atomic': 'true' },
          h('span', { class: 'tag-will-label' }, 'Will show as'), willName, willTag),
        h('div', { class: 'tag-options', role: 'radiogroup', 'aria-label': 'Speaker' }, radios),
        h('div', { class: 'tag-custom-field' },
          h('label', { for: inputId }, 'Someone else'), input),
        researchSwitch,
      ),
      h('div', { class: 'tag-actions' }, h('a', { class: 'btn', href: '#/live' }, 'Cancel'), save),
    ),
  );
}
