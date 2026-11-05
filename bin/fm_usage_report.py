#!/usr/bin/env python3
"""Local accounting only. Run fm-usage-report.sh --help for the public contract."""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import plistlib
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from contextlib import closing

HERE = Path(__file__).resolve().parent
ROLES = ['main chat', 'supervision', 'worker', 'scout', 'reviewer', 'fixer',
         'helper subagents', 'other automation', 'unassigned']
PROVIDERS = ['claude', 'codex', 'grok']
FIELDS = ['fresh', 'read', 'write', 'output']
PARSER_VERSION = 3
PRICES = json.loads((HERE / 'usage-prices.json').read_text())


def stamp(value):
    if isinstance(value, (int, float)):
        return (value / 1000 if value > 1e11 else float(value)) if math.isfinite(value) else None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)).timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


def utc(value):
    return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat() if value is not None else None


def count(value):
    return int(value) if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0 else None


def family(connector):
    return {'anthropic': 'claude', 'pi-claude-cli': 'claude', 'openai': 'codex',
            'openai-codex': 'codex', 'xai': 'grok', 'claude': 'claude', 'codex': 'codex',
            'grok': 'grok'}.get(connector, 'unknown')


def digest(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Store:
    def __init__(self, path, readonly=False):
        self.readonly = readonly
        if readonly:
            self.db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=30)
            self.db.row_factory = sqlite3.Row
            return
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS facts (key TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cursors (path TEXT PRIMARY KEY, identity TEXT, offset INTEGER,
                                               prefix TEXT, state TEXT);
            CREATE TABLE IF NOT EXISTS health (path TEXT, code TEXT, PRIMARY KEY(path, code));
            CREATE TABLE IF NOT EXISTS bindings (key TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS quota (key TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS fits (key TEXT PRIMARY KEY, data TEXT NOT NULL);
        ''')
        os.chmod(path, 0o600)

    def rows(self, table):
        return [json.loads(row[0]) for row in self.db.execute('SELECT data FROM ' + table)]

    def put(self, table, key, row):
        text = json.dumps(row, sort_keys=True)
        self.db.execute('INSERT INTO ' + table + ' VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET data=excluded.data '
                        'WHERE data != excluded.data', (str(key), text))

    def warn(self, path, code):
        self.db.execute('INSERT OR IGNORE INTO health VALUES (?, ?)', (str(path), code))

    def fact(self, key, row, fragments=False):
        if fragments or key.startswith('response:'):
            previous = self.db.execute('SELECT data FROM facts WHERE key=?', (key,)).fetchone()
            if previous:
                old = json.loads(previous[0])
                for field in FIELDS + ['write1h', 'reported']:
                    known = [r[field] for r in (old, row) if r.get(field) is not None]
                    row[field] = max(known) if known else None
                if old['source'] == 'pi' and row['source'] != 'pi':
                    for field in ['source', 'session', 'locator', 'cwd', 'role', 'evidence',
                                  'session_start', 'time', 'start', 'end']:
                        if field in old:
                            row[field] = old[field]
                for field in ['provider', 'connector', 'model', 'effort']:
                    if row.get(field) in [None, '', 'unknown'] and old.get(field) not in [None, '', 'unknown']:
                        row[field] = old[field]
        self.put('facts', key, row)


def base(source, sid, path, ts, cwd='', **kw):
    return dict(source=source, session=sid, locator=str(path), time=ts, start=ts, end=ts,
                cwd=cwd, provider='unknown', connector='', model='unknown', effort=None,
                role='unassigned', evidence='No proven role binding', project=None, task=None,
                run=None, review=None, task_record=None, fresh=None, read=None, write=None,
                write1h=None, output=None, reported=None, grain='response', normalization_version=1, **kw)


def same_path(value, expected):
    try:
        return isinstance(value, str) and Path(value).is_absolute() and Path(value).resolve() == Path(expected).resolve()
    except (OSError, RuntimeError, ValueError, TypeError):
        return False


def task_catalog(data_root, projects_root):
    registered = set()
    registry = data_root / 'projects.md'
    if registry.exists():
        for line in registry.read_text().splitlines():
            match = re.match(r'^- ([A-Za-z0-9._-]+) \[', line)
            if match:
                registered.add(match[1])
    result = {}
    backlog = data_root / 'backlog.md'
    if not backlog.exists():
        return result
    for line in backlog.read_text().splitlines():
        match = re.match(r'^- \[[ x]\] ([A-Za-z0-9._-]+) - ', line)
        if not match:
            continue
        repos = re.findall(r'\(repo: ([A-Za-z0-9._-]+)\)', line)
        kinds = re.findall(r'\(kind: (ship|scout)\)', line)
        project = projects_root / repos[-1] if repos and repos[-1] in registered else None
        task_record = data_root / match[1] / 'brief.md'
        result[match[1]] = dict(
            project=str(project) if project and project.is_dir() else None,
            role={'ship': 'worker', 'scout': 'scout'}.get(kinds[-1] if kinds else None, 'unassigned'),
            task_record=str(task_record if task_record.exists() else backlog))
    return result


def launch_binding(store, row, state, home, state_root, catalog):
    message = row.get('message', {})
    if message.get('role') != 'user' or same_path(state.get('cwd'), home):
        return
    content = message.get('content', '')
    text = content if isinstance(content, str) else '\n'.join(
        block.get('text', '') for block in content if isinstance(block, dict) and block.get('type') == 'text')
    if not text.lstrip('\u2063').startswith('FIRSTMATE_OP: v1 launch-brief:'):
        return
    match = re.search(r'^Your steering inbox is `([^`\n]+)`;', text, re.MULTILINE)
    if not match:
        return
    inbox = Path(match[1])
    if not same_path(str(inbox.parent), state_root) or not inbox.name.endswith('.inbox'):
        return
    task = inbox.name[:-6]
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', task):
        return
    started, launched = state.get('session_start'), stamp(row.get('timestamp'))
    if started is None or launched is None or launched < started:
        return  # A copied parent launch is not a launch of this native session.
    item = {k: v for k, v in catalog.get(task, {}).items() if v is not None and v != 'unassigned'}
    key = digest('pi-launch', state['sid'], task)
    existing = store.db.execute('SELECT data FROM bindings WHERE key=?', (key,)).fetchone()
    if existing:
        item = dict(json.loads(existing[0]), **item)
    binding = dict(key=key, origin='pi-launch', source='pi', session=state['sid'], task=task,
                   cwd=state.get('cwd'), start=started, end=None,
                   role=item.get('role', 'unassigned'), project=item.get('project'),
                   task_record=item.get('task_record'),
                   evidence='Native Pi session contains its typed Firstmate launch contract; task kind and project from backlog')
    store.put('bindings', key, binding)


def pi_row(store, path, row, state, supervision, home, state_root, catalog):
    typ = row.get('type')
    if typ == 'session':
        state.update(sid=row.get('id', str(path)), cwd=row.get('cwd', ''),
                     session_start=stamp(row.get('timestamp')))
        return
    msg = row.get('message', {})
    if typ == 'message' and not supervision:
        launch_binding(store, row, state, home, state_root, catalog)
    if typ == 'message' and msg.get('role') not in ['assistant', 'toolResult']:
        return
    obj = msg if typ == 'message' else row
    if typ not in ['message', 'usage', 'compaction', 'branch_summary'] or not isinstance(obj.get('usage'), dict):
        return
    u = obj['usage']
    sid = state.get('sid', str(path))
    ts = stamp(row.get('timestamp')) or stamp(obj.get('timestamp'))
    fact = base('pi', sid, path, ts, state.get('cwd', ''))
    fact.update(provider=family(obj.get('provider')), connector=obj.get('provider', ''),
                model=obj.get('responseModel') or obj.get('model') or 'unknown',
                effort=obj.get('thinkingLevel'), session_start=state.get('session_start'),
                fresh=count(u.get('input')), read=count(u.get('cacheRead')),
                write=count(u.get('cacheWrite')), write1h=count(u.get('cacheWrite1h')),
                output=count(u.get('output')), reported=count(u.get('totalTokens')))
    if supervision:
        fact.update(role='supervision', evidence='Explicit Firstmate supervision session store')
    if msg.get('role') == 'toolResult':
        fact.update(role='helper subagents', evidence='Pi tool-result nested usage; producing model unknown')
    rid = obj.get('responseId')
    key = ('response:' + str(rid)) if rid else digest('pi', row.get('id'), ts, u, fact['model'])
    store.fact(key, fact)


def claude_row(store, path, row, state):
    ts = stamp(row.get('timestamp'))
    if row.get('sessionId'):
        state['sid'] = row['sessionId']
    if ts is not None:
        state['session_start'] = min(ts, state.get('session_start', ts))
    msg = row.get('message', {})
    if msg.get('role') != 'assistant' or not isinstance(msg.get('usage'), dict):
        return
    sid = row.get('sessionId') or state.get('sid', str(path))
    u = msg['usage']
    fact = base('claude', sid, path, ts, row.get('cwd', ''))
    fact.update(provider='claude', connector='claude', model=msg.get('model', 'unknown'),
                effort=row.get('effort'), session_start=state.get('session_start'), fresh=count(u.get('input_tokens')),
                read=count(u.get('cache_read_input_tokens')), write=count(u.get('cache_creation_input_tokens')),
                write1h=count((u.get('cache_creation') or {}).get('ephemeral_1h_input_tokens')),
                output=count(u.get('output_tokens')))
    rid = msg.get('id')
    key = 'response:' + rid if rid else digest('claude', sid, row.get('uuid'), ts)
    store.fact(key, fact, fragments=True)


def codex_row(store, path, row, state):
    # Cumulative deltas own ordinary requests. Only a response explicitly paired
    # with a compaction marker can add usage outside that stream. See ccusage's
    # rust/adapters/codex/src/parser.rs and replay.rs (2026-11-04).
    typ, p = row.get('type'), row.get('payload', {})
    ts = stamp(row.get('timestamp'))
    fields = ['input_tokens', 'cached_input_tokens', 'cache_write_input_tokens', 'output_tokens']
    if typ == 'session_meta':
        source = p.get('source')
        subagent = source.get('subagent') if isinstance(source, dict) else None
        spawn = subagent.get('thread_spawn') if isinstance(subagent, dict) else None
        spawn = spawn if isinstance(spawn, dict) else {}
        state.update(sid=p.get('id') or p.get('session_id') or str(path), cwd=p.get('cwd', ''),
                     connector=p.get('model_provider', ''), session_start=stamp(p.get('timestamp')) or ts,
                     inherited=bool(p.get('forked_from_id') or spawn.get('parent_thread_id')))
    elif typ == 'turn_context':
        state.update(model=p.get('model', 'unknown'), effort=p.get('effort'))
    elif typ == 'compacted' and p.get('compaction_response_id'):
        rid = p['compaction_response_id']
        state.setdefault('compacted', []).append(rid)
        pending = state.setdefault('pending', {}).pop(rid, None)
        if pending and rid not in state.get('accounted', []):
            codex_fact(store, path, pending['context'], pending['usage'], pending['time'],
                       'response:' + rid, 'codex-compaction')
            state.setdefault('accounted', []).append(rid)
    elif typ == 'token_usage_record' and p.get('response_id'):
        rid = p['response_id']
        if rid in state.get('accounted', []):
            return
        context = {k: state.get(k) for k in ['sid', 'cwd', 'connector', 'session_start', 'model', 'effort']}
        if p.get('model'):
            context['model'] = p['model']
        if rid in state.get('compacted', []):
            codex_fact(store, path, context, p.get('usage', {}), ts, 'response:' + rid, 'codex-compaction')
            state.setdefault('accounted', []).append(rid)
        else:
            # Only the latest response can be matched by an intervening snapshot.
            # Keep accounting-only pending fields; never persist the payload.
            state['pending'] = {rid: dict(context=context, usage={k: count((p.get('usage') or {}).get(k, 0)) for k in fields},
                                         thread={k: count((p.get('thread_token_usage') or {}).get(k, 0)) for k in fields}, time=ts)}
            state['latest_response'] = rid
    elif typ == 'event_msg' and p.get('type') == 'token_count':
        info = p.get('info') or {}
        current = info.get('total_token_usage')
        if not isinstance(current, dict):
            store.warn(path, 'Codex snapshot has no cumulative totals; excluded')
            return
        current = {k: count(current.get(k, 0)) for k in fields}
        previous = state.get('totals', {})
        state['totals'] = current
        if any(v is None for v in current.values()):
            store.warn(path, 'Invalid Codex cumulative counters; excluded')
            return
        if state.get('inherited') and ts is not None and state.get('session_start') is not None:
            boundary = max(state.get('replay_last', state['session_start']), state['session_start'])
            if not state.get('own_usage') and ts <= boundary + 1:
                state['replay_last'] = ts
                store.warn(path, 'Codex inherited prefix excluded using fork-time baseline')
                return
            state['own_usage'] = True
        # Falling counters start a new segment with an unknown baseline.
        if any(current.get(k, 0) < (previous.get(k) or 0) for k in fields):
            state['segment'] = state.get('segment', 0) + 1
            store.warn(path, 'Codex cumulative counter reset: baseline excluded')
            return
        delta = {k: current.get(k, 0) - (previous.get(k) or 0) for k in fields}
        if not any(delta.values()):
            return
        rid = state.get('latest_response')
        pending = state.get('pending', {}).get(rid)
        if pending and (pending['usage'] == delta or pending['thread'] == current):
            state['pending'].pop(rid)
            state.setdefault('accounted', []).append(rid)
        codex_fact(store, path, state, delta, ts,
                   digest('codex-delta', state.get('sid'), state.get('segment', 0), current), 'codex-cumulative')


def codex_fact(store, path, state, u, ts, key, source):
    fact = base(source, state.get('sid', str(path)), path, ts, state.get('cwd', ''))
    raw, cached = count(u.get('input_tokens')), count(u.get('cached_input_tokens'))
    # Codex cached reads are an input subset. Cache writes are not subtracted:
    # the installed schema does not establish them as an input subset.
    writes = count(u.get('cache_write_input_tokens', 0))
    fact.update(provider=family(state.get('connector')), connector=state.get('connector', ''),
                model=state.get('model', 'unknown'), effort=state.get('effort'),
                session_start=state.get('session_start'),
                fresh=raw-cached if raw is not None and cached is not None and raw >= cached else None,
                read=cached, write=0 if writes == 0 else None,
                output=count(u.get('output_tokens')), reported=count(u.get('total_tokens')))
    if writes:
        store.warn(path, 'Codex cache-write normalization unknown; total is partial')
    store.fact(key, fact)


def import_file(store, path, source, supervision, home, state_root, catalog):
    stat = path.stat()
    identity = f'{stat.st_dev}:{stat.st_ino}'
    old = store.db.execute('SELECT * FROM cursors WHERE path=?', (str(path),)).fetchone()
    offset, state = 0, {}
    with path.open('rb') as stream:
        if (old and old['identity'] == identity and stat.st_size >= old['offset']
                and json.loads(old['state']).get('parser_version') == PARSER_VERSION):
            prefix = hashlib.sha256(stream.read(min(old['offset'], 4096))).hexdigest()
            if prefix == old['prefix']:
                offset, state = old['offset'], json.loads(old['state'])
        stream.seek(offset)
        while True:
            line = stream.readline()
            if not line or not line.endswith(b'\n'):
                break
            offset = stream.tell()
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError('not object')
                if source == 'pi':
                    pi_row(store, path, row, state, supervision, home, state_root, catalog)
                elif source == 'claude':
                    claude_row(store, path, row, state)
                else:
                    codex_row(store, path, row, state)
            except (ValueError, TypeError, KeyError, AttributeError):
                store.warn(path, 'Malformed or unsupported accounting record skipped')
        stream.seek(0)
        prefix = hashlib.sha256(stream.read(min(offset, 4096))).hexdigest()
    state['parser_version'] = PARSER_VERSION
    store.db.execute('INSERT OR REPLACE INTO cursors VALUES (?, ?, ?, ?, ?)',
                     (str(path), identity, offset, prefix, json.dumps(state)))


def capture_tasks(store, state_root, now):
    live = set()
    for path in sorted(state_root.glob('*.meta')):
        if path.is_symlink():
            continue
        # Only these accounting/join fields leave the task record.
        allowed = {'worktree', 'project', 'kind', 'spawn_gen', 'branch', 'session_id'}
        meta = {k: v for line in path.read_text().splitlines() if '=' in line
                for k, v in [line.split('=', 1)] if k in allowed}
        if meta.get('kind') == 'secondmate':
            continue
        key = digest(path.stem, meta.get('spawn_gen'))
        live.add(key)
        old = store.db.execute('SELECT data FROM bindings WHERE key=?', (key,)).fetchone()
        item = json.loads(old[0]) if old else {}
        match = re.match(r's?(\d{10})(?:\D|$)', meta.get('spawn_gen', ''))
        item.update(key=key, task=path.stem, cwd=meta.get('worktree'), project=meta.get('project'),
                    role='scout' if meta.get('kind') == 'scout' else 'worker',
                    start=item.get('start') or (float(match[1]) if match else now), end=None,
                    session=meta.get('session_id'), branch=meta.get('branch'),
                    task_record=str(path), evidence='Exact task copy and validity-bounded metadata binding')
        store.put('bindings', key, item)
    for item in store.rows('bindings'):
        if (item.get('task') and item.get('origin') != 'pi-launch'
                and item['key'] not in live and item.get('end') is None):
            item['end'] = now
            store.put('bindings', item['key'], item)


def nm_tokens(row):
    resumed, proven = row.get('session_mode') == 'resumed', True
    values = {}
    for k in ['input', 'output', 'cache_read']:
        raw, delta = count(row.get(k + '_tokens')), count(row.get('delta_' + k + '_tokens'))
        proven = proven and delta is not None and delta == raw
        values[k] = delta if delta is not None else (None if resumed else raw)
    write = count(row.get('cache_creation_tokens')) if not resumed or proven else None
    raw, cached = values['input'], values['cache_read']
    # Pi and Claude counters have disjoint input. Codex input includes cache.
    agent = row.get('agent')
    fresh = raw
    if agent == 'codex':
        fresh = raw-cached if raw is not None and cached is not None and raw >= cached else None
    elif agent not in ['pi', 'claude']:
        fresh = None
    return fresh, cached, write, values['output']


def nm_context(db):
    runs = {r['id']: dict(r) for r in db.execute(
        'SELECT id, repo_id, branch, worktree_dir, created_at, updated_at FROM runs')}
    links = [dict(r) for r in db.execute('SELECT run_id, agent, session_id FROM run_agent_sessions')]
    return runs, links


def import_nm(store, path):
    if not path.exists():
        store.warn(path, 'No-mistakes ledger absent')
        return [], []
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        runs, links = nm_context(db)
        repos = {r['id']: r['working_path'] for r in db.execute('SELECT id, working_path FROM repos')}
        logs = {}
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='step_results'").fetchone():
            logs = {(r['run_id'], r['step_name']): r['log_path'] for r in db.execute(
                'SELECT run_id, step_name, log_path FROM step_results WHERE log_path IS NOT NULL')}
        columns = {r[1] for r in db.execute('PRAGMA table_info(agent_invocations)')}
        wanted = ['id', 'run_id', 'step_name', 'purpose', 'agent', 'model', 'model_provider', 'session_key', 'session_mode',
                  'started_at', 'completed_at', 'input_tokens', 'output_tokens', 'cache_read_tokens',
                  'cache_creation_tokens', 'delta_input_tokens', 'delta_output_tokens', 'delta_cache_read_tokens']
        query = ','.join(c if c in columns else 'NULL AS ' + c for c in wanted)
        for record in db.execute('SELECT ' + query + ' FROM agent_invocations'):
            r = dict(record)
            run = runs.get(r['run_id'], {})
            if r.get('completed_at') is None:
                store.warn(path, 'Active invocations appear only after completion')
                continue
            fresh, cached, write, output = nm_tokens(r)
            role = {'review': 'reviewer', 'review-fix': 'fixer', 'test-fix': 'fixer'}.get(r['purpose'], 'other automation')
            native = [l['session_id'] for l in links if l['run_id'] == r['run_id'] and l['agent'] == r['agent']]
            fact = base('no-mistakes', 'nm:' + str(r.get('session_key') or r['id']), path, stamp(r['completed_at']), run.get('worktree_dir', ''))
            fact.update(start=stamp(r['started_at']), end=stamp(r['completed_at']),
                        locator=logs.get((r['run_id'], r.get('step_name'))) or str(path),
                        provider=family(r.get('model_provider') or (r['agent'] if r['agent'] in ['claude', 'codex'] else '')),
                        connector=r.get('model_provider') or '', model=r.get('model') or 'unknown',
                        role=role, evidence='No-mistakes invocation purpose: ' + str(r['purpose']),
                        project=repos.get(run.get('repo_id')), run=str(r['run_id']),
                        review=str(path.parent / 'logs' / str(r['run_id'])),
                        fresh=fresh, read=cached, write=write, output=output, grain='invocation; completion bucket',
                        native_sessions=native, branch=run.get('branch'),
                        session_key=r.get('session_key'))
            store.fact('nm:' + str(r['id']), fact)
        return list(runs.values()), links


def attributed(store, facts, runs, links, home):
    bindings = [b for b in store.rows('bindings') if b.get('task')]
    native_logs = {f['session']: f['locator'] for f in facts if f['source'] != 'no-mistakes'}
    exact_nm = {l['session_id'] for l in links}
    exact_nm.update(sid for f in facts if f['source'] == 'no-mistakes' for sid in f.get('native_sessions', []))
    exact_nm.update(f.get('session_key') for f in facts if f['source'] == 'no-mistakes' and f.get('session_key'))
    result, excluded = [], {'native_pipeline': 0, 'possible_pipeline': 0, 'possible_records': []}
    for f in facts:
        if f['source'] != 'no-mistakes' and f['session'] in exact_nm:
            excluded['native_pipeline'] += 1
            continue
        if f['source'] != 'no-mistakes' and any(
                f['cwd'] and f['cwd'] == r.get('worktree_dir') and f['time'] is not None
                and (stamp(r['created_at']) or 0) <= f['time'] <= (stamp(r['updated_at']) or 0) for r in runs):
            excluded['possible_pipeline'] += 1
            item = dict(session=f['session'], locator=f['locator'], source=f['source'])
            if item not in excluded['possible_records']:
                excluded['possible_records'].append(item)
            continue
        if f['source'] == 'pi' and f['role'] == 'unassigned' and same_path(f['cwd'], home):
            f.update(role='main chat', evidence='Primary Pi session in the Firstmate home cwd; not the supervision store',
                     project=str(home))
        session_bindings = [b for b in bindings if b.get('session') == f['session'] and b.get('source', f['source']) == f['source']]
        bounded = [b for b in bindings if not b.get('session') and f['cwd'] and b.get('cwd') == f['cwd']
                   and f.get('session_start', f['start']) is not None
                   and b['start'] <= f.get('session_start', f['start'])
                   and f['time'] is not None and b['start'] <= f['time'] < (b.get('end') or float('inf'))]
        if f['source'] == 'no-mistakes':
            linked = native_logs.get(f.get('session_key'))
            if not linked:
                candidates = {native_logs[s] for s in f.get('native_sessions', []) if s in native_logs}
                linked = next(iter(candidates)) if len(candidates) == 1 else None
            if linked:
                f['locator'] = linked
            bounded = [b for b in bindings if f.get('project') and b.get('project') == f['project']
                       and b.get('branch') and b['branch'] == f.get('branch') and f['time'] is not None
                       and f['start'] is not None and b['start'] <= f['start']
                       and b['start'] <= f['time'] < (b.get('end') or float('inf'))]
        matches = session_bindings or bounded
        identities = {(b['role'], b.get('task'), b.get('project')) for b in matches}
        if len(identities) == 1:
            b = next((b for b in matches if b.get('origin') == 'pi-launch'), matches[0])
            f.update(project=b.get('project'), task=b.get('task'), task_record=b.get('task_record'))
            if f['role'] == 'unassigned':
                f.update(role=b['role'], evidence=b['evidence'])
        f.pop('session_key', None)
        result.append(f)
    return result, excluded


def price(fact):
    model = fact['model']
    # Only documented date suffixes, never fuzzy aliases or model-family guesses.
    if re.search(r'-\d{8}$', model):
        model = model[:-9]
    card = PRICES['models'].get(model)
    if not card or card['provider'] != fact['provider'] or any(fact[k] is None for k in FIELDS):
        return None
    rates = list(card['rates'])
    if fact['write'] and rates[2] == 0:
        return None
    prompt = sum(fact[k] for k in FIELDS[:3])
    # Invocation totals are not one prompt. Use base rates and disclose that
    # limitation rather than applying a long-context surcharge to an aggregate.
    long = fact['grain'] == 'response' and (
        ('long_at' in card and prompt >= card['long_at']) or
        ('long_above' in card and prompt > card['long_above']))
    if long:
        rates = [r*m for r, m in zip(rates, card['long_multipliers'])]
    cost = sum(fact[k]*r for k, r in zip(FIELDS, rates))
    if fact.get('write1h') is not None and card.get('write_1h'):
        cost += min(fact['write1h'], fact['write']) * (card['write_1h'] - card['rates'][2])
    return cost / 1e6


def quota_rows(payload, now):
    rows = []
    generated = stamp(payload.get('generatedAt')) or now
    for provider in PROVIDERS:
        lanes = [p for p in payload.get('providers', []) if p.get('provider') == provider]
        # Do not combine or persist account identifiers. Multiple lanes require
        # an explicit acquisition choice outside this tool.
        if len(lanes) != 1 or len(lanes[0].get('accountKeys', [])) > 1:
            rows.append(dict(provider=provider, observed=now, generated=generated, status='unavailable: multiple or missing lanes'))
            continue
        p = lanes[0]
        state = p.get('state', {})
        fresh = not state.get('stale', False) and state.get('status') == 'fresh'
        windows = p.get('windows', [])
        if not windows or not fresh:
            rows.append(dict(provider=provider, observed=now, generated=generated, status='unavailable: no fresh quota reading'))
            continue
        source_time = stamp(p.get('refreshedAt')) or stamp(state.get('refreshedAt')) or generated
        for w in windows:
            end = stamp(w.get('resetsAt'))
            start = stamp(w.get('startsAt'))
            if start is None and end is not None:
                duration = {'weekly': 7*86400, 'daily': 86400}.get(w.get('kind'))
                if duration:
                    start = end - duration
            remaining = w.get('percentRemaining')
            valid = isinstance(remaining, (float, int)) and math.isfinite(remaining) and 0 <= remaining <= 100
            rows.append(dict(provider=provider, observed=now, generated=source_time,
                             status='fresh' if valid and start is not None and end is not None else 'unavailable: unknown window bounds or balance',
                             window=w.get('id', 'unknown'), label=w.get('label', 'quota'), kind=w.get('kind'),
                             start=start, end=end, remaining=remaining if valid else None))
    return rows


def sample(store, now, facts):
    # No allow-keychain-prompt or allow-inference flags, no vendor CLI refresh,
    # no TTY/stdin, no raw stdout/stderr on disk or in diagnostics.
    try:
        r = subprocess.run(['quota-axi', '--provider', ','.join(PROVIDERS), '--json', '--no-credential-refresh'],
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=True)
        rows = quota_rows(json.loads(r.stdout), now)
    except (OSError, ValueError, subprocess.SubprocessError):
        rows = [dict(provider=p, observed=now, generated=now, status='unavailable: quota-axi read failed or timed out') for p in PROVIDERS]
    for row in rows:
        hourly = [f for f in facts if f['provider'] == row['provider'] and f['time'] is not None
                  and row['generated'] - 3600 < f['time'] <= row['generated']]
        costs = [price(f) for f in hourly]
        row.update(priced_last_hour=sum(c or 0 for c in costs),
                   unpriced_last_hour=sum(c is None for c in costs), price_version=PRICES['version'])
        store.put('quota', digest(row['provider'], row['generated'], row.get('window'), row.get('end')), row)


def rate_fit(store, facts, snapshots, now):
    week = int(now // (7*86400))
    fits = {}
    for provider in PROVIDERS:
        old = store.db.execute('SELECT data FROM fits WHERE key=?', (f'{provider}:{week}',)).fetchone()
        if old and json.loads(old[0]).get('price_version') == PRICES['version']:
            fits[provider] = json.loads(old[0])
            continue
        pairs = []
        points = sorted([q for q in snapshots if q['provider'] == provider and q['status'] == 'fresh'
                         and q.get('window') in ['seven_day', 'weekly', 'credits']
                         and now - 28*86400 <= q['generated'] <= now], key=lambda q: q['generated'])
        for a, b in zip(points, points[1:]):
            gap = b['generated'] - a['generated']
            if (a['window'] != b['window'] or abs(a['end'] - b['end']) > 5
                    or not 1800 <= gap <= 5400):
                continue
            delta = a['remaining'] - b['remaining']
            interval = [f for f in facts if f['provider'] == provider and f['time'] is not None
                        and a['generated'] < f['time'] <= b['generated']]
            if delta < 0 or not interval or any(f['priced'] is None for f in interval):
                continue
            dollars = sum(f['priced'] for f in interval)
            if dollars > 0:
                pairs.append((dollars, delta))
        seed = PRICES['seed'].get(provider, {}).get('pp_per_dollar')
        measured = len(pairs) >= 3 and sum(p[1] for p in pairs) > 0
        rate = sum(p[1] for p in pairs)/sum(p[0] for p in pairs) if measured else seed
        fit = dict(provider=provider, rate=rate, samples=len(pairs), seeded=not measured and seed is not None,
                   fitted_at=now, price_version=PRICES['version'])
        # Do not freeze the cold-start seed for a week: switch as soon as enough
        # pairs exist, then hold that measured fit until the next weekly refit.
        if measured and not store.readonly:
            store.put('fits', f'{provider}:{week}', fit)
        fits[provider] = fit
    return fits


def report_data(store, facts, excluded, now):
    for fact in facts:
        fact['priced'] = price(fact)
    snapshots = store.rows('quota')
    fits = rate_fit(store, facts, snapshots, now)
    windows = []
    for provider in PROVIDERS:
        pp = [q for q in snapshots if q['provider'] == provider]
        latest = max((q['observed'] for q in pp), default=0)
        candidates = [q for q in pp if q['observed'] == latest and q['status'] == 'fresh'
                      and q.get('window') in ['seven_day', 'weekly', 'credits']
                      and q.get('start') is not None and q['start'] <= now < q['end']
                      and 0 <= now - q['generated'] < 7200]
        preferred = sorted(candidates, key=lambda q: (q.get('window') not in ['seven_day', 'weekly', 'credits'], q.get('window', '')))
        reason = max(pp, key=lambda q: q['observed'])['status'] if pp else 'unavailable: not sampled'
        if reason == 'fresh':
            reason = 'unavailable: old reading, expired window, or unsupported scope'
        window = dict(preferred[0]) if preferred else dict(provider=provider, status=reason, start=now-7*86400, end=now)
        window['available'] = bool(preferred)
        window['fit'] = fits[provider]
        selected = [f for f in facts if f['provider'] == provider and f['time'] is not None and window['start'] <= f['time'] < window['end']]
        priced = sum(f['priced'] or 0 for f in selected)
        window['unpriced'] = sum(f['priced'] is None for f in selected)
        window['priced_usage'] = priced
        window['used'] = 100 - window['remaining'] if preferred else None
        window['scale'] = window['used'] / (priced * fits[provider]['rate']) if preferred and priced and fits[provider]['rate'] else None
        # With no published provider seed, quota can still be allocated by relative
        # API-priced weight; disclose this rather than inventing a measured rate.
        window['allocation_rate'] = window['used'] / priced if preferred and priced else None
        windows.append(window)
    health = [{'source': Path(r[0]).name, 'warning': r[1]} for r in store.db.execute('SELECT path, code FROM health ORDER BY path, code')]
    return dict(generated=now, roles=ROLES, windows=windows, facts=facts, excluded=excluded,
                health=health, prices=PRICES['version'], seeds=PRICES['seed'])


def build_report(store, facts, excluded, output, now):
    payload = report_data(store, facts, excluded, now)
    text = json.dumps(payload, separators=(',', ':'), ensure_ascii=True).replace('<', '\\u003c').replace('&', '\\u0026')
    template = (HERE / 'usage-report.html').read_text()
    atomic(output, re.sub(r'/\*ACCOUNTING_DATA\*/\s*null', lambda _: text, template).encode())
    return payload


def text_report(payload):
    def safe(value):
        return ''.join(c if 32 <= ord(c) < 127 else '?' for c in str(value))

    def percent(value, partial=False):
        return 'Unknown' if value is None else f'{value:.2f}%' + (' *' if partial else '')

    sessions = {}
    windows = {w['provider']: w for w in payload['windows']}
    for fact in payload['facts']:
        window = windows.get(fact['provider'])
        if fact['time'] is None or not (
                window['start'] <= fact['time'] < window['end'] if window else
                fact['time'] >= payload['generated'] - 7*86400):
            continue
        source = 'codex' if fact['source'].startswith('codex') else fact['source']
        key = (source, fact['session'], fact['provider'], fact['role'])
        session = sessions.setdefault(key, dict(provider=fact['provider'], role=fact['role'],
            session=fact['session'], task=None, tokens=0, partial=False, priced=0, unpriced=False))
        values = [fact[k] for k in FIELDS]
        session['tokens'] += (sum(values) if all(v is not None for v in values) else
                              fact['reported'] if fact['reported'] is not None else sum(v or 0 for v in values))
        session['partial'] |= any(v is None for v in values)
        session['priced'] += fact['priced'] or 0
        session['unpriced'] |= fact['priced'] is None
        session['task'] = session['task'] or fact.get('task')
    for session in sessions.values():
        window = windows.get(session['provider'])
        session['quota'] = (session['priced'] * window['allocation_rate'] if window and window['available']
            and window['allocation_rate'] is not None and (not session['unpriced'] or session['priced'] > 0) else None)
        session['partial_quota'] = session['unpriced'] and session['priced'] > 0

    lines = ['Local usage (UTC; quota shares are estimates)']
    for window in payload['windows']:
        provider = window['provider']
        rows = [s for s in sessions.values() if s['provider'] == provider]
        if window['available']:
            end = dt.datetime.fromtimestamp(window['end'], dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
            lines.append(f"{provider.title()}: {percent(window['used'])} used, {percent(window['remaining'])} left; "
                         f"{safe(window['label'])} ends {end}")
            roles = []
            for role in payload['roles']:
                rr = [s for s in rows if s['role'] == role]
                share = sum(s['quota'] or 0 for s in rr)
                if share > 0:
                    partial = any(s['quota'] is None or s['partial_quota'] for s in rr)
                    roles.append(f"{role}: {percent(share, partial)} ({len(rr)})")
            lines.extend('  ' + '; '.join(roles[i:i+2]) for i in range(0, len(roles), 2))
        else:
            lines.append(f"{provider.title()}: quota unavailable; last 7 days, {sum(s['tokens'] for s in rows):,} tokens")
    lines.extend(['Role counts in parentheses are sessions.', '', 'Top 10 sessions (current windows; unavailable providers: last 7 days)',
                  f"{'Tokens':>13} {'Est. quota':>11} {'Provider':<8} {'Role':<16} Task / session"])
    top = sorted(sessions.items(), key=lambda item: (-item[1]['tokens'], item[0]))[:10]
    for _, session in top:
        tokens = f"{session['tokens']:,}" + (' *' if session['partial'] else '')
        share = percent(session['quota'], session['partial_quota'])
        identifier = safe(session['task']) if session['task'] else safe(session['session'])[:12]
        lines.append(f"{tokens:>13} {share:>11} {safe(session['provider']):<8} {safe(session['role']):<16} {identifier}")
    if not top:
        lines.append('No sessions in these windows.')
    lines.extend(['', '* Incomplete token or priced coverage; Unknown = no quota estimate.',
                  'Account-wide allocation, not exact session use; other devices and missing logs can bias it.',
                  'Rates may be seeded or uncalibrated; run refresh first for fresh accounting and quota.'])
    return '\n'.join(lines)


def launch_agent(args, home):
    launch_dir = args.launch_agents.resolve()
    label = 'local.firstmate.usage.' + digest(str(home))[:12]
    path = launch_dir / (label + '.plist')
    if args.command == 'uninstall':
        path.unlink(missing_ok=True)
        print('Removed definition only; no launchctl command executed: ' + str(path))
        return
    cli = shutil.which('quota-axi')
    if not cli:
        raise SystemExit('quota-axi must be on PATH before install')
    env = {'FM_HOME': str(home), 'PATH': os.pathsep.join(dict.fromkeys([str(Path(cli).parent), str(Path(shutil.which('python3')).parent), '/usr/bin', '/bin']))}
    for key in ['FM_DATA_OVERRIDE', 'FM_STATE_OVERRIDE', 'FM_PROJECTS_OVERRIDE', 'PI_CODING_AGENT_DIR', 'CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'NM_HOME']:
        if os.environ.get(key):
            env[key] = str(Path(os.environ[key]).expanduser().resolve())
    arguments = [str(HERE/'fm-usage-report.sh'), 'refresh']
    for option in ['pi_root', 'supervision_root', 'claude_root', 'codex_root', 'nm_db', 'output', 'task_data_root']:
        value = getattr(args, option)
        for path_value in value if isinstance(value, list) else ([value] if value else []):
            arguments.extend(['--' + option.replace('_', '-'), str(path_value.resolve())])
    definition = dict(Label=label, ProgramArguments=arguments,
                      StartInterval=3600, EnvironmentVariables=env, ProcessType='Background')
    atomic(path, plistlib.dumps(definition))
    print('Wrote definition only; no launchctl command executed: ' + str(path))
    print('To load after review: launchctl bootstrap gui/$(id -u) ' + str(path))
    print('To unload before uninstall: launchctl bootout gui/$(id -u)/' + label)


def main():
    parser = argparse.ArgumentParser(description='Import local token accounting and generate private HTML or plain-text reports.',
        epilog='Only accounting fields and source locators are stored. No prompts, responses, credentials, or account IDs. '
        'Incremental JSONL cursors and facts commit together; partial final lines wait. '
        'No-mistakes invocation deltas own proven overlapping native sessions; possible overlaps are excluded and counted. '
        'Unknown token components/prices stay unknown. Fitted rates need three fresh hourly pairs and refit weekly; '
        'quota allocation is an estimate scaled to the selected account-wide window, not proof of local causation. '
        'No server or launchctl action runs. install/uninstall only write/remove the home-specific plist. '
        'Run refresh hourly via launchd after reviewing the printed bootstrap command. '
        'Source overrides replace defaults and support isolated fixtures.', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('command', choices=['import', 'report', 'text', 'sample', 'refresh', 'install', 'uninstall'],
        help='text prints existing accounting only: no import, quota sampling, HTML, or store writes; refresh updates first')
    parser.add_argument('--pi-root', type=Path, action='append', help='Pi JSONL root (repeatable)')
    parser.add_argument('--supervision-root', type=Path, action='append', help='Supervision JSONL root (repeatable)')
    parser.add_argument('--claude-root', type=Path, action='append', help='Claude projects JSONL root')
    parser.add_argument('--codex-root', type=Path, action='append', help='Codex JSONL root')
    parser.add_argument('--nm-db', type=Path, help='Read-only no-mistakes state.sqlite')
    parser.add_argument('--task-data-root', type=Path, help='Firstmate backlog and project registry root (default: FM_HOME/data, independent of report output)')
    parser.add_argument('--output', type=Path, help='Private offline HTML destination')
    parser.add_argument('--now', type=float, help='Fixed Unix time for deterministic accounting replay')
    parser.add_argument('--launch-agents', type=Path, default=Path.home()/'Library/LaunchAgents')
    args = parser.parse_args()
    if args.now is not None and not math.isfinite(args.now):
        parser.error('--now must be a finite Unix timestamp')
    os.umask(0o077)
    home = Path(os.environ['FM_HOME']).resolve()
    data = Path(os.environ.get('FM_DATA_OVERRIDE', home/'data')) / 'usage-report'
    state_root = Path(os.environ.get('FM_STATE_OVERRIDE', home/'state')).resolve()
    task_data_root = args.task_data_root or home/'data'
    projects_root = Path(os.environ.get('FM_PROJECTS_OVERRIDE', home/'projects'))
    if args.command in ['install', 'uninstall']:
        launch_agent(args, home)
        return
    try:
        store = Store(data/'usage.sqlite', readonly=args.command == 'text')
    except sqlite3.OperationalError:
        if args.command == 'text':
            parser.exit(1, 'No readable usage store; run fm-usage-report.sh refresh first.\n')
        raise
    now = args.now if args.now is not None else time.time()
    runs, links = [], []
    with store.db:
        if args.command in ['import', 'refresh']:
            capture_tasks(store, state_root, now)
            catalog = task_catalog(task_data_root, projects_root)
            pi_agent = Path(os.environ.get('PI_CODING_AGENT_DIR', Path.home()/'.pi/agent'))
            roots = [('pi', args.pi_root or [pi_agent/'sessions'], False),
                     ('pi', args.supervision_root or [state_root/'branch-session'], True),
                     ('claude', args.claude_root or [Path(os.environ.get('CLAUDE_CONFIG_DIR', Path.home()/'.claude'))/'projects'], False),
                     ('codex', args.codex_root or [Path(os.environ.get('CODEX_HOME', Path.home()/'.codex'))/'sessions', Path(os.environ.get('CODEX_HOME', Path.home()/'.codex'))/'archived_sessions'], False)]
            for source, dirs, supervision in roots:
                for root in dirs:
                    for path in sorted(root.rglob('*.jsonl')):
                        if not path.is_symlink():
                            import_file(store, path, source, supervision, home, state_root, catalog)
        nm_path = args.nm_db or Path(os.environ.get('NM_HOME', Path.home()/'.no-mistakes'))/'state.sqlite'
        # Refresh closed invocations too: a native log can arrive before its
        # invocation completes; recompute overlap from the ledger every time.
        if args.command in ['import', 'refresh', 'report', 'sample']:
            try:
                runs, links = import_nm(store, nm_path)
            except sqlite3.Error:
                store.warn(nm_path, 'No-mistakes schema unavailable; import incomplete')
        if args.command == 'text':
            # Reconcile overlap metadata without importing invocation accounting.
            stored_facts = store.rows('facts')
            run_ends, run_sessions = {}, {}
            for fact in stored_facts:
                if fact['source'] != 'no-mistakes':
                    continue
                run_id = fact['run']
                run_ends[run_id] = max(run_ends.get(run_id, 0), fact['end'])
                sessions = run_sessions.setdefault(run_id, set())
                sessions.update(fact.get('native_sessions', []))
                if fact.get('session_key'):
                    sessions.add(fact['session_key'])
            try:
                with closing(sqlite3.connect(nm_path.resolve().as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
                    db.row_factory = sqlite3.Row
                    db.execute('BEGIN')
                    run_map, live_links = nm_context(db)
                    runs = [dict(run, updated_at=min(stamp(run['updated_at']) or 0, run_ends[str(run_id)]))
                            for run_id, run in run_map.items() if str(run_id) in run_ends]
                    links = [link for link in live_links
                             if link['session_id'] in run_sessions.get(str(link['run_id']), set())]
            except sqlite3.Error:
                runs, links = [], []
                print('Overlap reconciliation skipped: no readable no-mistakes ledger.')
            facts, excluded = attributed(store, stored_facts, runs, links, home)
            print(text_report(report_data(store, facts, excluded, now)))
        if args.command in ['sample', 'refresh']:
            sampled_facts, _ = attributed(store, store.rows('facts'), runs, links, home)
            sample(store, now, sampled_facts)
        if args.command in ['report', 'refresh']:
            facts, excluded = attributed(store, store.rows('facts'), runs, links, home)
            output = args.output or data/'index.html'
            render_now = now if args.now is not None else time.time()
            payload = build_report(store, facts, excluded, output, render_now)
            print(f'Report: {output} ({len(payload["facts"])} accounting facts; private)')
        elif args.command != 'text':
            print(f'{args.command}: accounting records saved')
    store.db.close()


if __name__ == '__main__':
    main()
