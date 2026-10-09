const assert = require('node:assert/strict');
const { createLocalPreviewPolicy, allowedNetworkUrl, localPreviewOrigin } = require('../computer-url-policy');
(async () => {
  let time = 100;
  const policy = createLocalPreviewPolicy({ now: () => time, ttlMs: 100, forbiddenPorts: () => [5210] });
  const url = 'http://127.0.0.1:8766';
  await assert.rejects(allowedNetworkUrl(url, { localPreviewPolicy: policy }), /PRIVATE_NETWORK_BLOCKED/);
  assert.equal(policy.grant(`${url}/preview?x=1`), url);
  for (const path of ['/', '/desktop.png', '/redirect', '/nested/script.js']) {
    assert.equal(await allowedNetworkUrl(url + path, { localPreviewPolicy: policy }), url + path);
  }
  for (const other of ['http://127.0.0.1:8767', 'https://127.0.0.1:8766', 'http://localhost:8766', 'http://[::1]:8766', 'http://10.0.0.1:8766', 'http://169.254.169.254/']) {
    assert.equal(policy.allows(other), false);
    await assert.rejects(allowedNetworkUrl(other, { localPreviewPolicy: policy }), /PRIVATE_NETWORK_BLOCKED/);
  }
  for (const invalid of ['http://10.0.0.1/', 'http://x.localhost/', 'http://0.0.0.0/', 'file:///tmp/a', 'http://user:pass@localhost/']) {
    assert.throws(() => policy.grant(invalid));
  }
  assert.throws(() => policy.grant('http://localhost:5210'), /RESERVED/);
  assert.equal(localPreviewOrigin('http://2130706433:8766/'), url);
  assert.equal(policy.allows('http://127.0.0.1:8766@evil.invalid'), false);
  time = 201;
  assert.equal(policy.allows(url), false);
  policy.grant(url); policy.clear();
  assert.equal(policy.allows(url), false);
  assert.equal(localPreviewOrigin('http://[::1]:8766/a'), 'http://[::1]:8766');
  console.log('Local preview policy passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });
