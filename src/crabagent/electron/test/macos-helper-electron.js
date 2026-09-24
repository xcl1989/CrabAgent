#!/usr/bin/env node
// M0 integration test: drives the macOS computer-use helper through the same
// one-shot spawn mechanism that Electron main.js uses (child_process.spawn with
// a request temp file). Run: node test/macos-helper-electron.js [helper-path]
const { spawn } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const helper = process.argv[2] || path.join(__dirname, '..', 'helper', 'macos-helper');
const secret = crypto.randomBytes(16).toString('hex');
let failures = 0;

function runMacosHelper(request) {
  return new Promise((resolve) => {
    const requestPath = path.join(os.tmpdir(), `crab-helper-test-${crypto.randomBytes(8).toString('hex')}.json`);
    fs.writeFileSync(requestPath, JSON.stringify({ ...request, secret }), { mode: 0o600 });
    let out = '';
    const child = spawn(helper, ['--request-file', requestPath, '--secret', secret]);
    child.stdout.on('data', (d) => { out += d; });
    child.on('error', (e) => resolve({ ok: false, error: `spawn failed: ${e.message}` }));
    child.on('close', () => {
      try { fs.unlinkSync(requestPath); } catch {}
      try { resolve(JSON.parse(out)); } catch { resolve({ ok: false, error: 'bad helper output' }); }
    });
    setTimeout(() => { try { child.kill(); } catch {} resolve({ ok: false, error: 'helper timeout' }); }, 15000);
  });
}

function check(name, condition, detail) {
  if (!condition) { failures += 1; console.log('FAIL:', name, detail !== undefined ? JSON.stringify(detail).slice(0, 140) : ''); }
  else console.log('PASS:', name);
}

(async () => {
  const perm = await runMacosHelper({ command: 'permissions' });
  check('permissions', perm.ok && typeof perm.permissions.accessibility === 'boolean'
    && typeof perm.permissions.screenRecording === 'boolean' && typeof perm.permissions.osVersion === 'string', perm);

  const windows = await runMacosHelper({ command: 'windows' });
  check('windows', windows.ok && Array.isArray(windows.windows) && windows.windows.length >= 1, windows);
  check('window schema', windows.ok && windows.windows.every((w) =>
    Number.isInteger(w.windowId) && Number.isInteger(w.pid) && typeof w.bundleId === 'string' && w.bounds), windows);

  const stub = await runMacosHelper({ command: 'click' });
  check('input refused without opt-in', stub.ok === false && /opt-in/.test(stub.error || ''), stub);

  // Tampered request file: field changed after signing is impossible; wrong nonce refused.
  const tamperedPath = path.join(os.tmpdir(), `crab-helper-tampered-${crypto.randomBytes(8).toString('hex')}.json`);
  fs.writeFileSync(tamperedPath, JSON.stringify({ secret: 'tampered', command: 'permissions' }), { mode: 0o600 });
  const bad = await new Promise((resolve) => {
    let out = '';
    const child = spawn(helper, ['--request-file', tamperedPath, '--secret', secret]);
    child.stdout.on('data', (d) => { out += d; });
    child.on('close', () => { try { fs.unlinkSync(tamperedPath); } catch {} resolve(JSON.parse(out || '{}')); });
    child.on('error', (e) => resolve({ ok: false, error: e.message }));
  });
  check('tampered secret refused', bad.ok === false && bad.error === 'bad request or secret', bad);

  console.log(failures === 0 ? 'MACOS HELPER ELECTRON-PATH TESTS PASS' : `${failures} FAILURES`);
  process.exit(failures === 0 ? 0 : 1);
})();
