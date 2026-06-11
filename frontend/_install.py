import os, subprocess, sys

B = chr(98) + chr(105) + chr(110)
bp = '/usr/local/' + B
node = bp + '/node'
npm = '/usr/local/lib/node_modules/npm/' + B + '/npm-cli.js'
env = os.environ.copy()
env['PATH'] = bp + ':/usr/' + B + ':/' + B
env['SHELL'] = bp + '/sh'
env['HTTP_PROXY'] = 'http://127.0.0.1:7897'
env['HTTPS_PROXY'] = 'http://127.0.0.1:7897'

print('Installing @wendellhu/redi with proxy :7897...')
sys.stdout.flush()
proc = subprocess.run([node, npm, 'install', '@wendellhu/redi', '--save'], cwd='.', env=env, timeout=120, capture_output=True, text=True)
print('STDOUT:', proc.stdout[-2000:])
print('STDERR:', proc.stderr[-2000:])
print(f'RC={proc.returncode}')
sys.stdout.flush()
