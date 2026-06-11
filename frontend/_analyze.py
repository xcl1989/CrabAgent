import os, re, json

# Analyze what the chunk files are
dist = 'dist/assets'
for fname in sorted(os.listdir(dist)):
    if not fname.endswith('.js'):
        continue
    prefix = fname.split('-')[0]
    if prefix in ('index', 'vendor', 'facade', 'univer', 'cop', 'set', 'zh'):
        continue
    fpath = os.path.join(dist, fname)
    size = os.path.getsize(fpath)
    with open(fpath) as f:
        head = f.read(3000)
    # Look for any import/require statements or comments
    refs = re.findall(r'from\s+["\']([^"\']+)["\']', head)
    refs += re.findall(r'require\(["\']([^"\']+)["\']', head)
    refs += re.findall(r'import\s+["\']([^"\']+)["\']', head)
    # Look for package name markers
    pkg = [r for r in refs if 'univer' in r.lower()]
    print(f'{fname:50s} {size/1024:6.0f}KB  pkg={pkg[:2]}')
