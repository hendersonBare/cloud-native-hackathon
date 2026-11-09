// The context a person's agent carries about them: the topics and "working on" line Profile
// shows, plus anything the person adds or changes from Memory. One copy per phone, in
// `store.context`. Saving goes to the gateway (POST /api/context, the briefer turns it into a
// profile) when one answers; without one, or when that API isn't served, it stays on this phone.
// Text the person types is never logged; errors carry only a status.
import { uploadContext } from './api.js';
import { isUnavailable } from './mode.js';

export const MAX_NOTE_CHARS = 4000;
export const MAX_FILE_BYTES = 2 * 1024 * 1024; // the gateway's max_upload_bytes
export const FILE_TYPES = ['.pdf', '.md', '.txt'];
const MAX_TOPICS = 8; // ProfileInfo.interests

const DEFAULTS = {
  'acme.ava': {
    topics: ['eBPF tracing', 'OpenTelemetry', 'Healthcare', 'Observability'],
    workingOn: 'Working on: a hospital network rollout with 40% faster incidents',
  },
  'bluefin.bo': {
    topics: ['eBPF tracing', 'OpenTelemetry', 'HIPAA review', 'Observability cost'],
    workingOn: 'Trabajando en: la migración de la plataforma hospitalaria',
    lang: 'es',
  },
};

function savedFor({ me, store }) {
  return store?.context?.personaId === me?.id ? store.context : null;
}

/** What the agent carries for this phone's person right now. */
export function currentContext({ me, store }) {
  const base = DEFAULTS[me?.id] || DEFAULTS['acme.ava'];
  const saved = savedFor({ me, store });
  return {
    topics: saved?.topics || base.topics,
    workingOn: saved?.workingOn ?? base.workingOn,
    // The seed line keeps its language; a line from the agent may be in either, so it carries none.
    lang: saved?.workingOn != null ? undefined : base.lang,
    note: saved?.note || '',
    filename: saved?.filename || null,
    visibility: saved?.visibility || store?.profile?.visibility || 'shareable',
    savedTo: saved?.savedTo || null,
  };
}

/** Problems with a draft before it is sent, as a short message, or null. */
export function validateDraft({ text, file }) {
  const note = typeof text === 'string' ? text.trim() : '';
  if (!note && !file) return 'Write something or attach a file first.';
  if (note.length > MAX_NOTE_CHARS) return `Keep it under ${MAX_NOTE_CHARS.toLocaleString('en-US')} characters.`;
  if (file) {
    const name = String(file.name || '').toLowerCase();
    if (!FILE_TYPES.some((type) => name.endsWith(type))) return 'Attach a .pdf, .md or .txt file.';
    if (file.size > MAX_FILE_BYTES) return 'That file is over 2 MB.';
  }
  return null;
}

/** Turn a gateway PersonaProfile into the fields shown, keeping what it doesn't say. */
export function fromProfile(profile, visibility, prior) {
  const info = profile?.[visibility] || profile?.shareable || profile?.private || null;
  const interests = Array.isArray(info?.interests)
    ? info.interests.filter((item) => typeof item === 'string' && item.trim()).slice(0, MAX_TOPICS) : [];
  const headline = typeof info?.headline === 'string' && info.headline.trim() ? info.headline.trim() : null;
  return {
    topics: interests.length ? interests : prior.topics,
    workingOn: headline ?? prior.workingOn,
  };
}

const MESSAGES = {
  413: 'That is too large for your agent. Try a shorter note or a smaller file.',
  415: 'Your agent accepts .pdf, .md and .txt files only.',
  429: 'Your agent is busy. Try again in a moment.',
};

/**
 * Save a change to the person's context. Resolves to { ok: true, savedTo: 'agent' | 'phone' }
 * or { ok: false, message }. `upload` is injectable for tests.
 */
export async function saveContext(ctx, { text, file, visibility }, { upload = uploadContext } = {}) {
  const problem = validateDraft({ text, file });
  if (problem) return { ok: false, message: problem };
  const note = typeof text === 'string' ? text.trim() : '';
  const vis = visibility === 'private' ? 'private' : 'shareable';
  const prior = currentContext(ctx);
  const saved = savedFor(ctx);
  const next = {
    personaId: ctx.me.id,
    topics: saved?.topics,
    workingOn: saved?.workingOn,
    note,
    // Keep only the file's name: its contents go to the agent and are never kept on the phone.
    filename: file ? file.name : prior.filename,
    visibility: vis,
  };
  if (ctx.mode === 'live') {
    try {
      const profile = await upload({ personaId: ctx.me.id, visibility: vis, file, text: note || undefined });
      Object.assign(next, fromProfile(profile, vis, prior), { savedTo: 'agent' });
      ctx.store.context = next;
      return { ok: true, savedTo: 'agent' };
    } catch (error) {
      if (!isUnavailable(error)) {
        console.warn('Context save failed', error?.status || error?.name || 'Error');
        return { ok: false, message: MESSAGES[error?.status] || 'Your agent could not save that. Try again.' };
      }
    }
  }
  next.savedTo = 'phone';
  ctx.store.context = next;
  return { ok: true, savedTo: 'phone' };
}
