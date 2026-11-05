import importlib.util,json,os,sqlite3,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('cases',Path('tests/usage_report_cases.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
t=m.UsageReport();t.setUp()
evidence=Path('~/.no-mistakes/evidence/01M6MEX9WY04H2GWMWE52JER8G')
log=[]
def cli(cmd,*args):
 r=t.cli(cmd,*args);log.append('$ fm-usage-report.sh '+cmd+' '+ ' '.join(args)+'\n'+r.stdout);return r
try:
 data=t.home/'data';data.mkdir()
 (t.home/'projects/demo').mkdir(parents=True)
 (data/'projects.md').write_text('- demo [no-mistakes] - Synthetic demo\n')
 (data/'backlog.md').write_text('- [ ] demo-worker - Synthetic worker (repo: demo) (kind: ship)\n')
 (data/'demo-worker').mkdir();(data/'demo-worker/brief.md').write_text('Synthetic task record\n')
 sessions=[('main-large','claude','main',120000),('main-small','codex','main',1200),('supervisor','claude','supervision',40000),('worker-demo','codex','worker',65000),('grok-session','grok','none',8000),('unproven','claude','none',9000),('unknown-model','claude','none',500),('outside-window','claude','none',999999),('</script><script>window.INJECTED=1</script>','grok','none',2000)]
 for sid,provider,role,tokens in sessions:
  model={'claude':'claude-opus-5-5','codex':'gpt-6.1-sol','grok':'grok-4.7'}[provider]
  if sid=='unknown-model':model='unsupported-model'
  ts=t.now-(10*86400 if sid=='outside-window' else 100)
  rows=t.pi(sid,ts=ts,cwd=str(t.home) if role=='main' else '/synthetic/demo',model=model)
  rows[-1]['message']['provider']={'claude':'anthropic','codex':'openai','grok':'xai'}[provider]
  rows[-1]['message']['usage'].update(input=tokens,cacheRead=tokens//2,cacheWrite=10,cacheWrite1h=0,output=100,totalTokens=tokens+tokens//2+110)
  if role=='worker':
   rows.insert(1,dict(type='message',timestamp=m.iso(ts-99),message=dict(role='user',content=f'FIRSTMATE_OP: v1 launch-brief: synthetic\nYour steering inbox is `{t.home}/state/demo-worker.inbox`; only this task.\nSECRET_LAUNCH')))
  t.write('supervision' if role=='supervision' else 'pi',rows,'fixture-'+str(len(list(t.roots['pi'].glob('*.jsonl'))))+'.jsonl')
 # Retain a review invocation and a native source with the same session ID: ledger owns overlap.
 t.nm_db();t.write('pi',t.pi('native-review'),'review.jsonl')
 (t.root/'logs').mkdir();(t.root/'logs/run1').write_text('Synthetic review run\n')
 cli('refresh','--now',str(t.now))
 report=t.rendered_report()
 before=t.records();cli('import');cli('report','--now',str(t.now));assert t.records()==before
 report=t.rendered_report()
 windows={w['provider']:w for w in report['windows']}
 assert windows['claude']['used']==30 and windows['codex']['used']==30
 assert windows['claude']['fit']['seeded'] and not windows['grok']['available']
 for p in ['claude','codex']:
  w=windows[p];total=sum(f['priced']*w['allocation_rate'] for f in report['facts'] if f['provider']==p and w['start']<=f['time']<w['end'] and f['priced'] is not None)
  assert abs(total-30)<1e-9
 roles={f['session']:f['role'] for f in report['facts']}
 assert roles['main-large']=='main chat' and roles['supervisor']=='supervision' and roles['worker-demo']=='worker' and roles['unproven']=='unassigned'
 assert any(f['role']=='reviewer' for f in report['facts'])
 assert report['excluded']['native_pipeline']==1
 assert not any(f['session']=='native-review' for f in report['facts'])
 text=t.output.read_text();assert 'SECRET_' not in text and '</script><script>window.INJECTED' not in text
 cli('install','--launch-agents',str(t.root/'LaunchAgents'))
 plist=next((t.root/'LaunchAgents').glob('*.plist'))
 import plistlib
 definition=plistlib.loads(plist.read_bytes());assert definition['StartInterval']==3600
 log.append('Generated scheduler definition: '+json.dumps(definition,default=str,indent=2))
 cli('uninstall','--launch-agents',str(t.root/'LaunchAgents'));assert not plist.exists()
 (evidence/'synthetic-report.html').write_text(text)
 (evidence/'accounting-observed.json').write_text(json.dumps(dict(windows=report['windows'],roles=roles,excluded=report['excluded'],facts=report['facts']),indent=2))
 log.append('Observed accounting: '+json.dumps(dict(facts=len(report['facts']),roles=roles,excluded=report['excluded'],claude_allocated_percent=30,codex_allocated_percent=30),indent=2))
 (evidence/'cli-transcript.txt').write_text('\n'.join(log))
 print('Synthetic report saved; independently checked role evidence, replay identity, overlap ownership, 30% allocation, privacy and definition-only install/remove.')
finally:
 t.tmp._finalizer.detach()
 Path('.test-usage/fixture-root.txt').write_text(str(t.root))
