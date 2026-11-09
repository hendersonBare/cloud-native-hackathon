// Starts Dash0 website monitoring on the page that loads this (index.html and phone.html), when the
// gateway has it configured. See app/rum.js. The page never waits on it.

import { personaFrom, startRum } from './app/rum.js';

const page = location.pathname.endsWith('phone.html') ? 'phone' : 'stage';
const persona = page === 'phone' ? personaFrom(location.search) : null;

startRum({ page, persona }).catch((err) => console.warn('Website monitoring unavailable', err?.name || 'Error'));
