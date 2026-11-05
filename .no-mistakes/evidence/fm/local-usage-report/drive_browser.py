import json,os,subprocess
from pathlib import Path
E=Path('~/.no-mistakes/evidence/01M6MEX9WY04H2GWMWE52JER8G')
env=dict(os.environ,HOME=str(Path('.test-usage/browser-home').resolve()),CHROME_DEVTOOLS_AXI_SESSION='usage-report-gate',CHROME_DEVTOOLS_AXI_USER_DATA_DIR=str(Path('.test-usage/chrome-profile').resolve()))
log=[]
def run(*args):
 r=subprocess.run(['chrome-devtools-axi',*args],env=env,text=True,capture_output=True,timeout=45)
 log.append('$ chrome-devtools-axi '+' '.join(args)+'\n'+r.stdout+r.stderr)
 (E/'browser-transcript.txt').write_text('\n'.join(log))
 if r.returncode: raise RuntimeError(r.stdout+r.stderr)
 return r.stdout

def check(js):
 out=run('eval','() => { '+js+'; return {verification:"passed",title:document.title,hash:location.hash,text:document.querySelector("main").innerText}; }')
 result=json.loads(out.splitlines()[0].removeprefix('result: '))
 assert json.loads(result)['verification']=='passed',out

def click(js):
 run('eval','() => { '+js+'.click(); return "clicked"; }')
 run('wait','100')

run('open','file://'+str(E/'synthetic-report.html'))
run('resize','1440','1100')
check('''if(document.querySelectorAll('.card').length!==3) throw Error('provider cards');
const cards=[...document.querySelectorAll('.card')];
if(!cards[0].innerText.includes('30.00% used')||!cards[0].innerText.includes('70.00% left')||!cards[0].innerText.includes('Seeded')) throw Error('quota balance');
if(!cards[2].innerText.includes('100.00%')||!cards[2].innerText.includes('not quota')) throw Error('Grok fallback');
if(window.INJECTED) throw Error('script injection');
if(document.querySelector('select')) throw Error('unexpected extra filter');
if([...document.querySelectorAll('#sessions tbody tr')].some(r=>r.innerText.includes('outside-window'))) throw Error('old usage included');''')
run('screenshot',str(E/'overview.png'),'--full-page')
# User selects a role from a provider card; sessions list must be restricted across providers.
click("[...document.querySelectorAll('.card a')].find(a=>a.textContent==='main chat')")
check('''const rows=[...document.querySelectorAll('#sessions tbody tr')]; if(document.querySelector('h1').textContent!=='All sessions'||rows.length!==2||!rows.every(r=>r.children[4].textContent==='main chat')) throw Error('role navigation');''')
run('screenshot',str(E/'role-sessions.png'),'--full-page')
click("[...document.querySelectorAll('a')].find(a=>a.textContent==='Overview')")
# Overview Tokens header is a second all-sessions entry and must preserve descending rank.
click("document.querySelector('#sessions thead th:nth-child(2) a')")
check('''const rows=[...document.querySelectorAll('#sessions tbody tr')];
const values=rows.map(r=>Number(r.children[1].textContent.replace(/[^0-9]/g,'')));
if(rows.length!==9 || values[0]!==180110 || !values.every((v,i)=>!i||values[i-1]>=v)) throw Error('default rank or all-session count');
if(rows.some(r=>r.innerText.includes('outside-window'))) throw Error('current window boundary');''')
run('screenshot',str(E/'sessions.png'),'--full-page')
click("document.querySelector('#sessions thead th:nth-child(2) a')")
check('''const values=[...document.querySelectorAll('#sessions tbody tr')].map(r=>Number(r.children[1].textContent.replace(/[^0-9]/g,''))); if(values[0]!==330||!values.every((v,i)=>!i||values[i-1]<=v)) throw Error('ascending tokens');''')
click("document.querySelector('#sessions thead th:nth-child(3) a')")
check('''const rows=[...document.querySelectorAll('#sessions tbody tr')];const vals=rows.map(r=>parseFloat(r.children[2].textContent)); if(!rows[0].innerText.includes('demo-worker') || vals[0]!==29.24 || !vals.filter(Number.isFinite).every((v,i,a)=>!i||a[i-1]>=v)) throw Error('quota descending');''')
click("document.querySelector('#sessions thead th:nth-child(3) a')")
check('''const vals=[...document.querySelectorAll('#sessions tbody tr')].map(r=>parseFloat(r.children[2].textContent)).filter(Number.isFinite); if(!vals.every((v,i)=>!i||vals[i-1]<=v)) throw Error('quota ascending');''')
# Entire row (not its link) opens detail.
click("[...document.querySelectorAll('tr.session-row')].find(r=>r.innerText.includes('demo-worker'))")
check('''const text=document.querySelector('main').innerText;
for(const value of ['Session usage','Codex / gpt-6.1-sol / high','worker','launch','65,000','32,500','10','100','29.24%','Low confidence','demo-worker']) if(!text.includes(value)) throw Error('missing detail '+value);
const links=[...document.querySelectorAll('a[href^="file://"]')];if(links.length!==2||!links.some(a=>a.textContent.includes('task record'))) throw Error('local links');''')
run('screenshot',str(E/'worker-detail.png'),'--full-page')
# Open generated source locator in browser, not just inspect its href.
source=run('eval',"() => document.querySelector('a[href^=\"file://\"]').href")
click("document.querySelector('a[href^=\"file://\"]')")
run('snapshot')
# Browser renders the real JSONL fixture file.
out=run('eval',"() => ({body:document.body.innerText})")
assert 'worker-demo' in out and 'response-worker-demo' in out,out
run('back')
run('wait','100')
# Task-record link opens the actual synthetic brief.
click("[...document.querySelectorAll('a')].find(a=>a.textContent==='Open task record')")
out=run('eval',"() => document.body.innerText")
assert 'Synthetic task record' in out,out
run('back');run('wait','100')
click("[...document.querySelectorAll('a')].find(a=>a.textContent==='All sessions')")
# Review detail uses the no-mistakes ledger as source and provides the review record.
click("[...document.querySelectorAll('tr.session-row')].find(r=>r.children[4].textContent==='reviewer')")
check('''const text=document.querySelector('main').innerText; if(!text.includes('reviewer')||!text.includes('No-mistakes invocation purpose: review')) throw Error('review evidence'); const review=[...document.querySelectorAll('a')].find(a=>a.textContent==='Open review run'); if(!review||!review.href.startsWith('file://')||!review.href.endsWith('/logs/run1')) throw Error('review link');''')
run('screenshot',str(E/'review-detail.png'),'--full-page')
click("[...document.querySelectorAll('a')].find(a=>a.textContent==='Open review run')")
out=run('eval',"() => document.body.innerText")
assert 'Synthetic review run' in out,out
run('back');run('wait','100')
click("[...document.querySelectorAll('a')].find(a=>a.textContent==='Overview')")
click("[...document.querySelectorAll('a')].find(a=>a.textContent==='View all sessions')")
# Malicious session identifier remains literal text on detail too.
click("[...document.querySelectorAll('tr.session-row')].find(r=>r.innerText.includes('window.INJECTED'))")
check('''if(window.INJECTED||!document.querySelector('h1').textContent.includes('Session usage')||!document.querySelector('main').innerText.includes('</script><script>window.INJECTED=1</script>')) throw Error('inert detail');''')
click("[...document.querySelectorAll('a')].find(a=>a.textContent==='Overview')")
run('emulate','--viewport','390x844x1')
check('''if(document.documentElement.scrollWidth>innerWidth+1) throw Error('mobile page overflow'); if(document.querySelector('.card').getBoundingClientRect().width>innerWidth) throw Error('mobile card');''')
run('screenshot',str(E/'mobile.png'),'--full-page')
# Keyboard row activation remains usable at narrow size.
click("[...document.querySelectorAll('a')].find(a=>a.textContent==='View all sessions')")
run('eval',"() => { document.querySelector('tr.session-row').focus(); return document.activeElement.getAttribute('aria-label'); }")
run('press','Enter')
check("if(document.querySelector('h1').textContent!=='Session usage') throw Error('keyboard activation');")
run('screenshot',str(E/'mobile-detail.png'),'--full-page')
run('console')
print('Browser navigation, 9-session window, both sort directions, detail/source/task links, inert adversarial session and narrow-screen keyboard flow verified.')
