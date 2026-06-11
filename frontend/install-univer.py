#!/usr/bin/env python3
"""Install Univer npm packages."""
import subprocess, os, sys

npm = '/usr/local/bin/npm'
cwd = os.path.dirname(os.path.abspath(__file__))

env = {
    'PATH': '/usr/local/bin',
    'HOME': os.environ.get('HOME', ''),
    'USER': os.environ.get('USER', ''),
    'npm_config_proxy': 'http://127.0.0.1:7897',
    'npm_config_https_proxy': 'http://127.0.0.1:7897',
}

try:
    r = subprocess.run(
        [npm, 'install', '--ignore-scripts'],
        cwd=cwd, capture_output=True, text=True, timeout=180, env=env
    )
    # Only print non-path content
    for line in (r.stdout or '').split('\n'):
        if '/bin' not in line and '/usr' not in line:
            print(line)
    if r.returncode != 0:
        for line in (r.stderr or '').split('\n'):
            if '/bin' not in line and '/usr' not in line:
                print('E:', line)
    print('Return code:', r.returncode)
    sys.exit(r.returncode)
except subprocess.TimeoutExpired:
    print('TIMEOUT - npm install took too long')
    sys.exit(1)
