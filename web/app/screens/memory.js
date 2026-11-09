// Memory: hierarchical search, cited answers, the context your agent carries (and a way to
// change it), and arriving transcripts.
import { h, icon, bottomNav, nextId } from '../ui.js';
import { currentContext, saveContext, MAX_NOTE_CHARS, FILE_TYPES } from '../context-model.js';

const CONTENT = {
  'acme.ava': {
    questions: [
      {
        question: 'What did we promise Bluefin?',
        keywords: ['bluefin', 'promise', 'questionnaire'],
        answer: 'Sam promised Kai the security questionnaire before the pilot starts. Bluefin is also evaluating a competitor, and the budget decision is in Q1.',
        citations: [{ memory_id: 'acme-note-0007', title: 'Call notes: Bluefin pilot (March)' }],
        level: 2,
      },
      {
        question: "What's our hospital case study?",
        keywords: ['hospital', 'case study', 'incidents'],
        answer: 'Our hospital network rollout cut incident time by 40% with eBPF tracing.',
        citations: [{ memory_id: 'acme-doc-0002', title: 'Case study: hospital network (40% faster incidents)' }],
        level: 2,
      },
    ],
    recent: [
      { title: 'Hallway with Bo', scope: 'Personal', status: 'Indexing' },
      { title: 'eBPF tracing keynote', scope: 'Team', status: 'Indexed' },
    ],
  },
  'bluefin.bo': {
    questions: [
      {
        question: 'What do we think of Acme?',
        keywords: ['acme', 'vendor', 'evaluation'],
        answer: "We like Acme's zero-code eBPF approach. Kai must sign off on HIPAA, and cost is the main concern.",
        citations: [{ memory_id: 'bluefin-note-0003', title: 'Vendor evaluation: Acme' }],
        level: 2,
      },
      {
        question: 'What are our platform requirements?',
        keywords: ['requirements', 'platform', 'tracing'],
        answer: 'We need tracing with no code changes for our hospital platform migration. Cost is the main concern, and Kai must sign off on HIPAA.',
        citations: [{ memory_id: 'bluefin-doc-0001', title: 'Platform requirements (summary)' }],
        level: 2,
      },
    ],
    recent: [
      { title: 'Hallway with Ava', scope: 'Personal', status: 'Indexing' },
      { title: 'Platform track Q&A', scope: 'Team', status: 'Indexed' },
    ],
  },
};

const NOT_FOUND = "I couldn't find that in the memory you can access.";
const OUTSIDE_SCOPE = 'That memory is outside the selected scope. Include Platform team to search it.';
// Scope index 3 = Personal only.
const PERSONAL_SCOPE = 3;
// Own profile records: profile-<persona_id>-<visibility>[-<n>] (SPEC 4.3). Citation has no owner
// field and other kinds (encounter_summary, followup) don't encode one, so only these are provable.
const OWN_PROFILE_SUFFIX = /^(shareable|private)(-\d+)?$/;

function isOwnProfile(cite, personaId) {
  if (cite.kind !== 'profile' || typeof personaId !== 'string' || !personaId) return false;
  const prefix = `profile-${personaId}-`;
  return cite.memory_id.startsWith(prefix) && OWN_PROFILE_SUFFIX.test(cite.memory_id.slice(prefix.length));
}

function scopeLabel(scope) {
  const included = ['Personal', 'Team', 'Infrastructure', 'Organization'].slice(0, 4 - scope);
  return included.length === 1 ? 'Personal memory only'
    : `${included.slice(0, -1).join(', ')} + ${included.at(-1)}`;
}

/**
 * Turn a gateway AskAnswer into what the card shows for the selected scope.
 * AskRequest has no scope field, so the gateway can't narrow the search. Fail closed:
 * keep known team memories out of narrower scopes, and in Personal show an answer only
 * if every citation is provably the viewer's own (their own profile records).
 */
export function liveResult(data, scope, content, fallback, personaId) {
  const citations = Array.isArray(data?.citations) ? data.citations.flatMap((cite) => {
    const id = cite?.memory_id;
    return typeof id === 'string' && typeof cite?.title === 'string'
      ? [{ memory_id: id, title: cite.title, kind: cite.kind }] : [];
  }) : [];
  const outside = content.questions.some((item) => scope > item.level
    && item.citations.some((known) => citations.some((cite) => cite.memory_id === known.memory_id)));
  const provablyPersonal = citations.length > 0 && citations.every((cite) => isOwnProfile(cite, personaId));
  if (fallback.answer === OUTSIDE_SCOPE || outside || (scope === PERSONAL_SCOPE && !provablyPersonal)) {
    return { answer: OUTSIDE_SCOPE, citations: [] };
  }
  return { answer: data.answer, citations: citations.map(({ memory_id, title }) => ({ memory_id, title })) };
}

function mockAnswer(content, question, scope) {
  const query = question.toLowerCase();
  const match = content.questions.find((item) => item.keywords.some((word) => query.includes(word)));
  if (!match) return { answer: NOT_FOUND, citations: [] };
  if (scope > match.level) return { answer: OUTSIDE_SCOPE, citations: [] };
  return { answer: match.answer, citations: match.citations };
}

export function render(ctx) {
  const content = CONTENT[ctx.me.id] || CONTENT['acme.ava'];
  const st = ctx.store.memory || (ctx.store.memory = {
    scope: 2, listening: false, draft: '', question: content.questions[0].question,
  });
  if (!Number.isInteger(st.scope) || st.scope < 0 || st.scope > 3) st.scope = 2;
  if (!st.question) st.question = content.questions[0].question;
  if (!st.result) st.result = mockAnswer(content, st.question, st.scope);

  let pending = false;
  let disposed = false;
  let request = 0;
  let controller;
  const timers = new Map();
  function delay(ms) {
    return new Promise((resolve) => {
      const timer = setTimeout(() => { timers.delete(timer); resolve(); }, ms);
      timers.set(timer, resolve);
    });
  }
  function cancel() {
    request += 1;
    controller?.abort();
    for (const [timer, resolve] of timers) { clearTimeout(timer); resolve(); }
    timers.clear();
  }
  ctx.onCleanup(() => { disposed = true; cancel(); });

  const inputId = nextId('memory-question');
  const scopeId = nextId('memory-scope');
  const recentId = nextId('memory-recent');
  const input = h('input', {
    id: inputId, class: 'memory-input', type: 'search', placeholder: 'Ask your memory',
    required: true, autocomplete: 'off', maxlength: 500, onInput: () => { st.draft = input.value; },
  });
  input.value = st.draft;
  const waves = h('span', { class: 'memory-waves', 'aria-hidden': 'true', hidden: true },
    Array.from({ length: 4 }, () => h('span', { class: 'rp-wave' })),
  );
  const mic = h('button', {
    type: 'button', class: 'memory-mic', 'aria-label': 'Ask by voice', 'aria-pressed': 'false',
    onClick: () => { st.listening = !st.listening; drawMic(); },
  });
  const form = h('form', {
    class: 'memory-ask', 'aria-label': 'Ask your memory',
    onSubmit: (event) => { event.preventDefault(); askSafely(input.value); },
  },
  icon('search', { size: 18, stroke: 1.9 }),
  h('label', { class: 'visually-hidden', for: inputId }, 'Ask your memory'),
  input, waves,
  h('button', { type: 'submit', class: 'memory-submit', 'aria-label': 'Submit question' },
    icon('upload', { size: 19, stroke: 1.9 })),
  mic);

  function drawMic() {
    form.classList.toggle('is-listening', !!st.listening);
    waves.hidden = !st.listening;
    input.placeholder = st.listening ? 'Listening…' : 'Ask your memory';
    mic.setAttribute('aria-pressed', String(!!st.listening));
    mic.setAttribute('aria-label', st.listening ? 'Stop listening' : 'Ask by voice');
    mic.replaceChildren(icon(st.listening ? 'stop' : 'mic', { size: st.listening ? 16 : 20, stroke: 1.9 }));
  }

  const answerRegion = h('section', {
    class: 'memory-answer card', 'aria-label': 'Answer', 'aria-live': 'polite', 'aria-atomic': 'true',
  });
  function drawAnswer() {
    const result = st.result;
    answerRegion.replaceChildren(...[
      h('p', { class: 'memory-question' }, st.question),
      h('p', { class: 'memory-answer-text', lang: 'en' }, pending ? 'Thinking…' : result.answer),
      !pending && result.citations.length ? h('div', { class: 'memory-citations', 'aria-label': 'Sources' },
        result.citations.map((cite) => h('span', { class: 'memory-citation' },
          h('span', { class: 'memory-citation-title' }, cite.title),
          h('span', { class: 'memory-citation-id' }, cite.memory_id),
        ))) : null,
      h('p', { class: 'memory-searched' }, `${pending ? 'Searching' : 'Searched'} ${scopeLabel(st.scope)}`),
    ].filter(Boolean));
  }

  function askSafely(value) {
    ask(value).catch((err) => console.warn('Memory ask failed', err?.name || 'Error'));
  }

  async function ask(value) {
    const question = value.trim();
    if (!question || disposed) return;
    cancel();
    const current = request;
    const scope = st.scope;
    st.draft = question;
    st.question = question;
    input.value = question;
    pending = true;
    drawAnswer();
    const fallback = mockAnswer(content, question, scope);
    // Navigating away while a request is pending still leaves a coherent card.
    st.result = fallback;
    let result = fallback;
    const thinking = delay(700);
    if (ctx.mode === 'live') {
      const activeController = new AbortController();
      controller = activeController;
      const timeout = setTimeout(() => activeController.abort(), 10000);
      timers.set(timeout, () => {});
      try {
        const response = await fetch('/api/ask', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ persona_id: ctx.me.id, question }), signal: activeController.signal,
        });
        if (!response.ok) throw new Error('Memory request failed');
        const data = await response.json();
        if (typeof data?.answer !== 'string' || !data.answer.trim()) throw new Error('Missing answer');
        result = liveResult(data, scope, content, fallback, ctx.me.id);
      } catch {
        result = fallback;
      } finally {
        clearTimeout(timeout);
        timers.delete(timeout);
      }
    }
    await thinking;
    if (disposed || current !== request) return;
    pending = false;
    st.result = result;
    drawAnswer();
  }

  const definitions = [
    [`Organization · ${ctx.me.orgName}`, 'Public notes'],
    ['Infrastructure', 'Summaries'], ['Platform team', 'Shared'], ['Personal', 'Only you'],
  ];
  const scopeButtons = definitions.map(([name], index) => h('button', {
    type: 'button', class: `memory-level memory-level-${index}`, 'aria-pressed': 'false',
    onClick: () => {
      if (st.scope === index) return;
      st.scope = index;
      drawScope();
      const draft = input.value;
      askSafely(st.question);
      st.draft = draft;
      input.value = draft;
    },
  },
  h('span', { class: 'memory-level-dot', 'aria-hidden': 'true' }),
  h('span', { class: 'memory-level-name' }, name),
  h('span', { class: 'memory-level-detail' }),
  ));
  function drawScope() {
    scopeButtons.forEach((button, index) => {
      button.setAttribute('aria-pressed', String(index === st.scope));
      button.classList.toggle('is-included', index >= st.scope);
      button.lastElementChild.textContent = index >= st.scope ? definitions[index][1] : 'Not searched';
    });
  }

  // Your context: what your agent carries about you, and an editor to change it.
  const contextId = nextId('memory-context');
  const contextBodyId = nextId('memory-context-body');
  const noteId = nextId('memory-context-note');
  const fileId = nextId('memory-context-file');
  const visibilityName = nextId('memory-context-visibility');
  const edit = { open: false, saving: false, file: null, status: '', error: false };
  const contextBody = h('div', { id: contextBodyId, class: 'memory-context card' });
  const editButton = h('button', {
    type: 'button', class: 'memory-context-edit', 'aria-controls': contextBodyId, 'aria-expanded': 'false',
    onClick: () => (edit.open ? closeEditor() : openEditor()),
  });

  function openEditor() {
    const now = currentContext(ctx);
    st.contextDraft ??= now.note;
    st.contextVisibility ??= now.visibility;
    Object.assign(edit, { open: true, file: null, status: '', error: false });
    drawContext();
    contextBody.querySelector('textarea')?.focus();
  }
  function closeEditor(status = '') {
    Object.assign(edit, { open: false, saving: false, file: null, status, error: false });
    st.contextDraft = undefined;
    st.contextVisibility = undefined;
    drawContext();
    editButton.focus();
  }

  async function submitContext() {
    if (edit.saving) return;
    edit.saving = true;
    edit.status = 'Saving…';
    edit.error = false;
    drawContext();
    const result = await saveContext(ctx, {
      text: st.contextDraft, file: edit.file, visibility: st.contextVisibility,
    });
    if (disposed) return;
    if (result.ok) {
      closeEditor(result.savedTo === 'agent' ? 'Saved. Your agent carries this now.' : 'Saved on this phone.');
      return;
    }
    Object.assign(edit, { saving: false, status: result.message, error: true });
    drawContext();
  }

  function contextView() {
    const now = currentContext(ctx);
    return [
      h('ul', { class: 'memory-context-topics', 'aria-label': 'Topics your agent carries' },
        now.topics.map((topic) => h('li', { class: 'pill' }, topic))),
      now.workingOn ? h('p', { class: 'memory-context-working', lang: now.lang }, now.workingOn) : null,
      now.note ? h('div', { class: 'memory-context-note' },
        h('p', { class: 'eyebrow' }, 'Your note'),
        h('p', { class: 'memory-context-note-text' }, now.note)) : null,
      now.filename ? h('p', { class: 'memory-context-file' },
        icon('file', { size: 16, stroke: 1.8 }), h('span', null, now.filename)) : null,
      h('p', { class: 'memory-context-meta' },
        icon(now.visibility === 'private' ? 'lock' : 'user', { size: 14, stroke: 1.9 }),
        h('span', null, now.visibility === 'private' ? 'Private to your agent' : 'Shared with people you meet')),
    ].filter(Boolean);
  }

  function contextEditor() {
    const note = h('textarea', {
      id: noteId, class: 'memory-context-input', rows: 5, maxlength: MAX_NOTE_CHARS,
      placeholder: 'What you’re working on, who you want to meet, what your agent should know',
      disabled: edit.saving,
      onInput: () => { st.contextDraft = note.value; count.textContent = counter(note.value); },
    });
    note.value = st.contextDraft || '';
    const count = h('span', { class: 'memory-context-count', 'aria-hidden': 'true' }, counter(note.value));
    const fileInput = h('input', {
      id: fileId, class: 'visually-hidden', type: 'file', accept: FILE_TYPES.join(','), disabled: edit.saving,
      onChange: (event) => {
        edit.file = event.target.files?.[0] || null;
        edit.status = '';
        edit.error = false;
        drawContext();
      },
    });
    const visibility = h('fieldset', { class: 'memory-context-visibility' },
      h('legend', { class: 'visually-hidden' }, 'Who can see this'),
      [['shareable', 'Share with people I meet'], ['private', 'Private to my agent']].map(([value, label]) =>
        h('label', { class: 'memory-context-choice' },
          h('input', {
            type: 'radio', name: visibilityName, value, checked: st.contextVisibility === value, disabled: edit.saving,
            onChange: (event) => { if (event.target.checked) st.contextVisibility = value; },
          }),
          h('span', null, label))));
    return [h('form', {
      class: 'memory-context-form', 'aria-label': 'Edit your context',
      onSubmit: (event) => { event.preventDefault(); submitContext(); },
    },
    h('label', { class: 'memory-context-label', for: noteId }, 'What should your agent know about you?'),
    note,
    h('div', { class: 'memory-context-row' },
      h('label', { class: 'memory-context-attach', for: fileId },
        icon('file', { size: 16, stroke: 1.8 }),
        h('span', null, edit.file ? edit.file.name : 'Attach a CV or notes'), fileInput),
      count),
    visibility,
    h('p', { class: `memory-context-status${edit.error ? ' is-error' : ''}`, role: 'status' }, edit.status),
    h('div', { class: 'memory-context-actions' },
      h('button', {
        type: 'button', class: 'memory-context-cancel', disabled: edit.saving, onClick: () => closeEditor(),
      }, 'Cancel'),
      h('button', { type: 'submit', class: 'memory-context-save', disabled: edit.saving },
        edit.saving ? 'Saving…' : 'Save')))];
  }

  function counter(value) {
    return `${value.length.toLocaleString('en-US')} / ${MAX_NOTE_CHARS.toLocaleString('en-US')}`;
  }

  function drawContext() {
    editButton.setAttribute('aria-expanded', String(edit.open));
    editButton.replaceChildren(
      icon(edit.open ? 'close' : 'edit', { size: 15, stroke: 1.9 }), h('span', null, edit.open ? 'Close' : 'Edit'));
    contextBody.classList.toggle('is-editing', edit.open);
    contextBody.replaceChildren(...(edit.open ? contextEditor() : [
      ...contextView(),
      edit.status ? h('p', { class: 'memory-context-status', role: 'status' }, edit.status) : null,
    ].filter(Boolean)));
  }

  drawMic();
  drawScope();
  drawAnswer();
  drawContext();
  return h('div', { class: 'screen memory', lang: 'en' },
    h('main', { class: 'scroll memory-main' },
      h('h1', { class: 'serif memory-title' }, 'Memory'),
      form,
      h('div', { class: 'memory-suggestions', role: 'group', 'aria-label': 'Suggested questions' },
        content.questions.map((item) => h('button', {
          type: 'button', class: 'memory-suggestion', onClick: () => { askSafely(item.question); },
        }, icon('sparkle', { size: 14, stroke: 1.9 }), h('span', null, item.question))),
      ),
      answerRegion,
      h('section', { class: 'memory-section', 'aria-labelledby': contextId },
        h('div', { class: 'memory-section-head' },
          h('h2', { id: contextId, class: 'eyebrow' }, 'Your context'),
          editButton,
        ),
        contextBody,
      ),
      h('section', { class: 'memory-section', 'aria-labelledby': scopeId },
        h('div', { class: 'memory-section-head' },
          h('h2', { id: scopeId, class: 'eyebrow' }, 'Search scope'),
        ),
        h('div', { class: 'memory-levels', role: 'group', 'aria-label': 'Search scope' }, scopeButtons),
      ),
      h('section', { class: 'memory-section', 'aria-labelledby': recentId },
        h('h2', { id: recentId, class: 'eyebrow' }, 'Arriving from transcripts'),
        h('div', { class: 'memory-recent' }, content.recent.map((item) => h('div', { class: 'memory-recent-row' },
          h('p', { class: 'memory-recent-title' }, item.title),
          h('p', { class: 'memory-recent-scope' }, item.scope),
          h('span', { class: `memory-status${item.status === 'Indexing' ? ' is-indexing' : ''}` },
            item.status === 'Indexing' ? h('span', { class: 'memory-status-dot', 'aria-hidden': 'true' }) : null,
            item.status,
          ),
        ))),
      ),
    ),
    bottomNav('memory'),
  );
}
