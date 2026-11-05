"""Synthetic fixtures through fm-usage-report's public executable and SQLite output."""
import datetime as dt
import json
import os
from pathlib import Path
import plistlib
import re
import sqlite3
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / 'bin/fm-usage-report.sh'


def iso(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat()


class UsageReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='fm-usage-report-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root/'home'
        self.home.mkdir()
        (self.home/'state').mkdir()
        self.now = int(time.time())
        self.roots = {k: self.root/k for k in ['pi', 'supervision', 'claude', 'codex']}
        for path in self.roots.values():
            path.mkdir()
        self.nm = self.root/'nm.sqlite'
        self.output = self.root/'report.html'
        self.env = dict(os.environ, FM_HOME=str(self.home))
        for key in ['FM_DATA_OVERRIDE', 'FM_STATE_OVERRIDE', 'FM_PROJECTS_OVERRIDE']:
            self.env.pop(key, None)
        self.fakebin = self.root/'fakebin'
        self.fakebin.mkdir()
        self.env['PATH'] = str(self.fakebin) + os.pathsep + self.env['PATH']
        self.quota = {'generatedAt': iso(self.now), 'providers': [dict(provider=p,
            accountKeys=['SENSITIVE_ACCOUNT_DO_NOT_STORE'], state={'status': 'fresh', 'stale': False},
            windows=[dict(id='weekly', label='week', kind='weekly', startsAt=iso(self.now-86400),
                          resetsAt=iso(self.now+6*86400), percentRemaining=70)]) for p in ['claude', 'codex']]}
        self.quota_file = self.root/'quota.json'
        self.quota_file.write_text(json.dumps(self.quota))
        script = self.fakebin/'quota-axi'
        script.write_text('#!/usr/bin/env python3\nimport os,sys\nfrom pathlib import Path\n'
            'assert sys.argv[1:]==["--provider","claude,codex,grok","--json","--no-credential-refresh"]\n'
            'assert not sys.stdin.isatty()\n'
            'print(Path(os.environ["FAKE_QUOTA"]).read_text())\n')
        script.chmod(0o700)
        self.env['FAKE_QUOTA'] = str(self.quota_file)

    def cli(self, command, *extra):
        return subprocess.run([str(CLI), command, '--pi-root', str(self.roots['pi']),
            '--supervision-root', str(self.roots['supervision']), '--claude-root', str(self.roots['claude']),
            '--codex-root', str(self.roots['codex']), '--nm-db', str(self.nm), '--output', str(self.output), *extra],
            env=self.env, capture_output=True, text=True, check=True)

    def write(self, source, rows, name='session.jsonl', append=False):
        path = self.roots[source]/name
        with path.open('a' if append else 'w') as f:
            for r in rows:
                f.write(json.dumps(r)+'\n')
        return path

    def pi(self, sid='alpha', ts=None, cwd='/synthetic/project', model='claude-opus-5-5', **kw):
        ts = ts or self.now-100
        return [dict(type='session', id=sid, timestamp=iso(ts-100), cwd=cwd),
            dict(type='message', id='entry-'+sid, timestamp=iso(ts), message=dict(
                role='assistant', model=model, provider='anthropic', thinkingLevel='high',
                responseId='response-'+sid, content='SECRET_PROMPT_OR_RESPONSE',
                usage=dict(input=100, cacheRead=200, cacheWrite=10, output=30,
                           reasoning=25, cacheWrite1h=3, totalTokens=340, **kw)))]

    def records(self, table='facts'):
        with sqlite3.connect(self.home/'data/usage-report/usage.sqlite') as db:
            return [json.loads(r[0]) for r in db.execute('SELECT data FROM '+table)]

    def rendered_report(self):
        match = re.search(r'const DATA\s*=\s*(.*);\n', self.output.read_text())
        self.assertIsNotNone(match)
        return json.loads(match[1])

    def report(self):
        self.cli('report')
        return self.rendered_report()

    def nm_db(self, mode='cold', deltas=(100, 20, 200), completed=True):
        db = sqlite3.connect(self.nm)
        db.executescript('''
            CREATE TABLE repos(id,working_path);
            CREATE TABLE runs(id,repo_id,branch,worktree_dir,created_at,updated_at);
            CREATE TABLE run_agent_sessions(run_id,agent,session_id);
            CREATE TABLE agent_invocations(id,run_id,purpose,agent,model,model_provider,session_key,session_mode,
                started_at,completed_at,input_tokens,output_tokens,cache_read_tokens,cache_creation_tokens,
                delta_input_tokens,delta_output_tokens,delta_cache_read_tokens);
        ''')
        db.execute('INSERT INTO repos VALUES (?,?)', ('repo', '/synthetic/project'))
        db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?)',
                   ('run1', 'repo', 'fm/test', '/synthetic/review', self.now-1000, self.now))
        db.execute('INSERT INTO run_agent_sessions VALUES (?,?,?)', ('run1', 'pi', 'native-review'))
        db.execute('INSERT INTO agent_invocations VALUES ('+','.join('?'*17)+')',
            ('inv1','run1','review','pi','claude-opus-5-5','anthropic','native-review',mode,
             self.now-200,self.now-100 if completed else None,100,20,200,10,*deltas))
        db.commit()
        db.close()

    def test_pi_operations_compaction_nested_and_copy_dedup(self):
        rows=self.pi()
        rows.extend([dict(type='usage', id='warm', timestamp=iso(self.now-80), provider='anthropic',
             model='claude-opus-5-5', usage=dict(input=0,cacheRead=40,cacheWrite=0,output=0)),
             dict(type='compaction',id='compact', timestamp=iso(self.now-70),
                  usage=dict(input=20,cacheRead=0,cacheWrite=0,output=4)),
             dict(type='message',id='nested',timestamp=iso(self.now-60),message=dict(role='toolResult',
                  content='SECRET_TOOL_OUTPUT',usage=dict(input=2,cacheRead=0,cacheWrite=0,output=3)))])
        self.write('pi',rows)
        copied=[dict(rows[0],id='copy'),*rows[1:]]
        self.write('pi',copied,'copy.jsonl')
        self.cli('import')
        facts=self.records()
        self.assertEqual(len(facts),4)
        self.assertEqual(sum(f['output'] for f in facts),37)
        self.assertEqual(sum(f['provider']=='unknown' for f in facts),2)
        before=self.records()
        self.cli('import')
        self.assertEqual(self.records(),before)
        self.assertNotIn('SECRET_',json.dumps(facts))

    def test_supervision_store_and_unassigned_not_guessed_main(self):
        self.write('supervision',self.pi('supervision'))
        self.write('pi',self.pi('ordinary'))
        self.cli('import')
        self.assertEqual({f['role'] for f in self.records()},{'supervision','unassigned'})

    def test_home_main_sessions_include_history_but_not_supervision_or_workers(self):
        self.write('pi',self.pi('past-main',ts=self.now-14*86400,cwd=str(self.home)),'past.jsonl')
        self.write('pi',self.pi('current-main',cwd=str(self.home)),'current.jsonl')
        self.write('pi',self.pi('unknown-worker',cwd='/synthetic/pool/1/project'),'worker.jsonl')
        self.write('supervision',self.pi('branch',cwd=str(self.home)))
        self.cli('import')
        roles={f['session']:f['role'] for f in self.report()['facts']}
        self.assertEqual(roles,{'past-main':'main chat','current-main':'main chat',
                                'unknown-worker':'unassigned','branch':'supervision'})

    def test_branch_uses_each_response_provider_model_not_parent_labels_or_current_pin(self):
        config=self.home/'config';config.mkdir()
        (config/'supervision-branch-model').write_text('openai/gpt-6.1-sol\n')
        rows=self.pi('branch',cwd=str(self.home))
        rows.insert(1,dict(type='model_change',provider='anthropic',modelId='claude-opus-5-5'))
        response=dict(rows[-1])
        response['id']='openai-entry'
        response['provider']='anthropic'  # Envelope / selected-model labels are not usage evidence.
        response['model']='claude-opus-5-5'
        response['message']=dict(rows[-1]['message'],provider='openai',model='gpt-6.1-sol',responseId='openai-response')
        rows.append(response)
        self.write('supervision',rows)
        self.cli('import')
        facts=self.report()['facts']
        self.assertEqual({(f['provider'],f['model'],f['role']) for f in facts},
            {('claude','claude-opus-5-5','supervision'),('codex','gpt-6.1-sol','supervision')})
        claude=next(f for f in facts if f['provider']=='claude')
        codex=next(f for f in facts if f['provider']=='codex')
        self.assertAlmostEqual(claude['priced'],(100*4+200*.2+7*5+3*8+30*20)/1e6)
        self.assertAlmostEqual(codex['priced'],(100*2+200*.1+10*2.5+30*10)/1e6)

    def test_historical_worker_launch_bindings_survive_cleanup_and_pool_reuse(self):
        data=self.home/'data';data.mkdir()
        (self.home/'projects/fixture').mkdir(parents=True)
        (data/'projects.md').write_text('- fixture [no-mistakes] - Fixture project\n')
        (data/'backlog.md').write_text('- [x] old-worker - Old task (repo: fixture) (kind: ship)\n'
            '- [ ] new-scout - New task (repo: fixture) (kind: scout)\n')
        cwd='/synthetic/pool/1/fixture'
        state_root=self.home/'state'
        metadata=state_root/'old-worker.meta'
        metadata.write_text(f'worktree={cwd}\nproject={self.home.resolve()}/projects/fixture\nkind=ship\n'
            f'spawn_gen=s{int(self.now-10100)}.1.1\nsession_id=old-session\n')
        for sid,task,ts in [('old-session','old-worker',self.now-10000),('new-session','new-scout',self.now-100)]:
            rows=self.pi(sid,ts=ts,cwd=cwd,model='gpt-6.1-sol')
            rows[1]['message']['provider']='openai'
            body='\u2063FIRSTMATE_OP: v1 launch-brief: # Current worker role contract\n'
            body+=f'Your steering inbox is `{self.home}/state/{task}.inbox`; this exact path belongs to this task.\nSECRET_WORKER_PROMPT'
            rows.insert(1,dict(type='message',timestamp=iso(ts-99),message=dict(role='user',content=body)))
            self.write('pi',rows,sid+'.jsonl')
        peer=self.pi('unbound-peer',ts=self.now-5000,cwd=cwd,model='gpt-6.1-sol')
        peer[-1]['message']['provider']='openai'
        self.write('pi',peer,'peer.jsonl')
        inherited=self.pi('inherited-child',ts=self.now,cwd=cwd,model='gpt-6.1-sol')
        inherited[-1]['message']['provider']='openai'
        inherited.insert(1,dict(type='message',timestamp=iso(self.now-10000),message=dict(role='user',content=
            f'FIRSTMATE_OP: v1 launch-brief: copied parent\nYour steering inbox is `{self.home}/state/old-worker.inbox`; copied launch.')))
        self.write('pi',inherited,'inherited.jsonl')
        self.cli('import')
        facts={f['session']:f for f in self.report()['facts']}
        self.assertEqual(facts['unbound-peer']['role'],'unassigned')
        self.assertEqual(facts['inherited-child']['role'],'unassigned')
        self.assertEqual(len(self.records('bindings')),3)
        self.assertEqual((facts['old-session']['role'],facts['old-session']['task']),('worker','old-worker'))
        self.assertEqual((facts['new-session']['role'],facts['new-session']['task']),('scout','new-scout'))
        self.assertEqual(facts['old-session']['project'],str(self.home.resolve()/'projects/fixture'))
        before=self.records()
        # A v1 database already has complete cursors but lacks launch bindings.
        with sqlite3.connect(data/'usage-report/usage.sqlite') as db:
            for key, encoded in db.execute('SELECT key,data FROM bindings').fetchall():
                if json.loads(encoded).get('origin')=='pi-launch':
                    db.execute('DELETE FROM bindings WHERE key=?',(key,))
            for path, encoded in db.execute('SELECT path,state FROM cursors').fetchall():
                state=json.loads(encoded);state.pop('parser_version',None)
                db.execute('UPDATE cursors SET state=? WHERE path=?',(json.dumps(state),path))
        self.cli('import')
        self.assertEqual(len(self.records()),len(before))
        self.assertEqual(next(f for f in self.report()['facts'] if f['session']=='old-session')['role'],'worker')
        self.assertEqual(next(f for f in self.report()['facts'] if f['session']=='new-session')['role'],'scout')
        metadata.unlink()
        (data/'backlog.md').unlink()
        self.cli('import')
        self.assertEqual(self.records(),before)
        self.assertEqual(next(f for f in self.report()['facts'] if f['session']=='old-session')['role'],'worker')
        self.assertNotIn('SECRET_WORKER_PROMPT',json.dumps(self.records('bindings')))
        with sqlite3.connect(data/'usage-report/usage.sqlite') as db:
            cursors=[json.loads(r[0]) for r in db.execute('SELECT state FROM cursors')]
        self.assertNotIn('SECRET_WORKER_PROMPT',json.dumps(cursors))

    def test_claude_fragments_max_counters_not_line_sum(self):
        rows=[]
        for output in [2,12,8,12]:
            rows.append(dict(timestamp=iso(self.now-10),sessionId='cc1',cwd='/project',uuid=str(output),
                message=dict(role='assistant',id='message1',model='claude-opus-5-5',content='SECRET',
                    usage=dict(input_tokens=50,cache_read_input_tokens=100,cache_creation_input_tokens=10,output_tokens=output))))
        self.write('claude',rows)
        self.cli('import')
        f=self.records()[0]
        self.assertEqual((len(self.records()),f['fresh'],f['read'],f['output']),(1,50,100,12))
        self.cli('import')
        self.assertEqual(len(self.records()),1)

    def test_pi_claude_transport_response_overlap(self):
        rows=self.pi(cwd=str(self.home))
        rows[1]['message'].update(provider='pi-claude-cli')
        self.write('pi',rows)
        self.write('claude',[dict(timestamp=iso(self.now-100),sessionId='alpha',message=dict(
            role='assistant',id='response-alpha',model='claude-opus-5-5',usage=dict(input_tokens=100,
            cache_read_input_tokens=200,cache_creation_input_tokens=10,output_tokens=30)))])
        self.cli('import')
        facts=self.report()['facts']
        self.assertEqual(len(facts),1)
        self.assertEqual((facts[0]['source'],facts[0]['session'],facts[0]['role']),('pi','alpha','main chat'))
        self.assertEqual(facts[0]['locator'],str(self.roots['pi']/'session.jsonl'))

    def test_transport_overlap_repairs_native_roles_in_both_orders_and_replays(self):
        data=self.home/'data';data.mkdir()
        (data/'backlog.md').write_text('- [ ] bound-worker - Fixture (kind: ship)\n')
        expected={}
        for provider in ['claude','codex']:
            for role in ['main chat','supervision','worker']:
                sid=provider+'-'+role.replace(' ','-')
                model='claude-opus-5-5' if provider=='claude' else 'gpt-6.1-sol'
                expected[sid]=(provider,model,role)
                if provider=='claude':
                    transport=[dict(timestamp=iso(self.now-100),sessionId='transport-'+sid,message=dict(
                        role='assistant',id='response-'+sid,model=model,usage=dict(input_tokens=120,
                        cache_read_input_tokens=200,cache_creation_input_tokens=10,output_tokens=40)))]
                else:
                    transport=[dict(type='session_meta',payload=dict(id='transport-'+sid,cwd='/transport',model_provider='openai')),
                        dict(type='turn_context',payload=dict(model=model,effort='xhigh')),
                        dict(type='token_usage_record',timestamp=iso(self.now-100),payload=dict(
                            response_id='response-'+sid,usage=dict(input_tokens=320,cached_input_tokens=200,output_tokens=40))),
                        dict(type='compacted',payload=dict(compaction_response_id='response-'+sid))]
                self.write(provider,transport,sid+'.jsonl')
        self.cli('import')
        self.assertEqual(len(self.records()),6)
        for sid,(_,model,role) in expected.items():
            rows=self.pi(sid,cwd=str(self.home) if role!='worker' else '/synthetic/worker',model=model)
            rows[-1]['message']['provider']='pi-claude-cli' if sid.startswith('claude') else 'openai'
            if role=='worker':
                rows.insert(1,dict(type='message',timestamp=iso(self.now-199),message=dict(role='user',content=
                    f'FIRSTMATE_OP: v1 launch-brief: fixture\nYour steering inbox is `{self.home}/state/bound-worker.inbox`; fixture.')))
            self.write('supervision' if role=='supervision' else 'pi',rows,sid+'.jsonl')
        self.cli('import')
        facts=self.report()['facts']
        self.assertEqual({f['session']:(f['provider'],f['model'],f['role']) for f in facts},expected)
        self.assertTrue(all((f['source'],f['fresh'],f['read'],f['write'],f['output'])==('pi',120,200,10,40) for f in facts))
        self.assertTrue(all(f['session_start']==self.now-200 for f in facts))
        self.assertTrue(all(f['task']=='bound-worker' for f in facts if f['role']=='worker'))
        for sid,(provider,model,_) in expected.items():
            if provider=='claude':
                self.write('claude',[dict(timestamp=iso(self.now-100),sessionId='transport-'+sid,message=dict(
                    role='assistant',id='response-'+sid,model=model,usage=dict(input_tokens=110,
                    cache_read_input_tokens=200,cache_creation_input_tokens=10,output_tokens=50)))],sid+'.jsonl',append=True)
            else:
                self.write('codex',[dict(type='session_meta',payload=dict(id='updated-transport-'+sid,cwd='/transport',model_provider='openai')),
                    dict(type='turn_context',payload=dict(model=model,effort='xhigh')),
                    dict(type='compacted',payload=dict(compaction_response_id='response-'+sid)),
                    dict(type='token_usage_record',timestamp=iso(self.now-100),payload=dict(
                        response_id='response-'+sid,usage=dict(input_tokens=310,cached_input_tokens=200,output_tokens=50)))],sid+'.jsonl')
        self.cli('import')
        facts=self.report()['facts']
        self.assertEqual({f['session']:(f['provider'],f['model'],f['role']) for f in facts},expected)
        self.assertTrue(all(f['fresh']==120 and f['output']==50 for f in facts))
        self.assertEqual(len(facts),6)
        with sqlite3.connect(data/'usage-report/usage.sqlite') as db:
            for key,encoded in db.execute('SELECT key,data FROM facts').fetchall():
                fact=json.loads(encoded)
                fact.update(source='claude' if fact['provider']=='claude' else 'codex-compaction',
                    session='transport-'+fact['session'],cwd='/transport',role='unassigned',
                    evidence='No proven role binding',locator='/transport/log.jsonl',session_start=self.now-100)
                db.execute('UPDATE facts SET data=? WHERE key=?',(json.dumps(fact),key))
            for path,encoded in db.execute('SELECT path,state FROM cursors').fetchall():
                state=json.loads(encoded);state['parser_version']=2
                db.execute('UPDATE cursors SET state=? WHERE path=?',(json.dumps(state),path))
        self.cli('import')
        facts=self.report()['facts']
        self.assertEqual({f['session']:(f['provider'],f['model'],f['role']) for f in facts},expected)
        self.assertTrue(all(f['source']=='pi' and f['fresh']==120 and f['output']==50 for f in facts))
        self.assertTrue(all(f['session_start']==self.now-200 and f['locator'].startswith(str(self.root)) for f in facts))
        self.assertEqual(len(facts),6)

    def codex(self):
        return [dict(type='session_meta',payload=dict(id='thread',cwd='/synthetic/codex',model_provider='openai')),
                dict(type='turn_context',payload=dict(model='gpt-6.1-sol',effort='xhigh'))]

    def token_count(self, tokens, cached=0, output=10):
        return dict(type='event_msg',timestamp=iso(self.now-10),payload=dict(type='token_count',info=dict(
            total_token_usage=dict(input_tokens=tokens,cached_input_tokens=cached,output_tokens=output),
            last_token_usage=dict(input_tokens=999999,output_tokens=999999))))

    def test_codex_advancing_totals_and_counter_reset(self):
        self.write('codex',[*self.codex(),self.token_count(100,20),self.token_count(100,20),
                           self.token_count(150,30,20),self.token_count(50,10),self.token_count(70,10,15)])
        self.cli('import')
        facts=self.report()['facts']
        self.assertEqual(sum(f['fresh'] for f in facts),140)
        self.assertEqual(sum(f['read'] for f in facts),30)
        self.assertEqual(sum(f['output'] for f in facts),25)
        self.assertEqual(len(facts),3)

    def test_codex_overlapping_responses_do_not_stack_with_snapshots(self):
        response=dict(type='token_usage_record',timestamp=iso(self.now-5),payload=dict(response_id='codex-response',
            usage=dict(input_tokens=100,cached_input_tokens=20,output_tokens=10,total_tokens=110)))
        self.write('codex',[*self.codex(),self.token_count(100,20),response])
        clone=self.codex();clone[0]['payload']['id']='child'
        self.write('codex',[*clone,response],'fork.jsonl')
        self.cli('import')
        facts=self.report()['facts']
        self.assertEqual(len(facts),1)
        self.assertEqual((facts[0]['fresh'],facts[0]['read'],facts[0]['output']),(80,20,10))

    def test_codex_snapshots_own_normal_usage_not_response_records(self):
        self.write('codex',[*self.codex(),self.token_count(100,20),dict(type='token_usage_record',
            timestamp=iso(self.now-5),payload=dict(response_id='r1',usage=dict(input_tokens=100,
            cached_input_tokens=20,output_tokens=10,total_tokens=110)))])
        self.cli('import')
        report=self.report()
        self.assertEqual(len(report['facts']),1)
        self.assertEqual(report['facts'][0]['fresh'],80)
        self.assertEqual(report['facts'][0]['source'],'codex-cumulative')

    def test_codex_compaction_is_extra_only_when_not_already_in_snapshot(self):
        def response(rid, amount):
            return dict(type='token_usage_record',timestamp=iso(self.now-5),payload=dict(response_id=rid,
                usage=dict(input_tokens=amount,cached_input_tokens=0,output_tokens=10)))
        def marker(rid):
            return dict(type='compacted',payload=dict(compaction_response_id=rid))
        self.write('codex',[*self.codex(),self.token_count(100),response('covered',100),
            self.token_count(200,0,20),marker('covered'),response('extra',300),marker('extra')])
        self.cli('import')
        facts=self.report()['facts']
        self.assertEqual(sum(f['fresh'] for f in facts),500)
        self.assertEqual(sum(f['output'] for f in facts),30)
        self.assertEqual(sum(f['source']=='codex-compaction' for f in facts),1)
        self.cli('import')
        self.assertEqual(len(self.report()['facts']),3)

    def test_codex_inherited_prefix_final_baseline_and_model_switch(self):
        rows=self.codex()
        rows[0]['timestamp']=iso(self.now-100)
        rows[0]['payload']['source']={'subagent':{'thread_spawn':{'parent_thread_id':'parent'}}}
        first=self.token_count(100);first['timestamp']=iso(self.now-100)
        second=self.token_count(200,0,20);second['timestamp']=iso(self.now-100+.02)
        third=self.token_count(300,10,30);third['timestamp']=iso(self.now-50)
        self.write('codex',[*rows,first,second,dict(type='turn_context',payload=dict(model='gpt-other')),third])
        self.cli('import')
        facts=self.report()['facts']
        self.assertEqual(len(facts),1)
        self.assertEqual((facts[0]['fresh'],facts[0]['read'],facts[0]['output']),(90,10,10))
        self.assertEqual(facts[0]['model'],'gpt-other')

    def test_partial_line_truncation_and_rotation_replay(self):
        rows=self.pi()
        path=self.write('pi',[rows[0]])
        line=json.dumps(rows[1])
        with path.open('a') as f:f.write(line[:60])
        self.cli('import')
        self.assertEqual(len(self.records()),0)
        with path.open('a') as f:f.write(line[60:]+'\n')
        self.cli('import')
        self.assertEqual(len(self.records()),1)
        path.unlink();self.write('pi',rows)
        self.cli('import')
        self.assertEqual(len(self.records()),1)
        self.write('pi',rows)
        self.cli('import')
        self.assertEqual(len(self.records()),1)

    def test_native_pipeline_overlap_and_invocation_delta_accounting(self):
        self.nm_db(mode='resumed',deltas=(30,5,40))
        self.write('pi',self.pi('native-review',cwd='/synthetic/review'))
        self.cli('import')
        report=self.report()
        self.assertEqual(len(report['facts']),1)
        f=report['facts'][0]
        self.assertEqual((f['role'],f['fresh'],f['read'],f['write'],f['output']),('reviewer',30,40,None,5))
        self.assertEqual(report['excluded']['native_pipeline'],1)

    def test_legacy_resumed_unknown_and_possible_overlap_quarantined(self):
        self.nm_db(mode='resumed',deltas=(None,None,None))
        self.write('pi',self.pi('unproved',cwd='/synthetic/review'))
        self.cli('import')
        report=self.report()
        self.assertEqual(len(report['facts']),1)
        self.assertIsNone(report['facts'][0]['fresh'])
        self.assertEqual(report['excluded']['possible_pipeline'],1)
        self.assertEqual(report['excluded']['possible_records'][0]['session'],'unproved')

    def test_active_invocation_refreshed_after_completion(self):
        self.nm_db(completed=False)
        self.cli('import')
        self.assertEqual(self.records(),[])
        with sqlite3.connect(self.nm) as db:db.execute('UPDATE agent_invocations SET completed_at=?',(self.now,))
        self.cli('import')
        self.assertEqual(len(self.records()),1)

    def test_task_join_validity_and_retention_after_cleanup(self):
        path=self.home/'state/task.meta'
        path.write_text(f'kind=scout\nspawn_gen=s{self.now-500}.1.xyz\nworktree=/synthetic/project\nproject=/projects/fixture\nbranch=fm/test\n')
        self.write('pi',self.pi('new',ts=self.now-100))
        self.write('pi',self.pi('before-reuse',ts=self.now-10000),'old.jsonl')
        self.cli('import')
        facts=self.report()['facts']
        self.assertEqual({f['session']:f['role'] for f in facts},{'new':'scout','before-reuse':'unassigned'})
        path.unlink()
        with sqlite3.connect(self.home/'data/usage-report/usage.sqlite') as db:
            db.execute('INSERT INTO bindings VALUES (?, ?)', ('legacy-manual',json.dumps(dict(
                source='pi',session='before-reuse',role='main chat',evidence='Legacy manual override'))))
        self.cli('import')
        self.assertEqual({f['session']:f['role'] for f in self.report()['facts']},{'new':'scout','before-reuse':'unassigned'})

    def test_quota_sampling_privacy_fallback_and_scale(self):
        self.write('pi',self.pi())
        self.cli('refresh')
        report=self.report()
        claude=next(w for w in report['windows'] if w['provider']=='claude')
        self.assertEqual(claude['used'],30)
        self.assertAlmostEqual(sum(f['priced']*claude['allocation_rate'] for f in report['facts'] if f['provider']=='claude'),30)
        self.assertTrue(claude['fit']['seeded'])
        self.assertAlmostEqual(claude['fit']['rate'],1/13.5)
        grok=next(w for w in report['windows'] if w['provider']=='grok')
        self.assertFalse(grok['available'])
        self.assertNotIn('SENSITIVE_ACCOUNT',json.dumps(self.records('quota')))
        before=len(self.records('quota'));self.cli('sample');self.assertEqual(len(self.records('quota')),before)
        self.quota['providers'][0]['windows'][0]['resetsAt']=iso(self.now+6*86400+0.36)
        self.quota_file.write_text(json.dumps(self.quota))
        self.cli('sample')
        self.assertEqual(len(self.records('quota')),before+1)
        self.assertEqual((self.home/'data/usage-report/usage.sqlite').stat().st_mode & 0o777,0o600)

    def test_weekly_fit_requires_hourly_fresh_same_window_pairs(self):
        end=self.now+86400
        rows=[]
        for i in range(5):
            t=self.now-(5-i)*3600
            rows.extend(self.pi(str(i),ts=t+600))
        self.write('pi',rows)
        self.cli('import')
        # Public sampler ingests historical source observation times, not fabricated DB rows.
        for i in range(5):
            t=self.now-(5-i)*3600
            q=dict(generatedAt=iso(t),providers=[dict(provider='claude',state=dict(status='fresh',stale=False),
                windows=[dict(id='weekly',label='week',kind='weekly',startsAt=iso(end-7*86400),
                              resetsAt=iso(end+[0, 0.36, 1.24, -0.36, 0][i]),percentRemaining=90-i*2)])])
            self.quota_file.write_text(json.dumps(q));self.cli('sample')
        report=self.report()
        fit=next(w['fit'] for w in report['windows'] if w['provider']=='claude')
        self.assertFalse(fit['seeded'])
        self.assertEqual(fit['samples'],4)
        expected=2/report['facts'][0]['priced']
        self.assertAlmostEqual(fit['rate'],expected)
        self.cli('report')
        self.assertEqual(next(w['fit'] for w in self.report()['windows'] if w['provider']=='claude'),fit)

    def test_quota_resets_do_not_train_a_rate(self):
        for i in range(5):
            t=self.now-18000+i*3600
            rows=self.pi(str(i),ts=t+300)
            self.write('pi',rows,str(i)+'.jsonl')
            q=dict(generatedAt=iso(t),providers=[dict(provider='claude',state=dict(status='fresh',stale=False),
                windows=[dict(id='weekly',label='week',kind='weekly',startsAt=iso(t-10000),
                              resetsAt=iso(self.now+(i+1)*604800),percentRemaining=90-i*2)])])
            self.quota_file.write_text(json.dumps(q));self.cli('sample')
        self.cli('import')
        fit=next(w['fit'] for w in self.report()['windows'] if w['provider']=='claude')
        self.assertTrue(fit['seeded'])
        self.assertEqual(fit['samples'],0)

    def test_unavailable_stale_multiple_lanes_not_fitted(self):
        self.quota['providers'][0]['accountKeys']=['one','two']
        self.quota['providers'][1]['state']['stale']=True
        self.quota_file.write_text(json.dumps(self.quota))
        self.cli('sample')
        report=self.report()
        self.assertFalse(any(w['available'] for w in report['windows']))
        self.assertTrue(all(w['fit']['samples']==0 for w in report['windows']))
        self.quota_file.write_text('not JSON SECRET_CREDENTIAL')
        self.cli('sample')
        self.assertTrue(any('read failed' in q['status'] for q in self.records('quota')))
        self.assertNotIn('SECRET_',json.dumps(self.records('quota')))

    def test_price_cache_subsets_long_context_and_unknown_model(self):
        self.write('pi',self.pi())
        self.write('pi',self.pi('unknown',model='unsupported-model'),'unknown.jsonl')
        self.cli('import')
        facts=self.report()['facts']
        f=next(f for f in facts if f['model']=='claude-opus-5-5')
        expected=(100*4+200*.2+7*5+3*8+30*20)/1e6
        self.assertAlmostEqual(f['priced'],expected)
        self.assertIsNone(next(f for f in facts if f['model']=='unsupported-model')['priced'])
        long=self.pi('long',model='grok-4.7')
        long[1]['message']['provider']='xai'
        long[1]['message']['usage'].update(input=200000,cacheRead=0,cacheWrite=0,cacheWrite1h=0,output=100)
        self.write('pi',long,'long.jsonl')
        self.cli('import')
        f=next(f for f in self.report()['facts'] if f['model']=='grok-4.7')
        self.assertAlmostEqual(f['priced'],(200000*4+100*12)/1e6)

    def test_render_inert_data_and_three_page_navigation(self):
        self.write('pi',self.pi('</script><script>alert(1)</script>'))
        self.cli('import')
        report=self.report()
        html=self.output.read_text()
        self.assertNotIn('</script><script>alert',html)
        self.assertIn('\\u003c/script',html)
        self.assertEqual(len(report['facts']),1)
        self.assertIn('Current provider windows',html)
        self.assertIn('All sessions',html)
        self.assertIn('Session usage',html)
        self.assertIn("connect-src 'none'",html)
        self.assertNotIn('SECRET_',html)

    def test_refresh_delayed_quota_uses_post_sample_clock_and_explicit_now(self):
        self.write('pi',self.pi())
        script=self.fakebin/'quota-axi'
        script.write_text('#!/usr/bin/env python3\nimport datetime,json,os,time\nfrom pathlib import Path\n'
            'time.sleep(.05)\n'
            'payload=json.loads(Path(os.environ["FAKE_QUOTA"]).read_text())\n'
            'payload["generatedAt"]=datetime.datetime.now(datetime.timezone.utc).isoformat()\n'
            'print(json.dumps(payload))\n')
        self.cli('refresh')
        rendered=self.rendered_report()
        windows={w['provider']:w for w in rendered['windows']}
        for provider in ['claude','codex']:
            self.assertTrue(windows[provider]['available'])
            self.assertGreater(windows[provider]['generated'],windows[provider]['observed'])
            self.assertGreaterEqual(rendered['generated'],windows[provider]['generated'])
        replay=self.now+3600
        self.cli('refresh','--now',str(replay))
        rendered=self.rendered_report()
        self.assertEqual(rendered['generated'],replay)
        self.cli('report','--now',str(replay))
        self.assertEqual(self.rendered_report(),rendered)
        self.cli('report','--now','0')
        self.assertEqual(self.rendered_report()['generated'],0)
        for invalid in ['nan','inf']:
            with self.assertRaises(subprocess.CalledProcessError) as error:
                self.cli('report','--now',invalid)
            self.assertEqual(error.exception.returncode,2)

    def test_text_shares_match_html_windows_and_session_estimates(self):
        self.write('pi',self.pi('main',cwd=str(self.home)))
        self.write('supervision',self.pi('branch'),'branch.jsonl')
        codex=self.pi('codex-main',cwd=str(self.home),model='gpt-6.1-sol')
        codex[-1]['message']['provider']='openai'
        codex[-1]['message']['usage']['input']=1000
        self.write('pi',codex,'codex.jsonl')
        self.cli('refresh','--now',str(self.now))
        report=self.rendered_report()
        result=self.cli('text','--now',str(self.now)).stdout
        self.assertTrue(result.isascii())
        self.assertLess(len(result.splitlines()),40)
        self.assertNotIn('\x1b',result)
        self.assertEqual(result,(self.output.parent/'summary.txt').read_text())
        self.assertEqual(result.splitlines()[0],
            'Local usage generated '+dt.datetime.fromtimestamp(report['generated'],dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')+
            ' (quota shares are estimates)')
        for window in report['windows']:
            if not window['available']:
                self.assertIn('Grok: quota unavailable; last 7 days, 0 tokens',result)
                continue
            block=result.split(window['provider'].title()+': ',1)[1].splitlines()
            self.assertIn(f"{window['used']:.2f}% used, {window['remaining']:.2f}% left",block[0])
            self.assertIn(dt.datetime.fromtimestamp(window['end'],dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),block[0])
            role_lines=[]
            for line in block[1:]:
                if not line.startswith('  '):break
                role_lines.append(line)
            shares=[float(x) for x in re.findall(r': ([0-9.]+)%',' '.join(role_lines))]
            self.assertAlmostEqual(sum(shares),window['used'],delta=.02)
        window=next(w for w in report['windows'] if w['provider']=='codex')
        fact=next(f for f in report['facts'] if f['session']=='codex-main')
        expected=fact['priced']*window['allocation_rate']
        top=result.split('Task / session\n',1)[1].splitlines()[0]
        self.assertEqual(top.split(),['1,240',f'{expected:.2f}%','codex','main','chat','codex-main'])
        self.assertIn('main chat: 15.00% (1); supervision: 15.00% (1)',result)

    def test_text_ignores_new_run_before_refresh(self):
        self.nm_db(completed=False)
        with sqlite3.connect(self.nm) as db:
            db.execute('DELETE FROM runs')
            db.execute('DELETE FROM run_agent_sessions')
        self.write('pi',self.pi('main',cwd=str(self.home)))
        self.write('supervision',self.pi('branch'),'branch.jsonl')
        self.cli('refresh','--now',str(self.now))
        before=self.cli('text','--now',str(self.now)).stdout
        self.assertIn('main chat: 15.00% (1); supervision: 15.00% (1)',before)
        with sqlite3.connect(self.nm) as db:
            db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?)',
                ('new-run','repo','fm/new',str(self.home),self.now-500,self.now))
            db.execute('INSERT INTO run_agent_sessions VALUES (?,?,?)',('new-run','pi','branch'))
        after=self.cli('text','--now',str(self.now)).stdout
        self.assertEqual(after,before)

    def test_text_preserves_render_time_exclusions_after_ledger_changes(self):
        self.nm_db()
        for sid,cwd,ts in [('possible','/synthetic/review',self.now-150),
                           ('later','/synthetic/review',self.now-50),
                           ('new-link',str(self.home),self.now-50),
                           ('native-review','/synthetic/review',self.now-150)]:
            self.write('pi',self.pi(sid,cwd=cwd,ts=ts),sid+'.jsonl')
        self.cli('refresh','--now',str(self.now))
        report=self.rendered_report()
        self.assertEqual(report['excluded']['possible_pipeline'],2)
        self.assertEqual(report['excluded']['native_pipeline'],1)
        before=self.cli('text','--now',str(self.now)).stdout
        self.assertNotIn('later',before)
        self.assertIn('new-link',before)
        self.assertNotIn('possible',before)
        store=self.home/'data/usage-report/usage.sqlite'
        stored=store.read_bytes()
        html=self.output.read_bytes()
        with sqlite3.connect(self.nm) as db:
            db.execute('UPDATE runs SET created_at=?,updated_at=?,worktree_dir=?',
                (self.now-2000,self.now+500,str(self.home)))
            db.execute('INSERT INTO run_agent_sessions VALUES (?,?,?)',('run1','pi','new-link'))
        after=self.cli('text','--now',str(self.now)).stdout
        self.assertEqual(after,before)
        self.assertEqual(store.read_bytes(),stored)
        self.assertEqual(self.output.read_bytes(),html)

    def test_text_preserves_active_and_other_agent_link_exclusions(self):
        self.nm_db(completed=False)
        for sid in ['native-review','other-agent','main']:
            self.write('pi',self.pi(sid,cwd=str(self.home)),sid+'.jsonl')
        with sqlite3.connect(self.nm) as db:
            db.execute('INSERT INTO run_agent_sessions VALUES (?,?,?)',('run1','codex','other-agent'))
        self.cli('refresh','--now',str(self.now))
        report=self.rendered_report()
        self.assertEqual(report['excluded']['native_pipeline'],2)
        before=self.cli('text').stdout
        self.assertIn('main chat: 30.00% (1)',before)
        self.assertNotIn('native-revie',before)
        self.assertNotIn('other-agent',before)
        with sqlite3.connect(self.nm) as db:
            db.execute('UPDATE agent_invocations SET completed_at=?',(self.now-100,))
        self.cli('refresh','--now',str(self.now))
        report=self.rendered_report()
        self.assertEqual(report['excluded']['native_pipeline'],2)
        window=next(w for w in report['windows'] if w['provider']=='claude')
        fact=next(f for f in report['facts'] if f['session']=='main')
        result=self.cli('text').stdout
        self.assertIn(f"main chat: {fact['priced']*window['allocation_rate']:.2f}% (1)",result)
        self.assertNotIn('other-agent',result)
        # Reading the saved summary needs neither the store nor a usable live ledger.
        expected=result
        with sqlite3.connect(self.nm) as db:
            db.execute('DROP TABLE run_agent_sessions')
        (self.home/'data/usage-report/usage.sqlite').unlink()
        self.assertEqual(self.cli('text').stdout,expected)
        self.nm.unlink()
        self.assertEqual(self.cli('text').stdout,expected)

    def test_text_is_readonly_and_does_not_import_sample_or_render(self):
        self.nm_db()
        self.write('pi',self.pi())
        self.cli('refresh','--now',str(self.now))
        store=self.home/'data/usage-report/usage.sqlite'
        before=store.read_bytes()
        mode=store.stat().st_mode
        html=self.output.read_bytes()
        self.write('pi',self.pi('not-imported'),'new.jsonl')
        self.quota_file.write_text('not JSON')
        result=self.cli('text','--now',str(self.now)).stdout
        self.assertNotIn('not-imported',result)
        self.assertIn('Claude: 30.00% used',result)
        self.assertEqual(store.read_bytes(),before)
        self.assertEqual(store.stat().st_mode,mode)
        self.assertEqual(self.output.read_bytes(),html)
        summary=self.output.parent/'summary.txt'
        self.assertEqual(summary.stat().st_mode & 0o777,0o600)
        self.assertEqual(result,summary.read_text())
        self.assertEqual(self.cli('text','--now',str(self.now+86400)).stdout,result)

    def test_text_partial_unknown_fallback_and_top_ten(self):
        for i in range(12):
            rows=self.pi('session-'+str(i),cwd=str(self.home))
            rows[-1]['message']['usage']['input']=100+i
            self.write('pi',rows,str(i)+'.jsonl')
        mixed=self.pi('session-11',model='unsupported-model',cwd=str(self.home))
        mixed[-1]['id']='unknown-entry';mixed[-1]['message']['responseId']='unknown-response'
        self.write('pi',mixed,'mixed.jsonl')
        unknown=self.pi('only-unknown',model='unsupported-model')
        unknown[-1]['message']['usage']['input']=400
        self.write('pi',unknown,'unknown.jsonl')
        partial=self.pi('partial')
        partial[-1]['message']['usage'].update(input=None,totalTokens=900)
        self.write('pi',partial,'partial.jsonl')
        old=self.pi('outside-window',ts=self.now-2*86400)
        old[-1]['message']['usage']['input']=2000
        self.write('pi',old,'old.jsonl')
        self.cli('refresh','--now',str(self.now))
        result=self.cli('text','--now',str(self.now)).stdout
        self.assertIn('main chat: 30.00% * (12)',result)
        self.assertNotIn('outside-wind',result)
        top=result.split('Task / session\n',1)[1].split('\n\n',1)[0].splitlines()
        self.assertEqual(len(top),10)
        self.assertIn('900 *',top[0])
        self.assertIn('Unknown',top[0])
        self.assertIn('session-11',top[1])
        self.assertIn('% *',top[1])
        self.assertIn('only-unknown',top[2])
        self.assertIn('Unknown',top[2])
        tokens=[int(line.split()[0].replace(',','')) for line in top]
        self.assertEqual(tokens,sorted(tokens,reverse=True))
        self.assertIn('Unknown',result)
        self.cli('report','--now',str(self.now+3*3600))
        fallback=self.cli('text').stdout
        self.assertIn('Claude: quota unavailable; last 7 days,',fallback)
        self.assertNotIn('30.00% used',fallback)
        self.assertIn('outside-wind',fallback)

    def test_text_missing_summary_and_empty_report(self):
        with self.assertRaises(subprocess.CalledProcessError) as error:
            self.cli('text')
        self.assertIn('run fm-usage-report.sh refresh first',error.exception.stderr)
        self.assertFalse((self.home/'data').exists())
        self.cli('import')
        with self.assertRaises(subprocess.CalledProcessError):
            self.cli('text')
        self.cli('report')
        result=self.cli('text').stdout
        self.assertIn('No sessions in these windows.',result)
        self.assertEqual(result.count('quota unavailable; last 7 days, 0 tokens'),3)
        # Default paths use the summary next to the default HTML, not --output's directory.
        subprocess.run([str(CLI),'report','--nm-db',str(self.nm)],env=self.env,capture_output=True,check=True)
        default=subprocess.run([str(CLI),'text'],env=self.env,capture_output=True,text=True,check=True)
        self.assertEqual(default.stdout,(self.home/'data/usage-report/summary.txt').read_text())

    def test_launchd_install_uninstall_no_load(self):
        directory=self.root/'LaunchAgents'
        self.env['FM_PROJECTS_OVERRIDE']=str(self.root/'registered-projects')
        task_data=self.root/'task-records'
        self.cli('install','--launch-agents',str(directory),'--task-data-root',str(task_data))
        path=next(directory.glob('*.plist'))
        definition=plistlib.loads(path.read_bytes())
        self.assertEqual(definition['StartInterval'],3600)
        self.assertEqual(definition['ProgramArguments'][:2],[str(CLI),'refresh'])
        pi_option=definition['ProgramArguments'].index('--pi-root')
        self.assertEqual(definition['ProgramArguments'][pi_option+1],str(self.roots['pi'].resolve()))
        self.assertIn('--nm-db',definition['ProgramArguments'])
        self.assertEqual(definition['EnvironmentVariables']['FM_HOME'],str(self.home.resolve()))
        self.assertEqual(definition['EnvironmentVariables']['FM_PROJECTS_OVERRIDE'],str((self.root/'registered-projects').resolve()))
        task_option=definition['ProgramArguments'].index('--task-data-root')
        self.assertEqual(definition['ProgramArguments'][task_option+1],str(task_data.resolve()))
        self.assertNotIn('SECRET',str(definition))
        self.cli('uninstall','--launch-agents',str(directory))
        self.assertFalse(path.exists())


if __name__=='__main__':
    unittest.main()
