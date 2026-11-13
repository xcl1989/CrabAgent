'use strict';

const MAX_DURATION_MS = 1000;
const KEY_PATTERN = /^(Key[A-Z]|Digit[0-9]|ArrowUp|ArrowDown|ArrowLeft|ArrowRight|Space)$/;

function validateGameKeys(payload) {
  const { keys, duration_ms: duration } = payload;
  if (!Array.isArray(keys) || keys.length < 1 || keys.length > 4 ||
      keys.some(key => typeof key !== 'string' || !KEY_PATTERN.test(key)) ||
      new Set(keys).size !== keys.length) throw new Error('INVALID_GAME_KEYS');
  if (!Number.isInteger(duration) || duration < 1 || duration > MAX_DURATION_MS) throw new Error('INVALID_GAME_DURATION');
  return { keys: [...keys], duration };
}

function validateGamePlan(payload) {
  if (!Array.isArray(payload.steps) || payload.steps.length < 1 || payload.steps.length > 8) throw new Error('INVALID_GAME_PLAN');
  let total = 0;
  const steps = payload.steps.map(step => {
    if (!step || typeof step !== 'object' || Array.isArray(step) || !['hold_keys', 'wait'].includes(step.type)) throw new Error('INVALID_GAME_STEP');
    const allowed = step.type === 'hold_keys' ? ['type', 'keys', 'duration_ms'] : ['type', 'duration_ms'];
    if (Object.keys(step).some(key => !allowed.includes(key))) throw new Error('INVALID_GAME_STEP');
    if (!Number.isInteger(step.duration_ms) || step.duration_ms < 1 || step.duration_ms > 1000) throw new Error('INVALID_GAME_DURATION');
    total += step.duration_ms;
    if (total > 2000) throw new Error('GAME_PLAN_TOO_LONG');
    if (step.type === 'hold_keys') validateGameKeys(step);
    return { ...step, ...(step.keys ? { keys: [...step.keys] } : {}) };
  });
  return { steps, total };
}

async function waitGameStep(duration, signal) {
  await new Promise((resolve, reject) => {
    let timer;
    const abort = () => { clearTimeout(timer); signal.removeEventListener('abort', abort); reject(new Error('GAME_KEYS_CANCELLED')); };
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) return abort();
    timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve(); }, duration);
  });
}

function electronKey(key) {
  if (key.startsWith('Key')) return key.slice(3);
  if (key.startsWith('Digit')) return key.slice(5);
  if (key.startsWith('Arrow')) return key.slice(5);
  return key;
}

async function holdGameKeys({ keys, duration, send, signal, check }) {
  const pressed = [];
  let timer;
  let onAbort;
  let failure;
  const releaseErrors = [];
  const deadline = performance.now() + duration;
  try {
    check();
    for (const key of keys) {
      if (signal.aborted) throw new Error('GAME_KEYS_CANCELLED');
      check();
      if (performance.now() >= deadline) throw new Error('GAME_KEYS_TIMEOUT');
      // Record before dispatch: even a throwing dispatcher may have delivered the event.
      pressed.push(key);
      send('keyDown', electronKey(key));
    }
    await new Promise((resolve, reject) => {
      onAbort = () => reject(new Error('GAME_KEYS_CANCELLED'));
      signal.addEventListener('abort', onAbort, { once: true });
      if (signal.aborted) return onAbort();
      timer = setTimeout(resolve, Math.max(0, deadline - performance.now()));
    });
    check();
  } catch (error) {
    failure = error;
  } finally {
    clearTimeout(timer);
    if (onAbort) signal.removeEventListener('abort', onAbort);
    for (const key of pressed.reverse()) {
      try { send('keyUp', electronKey(key)); } catch (error) { releaseErrors.push(key); }
    }
  }
  if (releaseErrors.length) throw new Error(`GAME_KEYS_RELEASE_FAILED: ${releaseErrors.join(',')}${failure ? `; ${failure.message}` : ''}`);
  if (failure) throw failure;
  return { held: keys, duration_ms: duration, released: true };
}

module.exports = { validateGameKeys, validateGamePlan, holdGameKeys, waitGameStep };
