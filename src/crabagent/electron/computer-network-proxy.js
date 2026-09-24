const dns = require('node:dns').promises;
const http = require('node:http');
const { randomBytes } = require('node:crypto');
const net = require('node:net');
const { parseBrowserUrl, blockedHost } = require('./computer-url-policy');

// VPN "fake-ip" range: when no system upstream exists, a 198.18.0.0/15 answer means the
// user runs a TUN-mode VPN whose tunnel routes that range; connecting there is safe and
// is how proxied traffic flows in that mode. Everything else private stays blocked.
function isFakeIp(address) {
  const parts = String(address).split('.').map(Number);
  return parts.length === 4 && parts[0] === 198 && (parts[1] === 18 || parts[1] === 19);
}

// Electron resolveProxy entries look like "PROXY 127.0.0.1:7897" (scheme + host:port),
// optionally "SOCKS5 host:port", several separated by ";". Returns the upstream target
// or null when the entry is unusable.
function parseProxyResolution(entry) {
  const [scheme, authority] = String(entry).trim().split(/\s+/);
  if (!scheme || !authority) return null;
  const kind = /^(PROXY|HTTPS?)$/i.test(scheme) ? 'http' : /^SOCKS5?$/i.test(scheme) ? 'socks5' : null;
  if (!kind) return null;
  const colon = authority.lastIndexOf(':');
  if (colon <= 0) return null;
  let host = authority.slice(0, colon);
  const port = authority.slice(colon + 1);
  if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535) return null;
  if (host.startsWith('[') && host.endsWith(']')) host = host.slice(1, -1);
  if (!host) return null;
  return { kind, host, port: Number(port) };
}

// Resolve and connect through one decided path. Without a system upstream, Chromium must
// never resolve collaboration traffic independently of this proxy's destination policy.
function createComputerNetworkProxy({ allowLocalFixture = false, lookup = (host) => dns.lookup(host, { all: true }), upstreamResolver = null, debug = null } = {}) {
  const trace = (msg) => { try { debug && debug(msg); } catch {} };
  function literalBlocked(host, address) {
    return blockedHost(address) && !(allowLocalFixture && host === '127.0.0.1' && address === '127.0.0.1');
  }

  // Decide the path for one authority: system upstream proxy or pinned direct IP.
  async function destination(host, port, scheme) {
    if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid port');
    if (blockedHost(host) && !(allowLocalFixture && host === '127.0.0.1')) throw new Error('PRIVATE_NETWORK_BLOCKED');
    const upstream = upstreamResolver ? await upstreamResolver(`${scheme || 'https'}://${host}:${port}/`) : null;
    trace(`destination ${host}:${port} -> ${upstream ? upstream.kind + ' ' + (upstream.host || '') + ':' + (upstream.port || '') : 'direct'}`);
    if (upstream && upstream.kind !== 'direct') {
      // The user's own proxy resolves the hostname; still refuse names/answers that point
      // at private infrastructure so a hostile page cannot reach the LAN or metadata.
      if (!net.isIP(host)) {
        const records = await lookup(host).catch(() => null);
        if (records && records.some(({ address }) => literalBlocked(host, address) && !isFakeIp(address))) {
          throw new Error('PRIVATE_NETWORK_BLOCKED');
        }
      }
      return upstream;
    }
    const records = net.isIP(host) ? [{ address: host }] : await lookup(host);
    if (!Array.isArray(records) || !records.length || records.some(({ address }) => !net.isIP(address) || (literalBlocked(host, address) && !isFakeIp(address)))) {
      throw new Error('PRIVATE_NETWORK_BLOCKED');
    }
    return { kind: 'direct', address: records[0].address };
  }

  function fail(socket, code = 403) {
    const challenge = code === 407 ? 'Proxy-Authenticate: Basic realm="CrabAgent"\r\n' : '';
    if (!socket.destroyed) socket.end(`HTTP/1.1 ${code} Forbidden\r\n${challenge}Connection: close\r\nContent-Length: 0\r\n\r\n`);
  }

  const proxySecret = randomBytes(32).toString('hex');
  function authorized(request) {
    return request.headers['proxy-authorization'] === `Basic ${Buffer.from(`crab:${proxySecret}`).toString('base64')}`;
  }

  function connectUpstreamHttp(upstream, authority) {
    return new Promise((resolve, reject) => {
      const socket = net.connect({ host: upstream.host, port: upstream.port });
      const timer = setTimeout(() => { socket.destroy(); reject(new Error('upstream connect timeout')); }, 20_000);
      let buffer = '';
      const onData = (chunk) => {
        buffer += chunk.toString('latin1');
        if (!buffer.includes('\r\n\r\n')) return;
        clearTimeout(timer);
        socket.off('data', onData);
        socket.off('error', onError);
        if (/^HTTP\/1\.[01] 200\b/.test(buffer)) resolve(socket);
        else { socket.destroy(); reject(new Error('upstream proxy refused CONNECT')); }
      };
      const onError = (error) => { clearTimeout(timer); reject(error); };
      socket.on('error', onError);
      socket.on('data', onData);
      socket.on('connect', () => {
        socket.write(`CONNECT ${authority} HTTP/1.1\r\nHost: ${authority}\r\n\r\n`);
      });
    });
  }

  function connectUpstreamSocks5(upstream, hostname, port) {
    return new Promise((resolve, reject) => {
      const socket = net.connect({ host: upstream.host, port: upstream.port });
      const timer = setTimeout(() => { socket.destroy(); reject(new Error('upstream socks timeout')); }, 20_000);
      const fail = (error) => { clearTimeout(timer); socket.destroy(); reject(error); };
      socket.on('error', fail);
      const hostBuf = Buffer.from(hostname, 'utf8');
      let stage = 'greeting';
      socket.on('data', function onData(chunk) {
        if (stage === 'greeting') {
          if (chunk[0] !== 0x05 || chunk[1] !== 0x00) { fail(new Error('upstream socks rejected auth')); return; }
          stage = 'connect';
          const request = Buffer.alloc(7 + hostBuf.length);
          request.writeUInt8(0x05, 0); request.writeUInt8(0x01, 1); request.writeUInt8(0x00, 2);
          request.writeUInt8(0x03, 3); request.writeUInt8(hostBuf.length, 4);
          hostBuf.copy(request, 5); request.writeUInt16BE(port, 5 + hostBuf.length);
          socket.write(request);
          return;
        }
        clearTimeout(timer);
        socket.off('data', onData);
        socket.off('error', fail);
        if (chunk[1] === 0x00) resolve(socket);
        else { socket.destroy(); reject(new Error('upstream socks connect failed')); }
      });
      socket.on('connect', () => socket.write(Buffer.from([0x05, 0x01, 0x00])));
    });
  }

  const server = http.createServer(async (request, response) => {
    if (!authorized(request)) {
      response.writeHead(407, { 'Proxy-Authenticate': 'Basic realm="CrabAgent"' }); response.end(); return;
    }
    try {
      const url = parseBrowserUrl(request.url);
      if (url.protocol !== 'http:') throw new Error('Unexpected proxy scheme');
      const target = await destination(url.hostname, Number(url.port || 80), 'http');
      let upstreamRequest;
      if (target.kind === 'direct') {
        upstreamRequest = http.request({
          host: target.address, port: Number(url.port || 80), method: request.method,
          path: url.pathname + url.search, headers: Object.fromEntries(Object.entries({ ...request.headers, host: url.host }).filter(([key]) => !['proxy-authorization', 'proxy-connection'].includes(key))),
          agent: false, family: net.isIP(target.address),
        });
      } else if (target.kind === 'http') {
        upstreamRequest = http.request({
          host: target.host, port: target.port, method: request.method,
          path: `${url.protocol}//${url.host}${url.pathname}${url.search}`,
          headers: Object.fromEntries(Object.entries({ ...request.headers, host: url.host }).filter(([key]) => !['proxy-authorization', 'proxy-connection'].includes(key))),
          agent: false,
        });
      } else {
        response.writeHead(502); response.end(); return;
      }
      upstreamRequest.on('response', (received) => {
        response.writeHead(received.statusCode, received.headers);
        received.pipe(response);
      });
      upstreamRequest.on('error', () => { if (!response.headersSent) response.writeHead(502); response.end(); });
      request.on('aborted', () => upstreamRequest.destroy());
      request.pipe(upstreamRequest);
    } catch {
      response.writeHead(403);
      response.end();
    }
  });
  server.on('connect', async (request, client, head) => {
    if (!authorized(request)) { fail(client, 407); return; }
    try {
      // CONNECT carries a single authority, not a URL or credentials.
      const authority = new URL(`http://${request.url}`);
      if (authority.host !== request.url || authority.username || authority.password) throw new Error('Invalid authority');
      const port = Number(authority.port || 443);
      const target = await destination(authority.hostname, port, 'https');
      let upstream;
      if (target.kind === 'direct') upstream = await new Promise((resolve, reject) => {
        const socket = net.connect({ host: target.address, port, family: net.isIP(target.address) });
        socket.once('connect', () => resolve(socket));
        socket.once('error', reject);
      });
      else if (target.kind === 'http') upstream = await connectUpstreamHttp(target, request.url);
      else upstream = await connectUpstreamSocks5(target, authority.hostname, port);
      if (client.destroyed) { upstream.destroy(); return; }
      client.write('HTTP/1.1 200 Connection Established\r\n\r\n');
      if (head.length) upstream.write(head);
      client.pipe(upstream).pipe(client);
      upstream.on('error', () => { fail(client, 502); client.destroy(); });
      client.on('error', () => upstream.destroy());
      client.on('close', () => upstream.destroy());
    } catch {
      fail(client);
    }
  });
  return { server, proxySecret };
}

module.exports = { createComputerNetworkProxy, parseProxyResolution };
