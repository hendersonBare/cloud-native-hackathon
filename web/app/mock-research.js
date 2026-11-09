// Mock-mode research decks, one per viewer that has one. demo-research.json is Ava's deck
// (a copy of contracts/demo-research.json); demo-research-bo.json is Bo's. Live mode asks the
// gateway instead. All names are fictional.
import AVA from '../mock/demo-research.json' with { type: 'json' };
import BO from '../mock/demo-research-bo.json' with { type: 'json' };

/** Every bundled deck, for data that does not depend on the viewer (such as searchable interests). */
export const MOCK_DECKS = Object.freeze([AVA, BO]);

const DECKS = new Map(MOCK_DECKS.map((deck) => [deck.persona_id, deck]));

/** The bundled ResearchResult computed for this viewer, or null when there is none. */
export function mockResearchFor(personaId) {
  return DECKS.get(personaId) || null;
}
