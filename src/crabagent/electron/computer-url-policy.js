const dns = require('node:dns').promises;
const net = require('node:net');

function blockedIPv4(address) {
  const parts = address.split('.').map(Number);
  if (parts.length !== 4 || parts.some((n) => !Number.isInteger(n) || n < 0 || n > 255)) return true;
  const [a, b] = parts;
  if (a === 0 || a === 10 || a === 127) return true; // this-host, private, loopback
  if (a === 100 && b >= 64 && b <= 127) return true; // CGNAT
  if (a === 169 && b === 254) return true; // link-local
  if (a === 172 && b >= 16 && b <= 31) return true; // private
  if (a === 192 && b === 0 && parts[2] === 0) return true; // TEST-NET-1
  if (a === 192 && b === 168) return true; // private
  if (a === 198 && (b === 18 || b === 19)) return true; // benchmarking (fake-ip VPNs)
  if (a >= 224) return true; // multicast + reserved
  return false;
}

function blockedIPv6(address) {
  const host = address.toLowerCase();
  if (host === '::' || host === '::1') return true; // unspecified, loopback
  if (host.startsWith('::ffff:')) return true; // IPv4-mapped (validated as IPv4 separately)
  if (/^f[cd]/.test(host)) return true; // unique local fc00::/7
  if (host.startsWith('fe8') || host.startsWith('fe9') || host.startsWith('fea') || host.startsWith('feb')) return true; // link-local
  if (/^f[e-f]/.test(host)) return true; // multicast/reserved ff00::/8 and fallback
  if (host.startsWith('2001:db8:')) return true; // documentation
  return false;
}

function parseBrowserUrl(raw) {
  const value = String(raw || '').trim();
  const url = new URL(/^[a-z][a-z\d+.-]*:/i.test(value) ? value : `https://${value}`);
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('Only http and https websites can be opened here.');
  if (url.username || url.password) throw new Error('Credentials in URLs are not allowed.');
  return url;
}

function blockedHost(hostname) {
  const host = hostname.replace(/^\[|\]$/g, '').toLowerCase();
  if (host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local') || host.endsWith('.internal')) return true;
  const family = net.isIP(host);
  if (family === 4) return blockedIPv4(host);
  if (family === 6) return blockedIPv6(host);
  return false;
}

async function allowedNetworkUrl(raw, { allowLocalFixture = false } = {}) {
  const url = parseBrowserUrl(raw);
  if (allowLocalFixture && url.hostname === '127.0.0.1') return url.toString();
  if (blockedHost(url.hostname)) throw new Error('PRIVATE_NETWORK_BLOCKED: local or private network address');
  const records = await dns.lookup(url.hostname, { all: true });
  if (!records.length || records.some(({ address }) => blockedHost(address))) {
    throw new Error('PRIVATE_NETWORK_BLOCKED: resolved to a local or private network address');
  }
  return url.toString();
}

module.exports = { parseBrowserUrl, blockedHost, allowedNetworkUrl };
