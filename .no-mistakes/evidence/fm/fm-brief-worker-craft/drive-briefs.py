"""Drive the real scaffold CLI; examine its generated public instruction contract.
Oracle: author intent requires concise craft advice in ship launch instructions;
scout/report and secondmate/supervision contracts remain outside ship scope.
No worker runtime, credential, fleet session, or implementation stub is used.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path.cwd()
evidence = Path('~/.no-mistakes/evidence/01M6RVN0GXVNE5WVRW1GDCP0HJ')
home = Path(tempfile.mkdtemp(prefix='.brief-live-', dir=root))
env = os.environ.copy()
for key in list(env):
    if key.startswith('FM_'):
        del env[key]
env['FM_HOME'] = str(home)
env['FM_SECONDMATE_CHARTER'] = 'Supervise the disposable alpha project only.'
transcript = []
scenarios = [('no-mistakes', ['alpha', '--mode', 'no-mistakes']),
             ('direct-PR', ['alpha', '--mode', 'direct-PR']),
             ('local-only', ['alpha', '--mode', 'local-only']),
             ('scout', ['alpha', '--scout']),
             ('charter', ['--secondmate', 'alpha'])]
try:
    for name, args in scenarios:
        task = 'craft-live-' + name.lower()
        command = ['bash', 'bin/fm-brief.sh', task] + args
        proc = subprocess.run(command, env=env, cwd=root, capture_output=True, text=True, timeout=45)
        transcript.append('$ FM_HOME=<disposable-worktree-home> ' + ' '.join(command))
        transcript.append('exit=' + str(proc.returncode))
        transcript.append(proc.stdout.replace(str(home), '<disposable-worktree-home>'))
        transcript.append(proc.stderr.replace(str(home), '<disposable-worktree-home>'))
        assert proc.returncode == 0, name + ': scaffold failed'
        brief = home / 'data' / task / 'brief.md'
        text = brief.read_text()
        # Preserve the exact generated end-user output, not source snapshots.
        shutil.copyfile(brief, evidence / (name + '-brief.md'))
        if name in ('scout', 'charter'):
            assert '# Working craft' not in text, name + ': ship heading leaked'
            assert 'write the goal and the smallest change' not in text, name + ': ship advice leaked'
            if name == 'scout':
                assert 'report.md' in text
            else:
                assert env['FM_SECONDMATE_CHARTER'] in text
            transcript.append('Observed: role-specific instructions generated without ship craft section.')
        else:
            assert text.count('\n# Working craft\n') == 1
            craft = text.split('\n# Working craft\n')[1].split('\n# Rules\n')[0]
            assert len(craft) <= 1800
            for phrase in ('goal and the smallest change', 'data shape or domain model',
                           'no new layer', 'one concern per change', 'verifiable steps',
                           'separate shippable changes', 'reproduce it first on the surface',
                           'Test behavior, not implementation details', 'prove it on the real surface',
                           'stand-in, mock or wrong surface', 'Known gaps', 'read your full diff once',
                           'narrative comments'):
                assert phrase in craft, name + ': missing intended instruction: ' + phrase
            assert 'Delivery contract: mode=' + name in text
            assert '## Captain\'s intent' in text and '## Firstmate spec' in text
            transcript.append('Observed craft delivered before Rules (' + str(len(craft)) + ' characters):\n' + craft)
        transcript.append('RESULT: ' + name + ' passed\n')
finally:
    shutil.rmtree(home)
    transcript.append('Disposable home removed; no worker or server was started.')
    (evidence / 'brief-cli-transcript.txt').write_text('\n'.join(transcript))
