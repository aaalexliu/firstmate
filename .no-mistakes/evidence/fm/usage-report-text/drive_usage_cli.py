"""Disposable public-CLI exercise; all accounting records below are synthetic."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess

ROOT = Path.cwd()
E = Path('~/.no-mistakes/evidence/01M6MWHTV5ENSBR09ZVZZAFRHG')
W = ROOT / '.usage-live'
assert not W.exists()
W.mkdir()
H = W/'home'
(H/'state').mkdir(parents=True)
roots = {name: W/name for name in ('pi','supervision','claude','codex')}
for p in roots.values(): p.mkdir()
N = 1793849879
iso = lambda t: dt.datetime.fromtimestamp(t,dt.timezone.utc).isoformat()
env = {k:v for k,v in os.environ.items() if not k.startswith('FM_')}
env['FM_HOME'] = str(H)
output = W/'render'/'index.html'
ledger = W/'ledger.sqlite'
store = H/'data/usage-report/usage.sqlite'
log = []
def cli(command, now=N, ok=True):
    args = [str(ROOT/'bin/fm-usage-report.sh'),command,'--now',str(now),'--nm-db',str(ledger),'--output',str(output)]
    for name,p in roots.items(): args += ['--'+name+'-root',str(p)]
    r = subprocess.run(args,env=env,text=True,capture_output=True,timeout=30)
    log.append('$ bin/fm-usage-report.sh '+command+' [isolated roots; synthetic records]\n'+r.stdout+r.stderr+'exit='+str(r.returncode)+'\n')
    assert (r.returncode == 0) == ok, r.stderr
    return r.stdout if ok else r.stderr

def record(name, sid, inp=100, model='claude-opus-5-5', provider='anthropic', ts=N-100):
    rows=[dict(type='session',id=sid,timestamp=iso(ts-100),cwd=str(H)),
          dict(type='message',id='entry-'+sid,timestamp=iso(ts),message=dict(role='assistant',model=model,provider=provider,responseId='response-'+sid,
              usage=dict(input=inp,cacheRead=200,cacheWrite=10,output=30,totalTokens=900 if inp is None else inp+240)))]
    (roots[name]/(sid+'.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in rows))

def payload():
    return json.loads(re.search(r'const DATA\s*=\s*(.*);\n',output.read_text())[1])

try:
    # Missing summary is actionable and creates no accounting directory.
    assert 'run fm-usage-report.sh refresh first' in cli('text',ok=False)
    assert not (H/'data').exists()
    record('pi','main')
    record('supervision','branch')
    record('pi','codex-main',1000,'gpt-6.1-sol','openai')
    with sqlite3.connect(ledger) as db:
        db.executescript('CREATE TABLE repos(id,working_path); CREATE TABLE runs(id,repo_id,branch,worktree_dir,created_at,updated_at); CREATE TABLE run_agent_sessions(run_id,agent,session_id); CREATE TABLE agent_invocations(id,run_id,purpose,agent,model,model_provider,session_key,session_mode,started_at,completed_at,input_tokens,output_tokens,cache_read_tokens,cache_creation_tokens,delta_input_tokens,delta_output_tokens,delta_cache_read_tokens);')
    cli('import')
    # Seed the isolated store with normalized synthetic quota records (no quota CLI or credentials).
    with sqlite3.connect(store) as db:
        for p,remaining in [('claude',60),('codex',70)]:
            q=dict(provider=p,observed=N,generated=N,status='fresh',window='weekly',label='week',kind='weekly',start=N-86400,end=N+6*86400,remaining=remaining)
            db.execute('INSERT INTO quota VALUES (?,?)',(p,json.dumps(q)))
    cli('report')
    text = cli('text')
    (E/'synthetic-summary.txt').write_text(text)
    shutil.copyfile(output,E/'synthetic-report.html')
    assert 'main chat: 20.00% (1); supervision: 20.00% (1)' in text
    assert 'Claude: 40.00% used, 60.00% left' in text
    assert 'Codex: 30.00% used, 70.00% left' in text
    assert re.search(r'1,240\s+30.00%\s+codex\s+main chat\s+codex-main',text)
    data=payload()
    assert [(w['provider'],w['used']) for w in data['windows'][:2]] == [('claude',40),('codex',30)]
    assert text.encode() == output.with_name('summary.txt').read_bytes()
    assert all(ord(c)<128 for c in text) and '\x1b' not in text and len(text.splitlines())<40
    log.append('Independent oracle: equal Claude records split 40% used into 20% main + 20% supervision; sole Codex record receives 30%. HTML payload and saved stdout agree.\n')
    old_store=store.read_bytes(); old_html=output.read_bytes(); old_summary=output.with_name('summary.txt').read_bytes()
    record('pi','not-yet-imported',2000)
    with sqlite3.connect(ledger) as db:
        db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?)',('new','repo','fm/new',str(H),N-500,N+500))
        db.execute('INSERT INTO run_agent_sessions VALUES (?,?,?)',('new','pi','main'))
        db.execute('INSERT INTO agent_invocations VALUES ('+','.join('?'*17)+')',('active','new','review','pi','claude-opus-5-5','anthropic','main','cold',N-200,None,100,20,200,0,100,20,200))
    assert cli('text',N+86400)==text
    with sqlite3.connect(ledger) as db:
        db.execute('UPDATE agent_invocations SET completed_at=?',(N,))
        db.execute('DROP TABLE run_agent_sessions')
    assert cli('text')==text
    assert store.read_bytes()==old_store and output.read_bytes()==old_html
    assert output.with_name('summary.txt').stat().st_mode & 0o777 == 0o600
    store.unlink(); ledger.unlink()
    assert cli('text')==text and not store.exists() and not ledger.exists()
    assert output.with_name('summary.txt').read_bytes()==old_summary
    log.append('Saved-output guard: new source, new run/link, invocation completion, broken ledger, deleted ledger/store, and next-day --now did not alter stdout or recreate deleted inputs.\n')
    # Separate empty-store rendering exercises fallback and incomplete coverage.
    cli('report')
    empty=cli('text')
    assert 'No sessions in these windows.' in empty
    (E/'empty-summary.txt').write_text(empty)
    for p in roots.values():
        for f in p.glob('*.jsonl'): f.unlink()
    for i in range(12): record('pi','session-'+str(i),100+i)
    record('pi','partial',None)
    record('pi','unknown',400,'unsupported-model')
    record('pi','outside-window',2000,ts=N-2*86400)
    cli('import')
    with sqlite3.connect(store) as db:
        db.execute('INSERT INTO quota VALUES (?,?)',('claude',json.dumps(dict(provider='claude',observed=N,generated=N,status='fresh',window='weekly',label='week',kind='weekly',start=N-86400,end=N+6*86400,remaining=60))))
    cli('report')
    partial=cli('text')
    assert 'outside-wind' not in partial
    top=partial.split('Task / session\n')[1].split('\n\n')[0].splitlines()
    assert len(top)==10 and '900 *' in top[0] and 'Unknown' in top[0]
    assert 'Unknown' in top[1] and 'unknown' in top[1]
    tokens=[int(row.split()[0].replace(',','')) for row in top]
    assert tokens==sorted(tokens,reverse=True)
    (E/'partial-summary.txt').write_text(partial)
    cli('report',N+10800)
    fallback=cli('text')
    assert 'Claude: quota unavailable; last 7 days,' in fallback and 'outside-wind' in fallback
    (E/'fallback-summary.txt').write_text(fallback)
    log.append('Coverage guard: incomplete token total is starred; unsupported model quota is Unknown; only ten rows appear in descending tokens; old session excluded from active quota window and included in stale-quota seven-day fallback.\n')
finally:
    shutil.rmtree(W)
    (E/'live-cli-transcript.txt').write_text('\n'.join(log))
print('All isolated public-CLI scenarios completed; disposable inputs removed.')
