const { test } = require('node:test');
const assert = require('node:assert/strict');
const { descendants, stopBackend } = require('../src/crabagent/electron/backend-lifecycle');

test('enumerates only descendants, deepest first, including detached children', () => {
  assert.deepEqual(descendants('10 1\n20 10\n30 20\n40 1\n50 10\n', 10), [30, 20, 50]);
});

test('escalates even when ChildProcess.killed is already true', async () => {
  const calls = [];
  await stopBackend({ pid: 10, killed: true, exitCode: null, signalCode: null }, {
    platform: 'darwin',
    run: async () => ({ stdout: '10 1\n20 10\n30 20\n' }),
    signal: (pid, name) => calls.push([pid, name]),
    delay: async () => {},
  });
  assert.deepEqual(calls, [
    [30, 'SIGTERM'], [20, 'SIGTERM'], [10, 'SIGTERM'],
    [30, 'SIGKILL'], [20, 'SIGKILL'], [10, 'SIGKILL'],
  ]);
});

test('does not signal a backend that has exited during the grace period', async () => {
  const calls = [];
  const child = { pid: 10, exitCode: null, signalCode: null };
  await stopBackend(child, {
    platform: 'linux',
    run: async () => ({ stdout: '' }),
    signal: (pid, name) => calls.push([pid, name]),
    delay: async () => { child.exitCode = 0; },
  });
  assert.deepEqual(calls, [[10, 'SIGTERM']]);
});

test('still stops the backend if process enumeration fails', async () => {
  const calls = [];
  await stopBackend({ pid: 10, exitCode: null, signalCode: null }, {
    platform: 'darwin',
    run: async () => { throw new Error('ps failed'); },
    signal: (pid, name) => calls.push([pid, name]),
    delay: async () => {},
  });
  assert.deepEqual(calls, [[10, 'SIGTERM'], [10, 'SIGKILL']]);
});

test('Windows terminates the tree using taskkill', async () => {
  let args;
  await stopBackend({ pid: 10 }, {
    platform: 'win32',
    run: async (...values) => { args = values; },
  });
  assert.deepEqual(args, ['taskkill', ['/PID', '10', '/T', '/F'], { timeout: 5000 }]);
});
