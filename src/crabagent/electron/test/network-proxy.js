const assert = require('node:assert/strict');
const http = require('node:http');
const net = require('node:net');
const { createComputerNetworkProxy } = require('../computer-network-proxy');
let auth = '';

async function listen(server) {
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  return server.address().port;
}
function fetch(proxyPort, url) {
  return new Promise((resolve, reject) => {
    http.get({ host: '127.0.0.1', port: proxyPort, path: url, headers: { 'Proxy-Authorization': auth } }, (response) => {
      let body = '';
      response.on('data', (data) => { body += data; });
      response.on('end', () => resolve({ status: response.statusCode, body }));
    }).on('error', reject);
  });
}
function connect(proxyPort, authority) {
  return new Promise((resolve, reject) => {
    const socket = net.connect(proxyPort, '127.0.0.1');
    socket.on('error', reject);
    socket.on('data', (data) => { resolve(data.toString()); socket.destroy(); });
    socket.on('connect', () => socket.write(`CONNECT ${authority} HTTP/1.1\r\nHost: ${authority}\r\nProxy-Authorization: ${auth}\r\n\r\n`));
  });
}
(async () => {
  const target = http.createServer((_req, res) => res.end('fixture'));
  const targetPort = await listen(target);
  let answers = [{ address: '127.0.0.1' }];
  const proxy = createComputerNetworkProxy({ lookup: async () => answers });
  auth = `Basic ${Buffer.from(`crab:${proxy.proxySecret}`).toString('base64')}`;
  const proxyPort = await listen(proxy.server);
  try {
    // DNS preflight would accept the first answer; the proxy resolves and pins at connect time.
    assert.equal((await fetch(proxyPort, `http://rebind.invalid:${targetPort}/`)).status, 403);
    assert.match(await connect(proxyPort, `rebind.invalid:${targetPort}`), /403 Forbidden/);
    const noAuth = await new Promise((resolve) => http.get({ host: '127.0.0.1', port: proxyPort, path: `http://rebind.invalid:${targetPort}/` }, (res) => { res.resume(); resolve(res.statusCode); }));
    assert.equal(noAuth, 407);
    answers = [{ address: '8.8.8.8' }, { address: '127.0.0.1' }];
    assert.equal((await fetch(proxyPort, `http://rebind.invalid:${targetPort}/`)).status, 403);
    assert.equal((await fetch(proxyPort, `http://169.254.169.254:${targetPort}/`)).status, 403);
    const fixture = createComputerNetworkProxy({ allowLocalFixture: true });
    const fixturePort = await listen(fixture.server);
    auth = `Basic ${Buffer.from(`crab:${fixture.proxySecret}`).toString('base64')}`;
    try {
      assert.deepEqual(await fetch(fixturePort, `http://127.0.0.1:${targetPort}/`), { status: 200, body: 'fixture' });
    } finally { fixture.server.close(); }
    // System-proxy chaining: our proxy must forward to the user's upstream (Clash etc.)
    let upstreamHits = 0;
    const upstream = http.createServer((req, res) => {
      // absolute-URI forward request; a real upstream resolves the hostname itself, so the
      // fixture connects to the target regardless of the (unresolvable) .invalid name
      upstreamHits++;
      const target = new URL(req.url);
      const forward = http.request({ host: '127.0.0.1', port: targetPort, path: target.pathname + target.search, method: req.method, headers: { host: target.host } }, (r) => {
        res.writeHead(r.statusCode, r.headers); r.pipe(res);
      });
      forward.on('error', () => { res.writeHead(502); res.end(); });
      req.pipe(forward);
    });
    upstream.on('connect', (req, client, head) => {
      upstreamHits++;
      const target = new URL('http://' + req.url);
      const socket = net.connect(target.port || 443, '127.0.0.1');
      socket.on('connect', () => {
        client.write('HTTP/1.1 200 Connection Established\r\n\r\n');
        if (head.length) socket.write(head);
        client.pipe(socket).pipe(client);
      });
      socket.on('error', () => client.destroy());
    });
    const upstreamPort = await listen(upstream);
    const chained = createComputerNetworkProxy({
      upstreamResolver: async () => ({ kind: 'http', host: '127.0.0.1', port: upstreamPort }),
      // A hostile hostname that resolves locally to loopback must be refused even though
      // the upstream would resolve it differently.
      lookup: async (host) => host === 'rebind.invalid' ? [{ address: '127.0.0.1' }] : dns.lookup(host, { all: true }),
    });
    auth = `Basic ${Buffer.from(`crab:${chained.proxySecret}`).toString('base64')}`;
    const chainedPort = await listen(chained.server);
    try {
      const viaUpstream = await fetch(chainedPort, `http://forwarded.invalid:${targetPort}/hello`);
      assert.equal(viaUpstream.status, 200);
      assert.ok(upstreamHits >= 1, 'traffic must traverse the system upstream');
      const viaConnect = await connect(chainedPort, `tunnel.invalid:${targetPort}`);
      assert.match(viaConnect, /HTTP\/1\.1 200 Connection Established/);
      assert.match(await connect(chainedPort, '169.254.169.254:80'), /403 Forbidden/);
      const blockedViaUpstream = await fetch(chainedPort, 'http://rebind.invalid:1/');
      assert.equal(blockedViaUpstream.status, 403, 'private answers must stay blocked even via upstream');
    } finally { chained.server.close(); upstream.close(); }

    console.log('Network proxy safety fixtures passed');
  } finally { proxy.server.close(); target.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
