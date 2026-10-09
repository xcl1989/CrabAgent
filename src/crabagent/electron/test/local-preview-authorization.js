// Test consent without starting Electron or creating visible windows.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { createLocalPreviewPolicy } = require('../computer-url-policy');
const source = fs.readFileSync(require.resolve('../main.js'), 'utf8');
const functions = source.slice(source.indexOf('let localPreviewApproval = null;'), source.indexOf('async function checkedBrowserUrl'));
const policy = createLocalPreviewPolicy({ forbiddenPorts: () => [5210] });
let response = 0, calls = 0, closed = 0, destroyed = 0, resolveDialog;
const sandbox = {
  localPreviewPolicy: policy, collaborationStopEpoch: 0,
  win: { isDestroyed: () => false }, collaborationView: { webContents: {
    stop() {}, session: { closeAllConnections: async () => { closed++; } },
  } },
  collaborationNetworkProxy: { closeConnections: () => { destroyed++; } },
  dialog: { showMessageBox: async (_window, options) => {
    calls++; assert.equal(options.defaultId, 0); assert.equal(options.cancelId, 0);
    assert.ok(options.message.includes('http://127.0.0.1:8766'));
    if (response === 'pending') return new Promise((resolve) => { resolveDialog = resolve; });
    return { response };
  } },
  sendCollaborationBrowserState() {}, invalidateCollaborationObservation() {},
  setTimeout: () => ({ unref() {} }),
};
vm.createContext(sandbox);
vm.runInContext(functions, sandbox);
(async () => {
  const url = 'http://127.0.0.1:8766/preview';
  assert.equal((await sandbox.authorizeLocalPreview(url)).status, 'blocked');
  assert.equal(policy.allows(url), false);
  response = 1;
  assert.equal((await sandbox.authorizeLocalPreview(url)).status, 'authorized');
  assert.equal(policy.allows(url), true);
  await sandbox.revokeLocalPreviews();
  assert.equal(policy.allows(url), false);
  assert.equal(closed, 1); assert.equal(destroyed, 1);
  response = 'pending';
  const pending = sandbox.authorizeLocalPreview(url);
  await assert.rejects(sandbox.authorizeLocalPreview(url), /PENDING/);
  await sandbox.revokeLocalPreviews();
  resolveDialog({ response: 1 });
  assert.equal((await pending).status, 'blocked');
  assert.equal(policy.allows(url), false);
  const priorCalls = calls;
  await assert.rejects(sandbox.authorizeLocalPreview('http://localhost:5210'), /RESERVED/);
  await assert.rejects(sandbox.authorizeLocalPreview('http://10.0.0.1'), /LOCAL_PREVIEW_ONLY/);
  assert.equal(calls, priorCalls);
  console.log('Native local preview authorization passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });
