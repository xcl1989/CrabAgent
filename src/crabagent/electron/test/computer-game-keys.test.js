'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { validateGameKeys, holdGameKeys } = require('../computer-game-keys');

function setup(extra = {}) {
  const events = [];
  const controller = new AbortController();
  return { events, controller, args: { keys: ['KeyW', 'ArrowUp'], duration: 5,
    signal: controller.signal, check() {}, send(type, key) { events.push([type, key]); }, ...extra } };
}
test('validates whitelist, uniqueness, type and hard limit', () => {
  assert.deepEqual(validateGameKeys({ keys: ['KeyW', 'Space'], duration_ms: 1000 }).keys, ['KeyW', 'Space']);
  for (const payload of [
    { keys: ['Enter'], duration_ms: 1 }, { keys: ['KeyW', 'KeyW'], duration_ms: 1 },
    { keys: ['KeyW'], duration_ms: 0 }, { keys: ['KeyW'], duration_ms: 1001 },
    { keys: ['KeyW'], duration_ms: '1' }, { keys: [], duration_ms: 1 },
    { keys: ['KeyW', 'KeyA', 'KeyS', 'KeyD', 'Space'], duration_ms: 1 },
  ]) assert.throws(() => validateGameKeys(payload));
});
test('presses and releases in reverse order', async () => {
  const t = setup(); await holdGameKeys(t.args);
  assert.deepEqual(t.events, [['keyDown','W'], ['keyDown','Up'], ['keyUp','Up'], ['keyUp','W']]);
});
test('abort interrupts wait and releases', async () => {
  const t = setup({ duration: 1000 });
  const promise = holdGameKeys(t.args); t.controller.abort();
  await assert.rejects(promise, /CANCELLED/);
  assert.deepEqual(t.events.slice(-2), [['keyUp','Up'], ['keyUp','W']]);
});
test('dispatch failure still attempts reverse cleanup', async () => {
  const t = setup(); t.args.send = (type, key) => { t.events.push([type,key]); if (type === 'keyDown' && key === 'Up') throw Error('send failed'); };
  await assert.rejects(holdGameKeys(t.args), /send failed/);
  assert.deepEqual(t.events.slice(-2), [['keyUp','Up'], ['keyUp','W']]);
});
test('cleanup continues and reports release failures', async () => {
  const t = setup(); t.args.send = (type, key) => { t.events.push([type,key]); if (type === 'keyUp' && key === 'Up') throw Error('failed'); };
  await assert.rejects(holdGameKeys(t.args), /RELEASE_FAILED/);
  assert.deepEqual(t.events.at(-1), ['keyUp','W']);
});
test('failed target check injects nothing', async () => {
  const t = setup({ check() { throw Error('STALE_PAGE'); } });
  await assert.rejects(holdGameKeys(t.args), /STALE_PAGE/); assert.deepEqual(t.events, []);
});
