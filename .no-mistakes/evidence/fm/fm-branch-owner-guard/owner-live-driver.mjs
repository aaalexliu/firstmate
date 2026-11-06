import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {spawnSync} from 'node:child_process';
import {existsSync,readFileSync,writeFileSync,unlinkSync,mkdirSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
const root=process.cwd(), lab=`${root}/.owner-live-lab`, home=`${lab}/home`, state=`${home}/state`, agent=`${lab}/agent`;
const sdk=await import(pathToFileURL(`${process.env.PI_PACKAGE_DIR}/dist/index.js`));
const plugin=(await import(pathToFileURL(`${lab}/repo/.pi/extensions/fm-branch-supervision.ts`))).default;
const {createBranchDispatchOffer}=await import(pathToFileURL(`${lab}/repo/.pi/extensions/lib/fm-branch-dispatch.ts`));
const ownerFile=`${state}/.branch-eligible-owner`, rowsFile=`${state}/.branch-eligible-rows`, leaseFile=`${state}/.lease-task-active`;
const owner=()=>readFileSync(ownerFile,'utf8');
const log=(event,data={})=>console.log(JSON.stringify({event,...data}));
let bus,session,requests=0,reports=0,currentCase='',grantAtRequest,assertLease=false,serverError;
async function makeSession(){
 const settings=sdk.SettingsManager.create(home,agent);
 const loader=new sdk.DefaultResourceLoader({cwd:home,agentDir:agent,settingsManager:settings,extensionFactories:[plugin,pi=>{bus=pi.events;}],noSkills:true,noPromptTemplates:true,noThemes:true,noContextFiles:true});
 await loader.reload(); assert.deepEqual(loader.getExtensions().errors,[]);
 const runtime=await sdk.ModelRuntime.create({authPath:`${agent}/auth.json`,modelsPath:`${agent}/models.json`});
 const registry=new sdk.ModelRegistry(runtime);await registry.refresh();
 const model=registry.find('owner-lab','local-model'); assert.ok(model);
 const created=await sdk.createAgentSession({cwd:home,agentDir:agent,settingsManager:settings,resourceLoader:loader,modelRuntime:runtime,model,noTools:'builtin',sessionManager:sdk.SessionManager.create(home,`${home}/main-sessions`),sessionStartEvent:{type:'session_start',reason:'startup'}});
 await created.session.bindExtensions({onError:error=>{console.error('EXTENSION_ERROR',error);}});
 return created.session;
}
if(process.env.OWNER_HELPER==='1'){
 session=await makeSession();
 assert.equal(owner(),process.env.EXPECTED_OWNER,'helper startup changed owner');
 assert.equal(session.getToolDefinition('fm_branch_report'),undefined);
 await session.extensionRunner.emit({type:'session_shutdown',reason:'exit'});await session.dispose();
 assert.equal(owner(),process.env.EXPECTED_OWNER,'helper shutdown changed owner');
 log('helper-start-and-exit-preserved-owner',{depth:process.env.PSTACK_SUBAGENT_DEPTH,pid:process.pid});
 process.exit(0);
}
const server=createServer(async(req,res)=>{
 try{
  let raw='';for await(const chunk of req)raw+=chunk;
  const body=JSON.parse(raw);requests++;
  const msgs=body.messages;const last=msgs.at(-1);
  const branch=body.tools?.some(t=>t.function?.name==='fm_branch_report');
  let delta;
  if(branch && last.role!=='tool'){
   assert.ok(existsSync(rowsFile),'branch reached provider without row grant');
   grantAtRequest=readFileSync(rowsFile,'utf8');
   if(assertLease)assert.ok(existsSync(leaseFile),'repair erased active branch lease');
   log('branch-received-wake',{case:currentCase,owner:owner(),grant:grantAtRequest,leasePreserved:existsSync(leaseFile)});
   delta={role:'assistant',tool_calls:[{index:0,id:`report-${requests}`,type:'function',function:{name:'fm_branch_report',arguments:JSON.stringify({task:'owner-probe',verdict:'routine',summary:`local ownership probe ${currentCase}`,silent:true})}}]};
  }else{
   if(branch){
    assert.equal(readFileSync(rowsFile,'utf8'),grantAtRequest,'healthy tool ownership recheck cleared active grant');
    assert.ok(!last.content.includes('Error')&&!last.content.includes('error'),'report tool failed: '+last.content);
    reports++;log('durable-report-tool-result',{case:currentCase,result:last.content,grantPreserved:true});
   }
   delta={role:'assistant',content:'Local ownership probe complete.'};
  }
  const chunk=(d,finish)=>`data: ${JSON.stringify({id:`local-${requests}`,object:'chat.completion.chunk',created:1,model:'local-model',choices:[{index:0,delta:d,finish_reason:finish}]})}\n\n`;
  res.writeHead(200,{'Content-Type':'text/event-stream'});res.end(chunk(delta,null)+chunk({},delta.tool_calls?'tool_calls':'stop')+'data: [DONE]\n\n');
 }catch(error){serverError=error;res.writeHead(500);res.end(String(error));}
});
let seq=0;
async function wake(label){
 currentCase=label;seq++;
 writeFileSync(`${state}/.wake-queue`,`1\t${seq}\tsignal\towner-probe.status\tsignal: owner-probe.status\n`);
 const before=reports;
 const offer=createBranchDispatchOffer('signal: owner-probe.status',[`${home}/projects/owner-probe`],false,true);
 bus.emit('fm-branch-supervision:dispatch',offer);
 assert.ok(offer.accepted,'wake declined '+label);
 await offer.settlement;if(serverError)throw serverError;
 assert.equal(reports,before+1,'wake did not persist report');
 log('wake-settled',{case:label,reports});
}
try{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 writeFileSync(`${agent}/models.json`,JSON.stringify({providers:{'owner-lab':{baseUrl:`http://127.0.0.1:${server.address().port}/v1`,api:'openai-completions',apiKey:'synthetic-local-only',models:[{id:'local-model',name:'Local ownership oracle',contextWindow:128000,maxTokens:512}]}}}));
 writeFileSync(`${state}/.lock`,`${process.pid}\n`);
 mkdirSync(`${home}/projects/owner-probe`,{recursive:true});
 writeFileSync(`${state}/owner-probe.meta`,`project=${home}/projects/owner-probe\nwindow=local-owner-probe\n`);
 session=await makeSession();const primaryOwner=owner();log('primary-activated',{pid:process.pid,owner:primaryOwner});
 await wake('baseline');
 for(const depth of ['1','2']){
  const child=spawnSync(process.execPath,[process.argv[1]],{encoding:'utf8',timeout:60000,env:{...process.env,OWNER_HELPER:'1',PSTACK_SUBAGENT_DEPTH:depth,EXPECTED_OWNER:primaryOwner}});
  log('helper-process',{depth,exit:child.status,stdout:child.stdout,stderr:child.stderr});
  assert.equal(child.status,0,'helper failed');assert.equal(owner(),primaryOwner);
  await wake(`after-helper-depth-${depth}`);
 }
 log('SCENARIO_PASS',{name:'helper exclusion and subsequent real branch delivery'});
 writeFileSync(leaseFile,`branch\t${process.pid}\t123\n`);assertLease=true;
 const dead=spawnSync(process.execPath,['-e','console.log(process.pid)'],{encoding:'utf8'});assert.equal(dead.status,0);
 const withPid=pid=>primaryOwner.split('\n').map((v,i)=>i===1?String(pid):v).join('\n');
 for(const [name,replacement] of [['missing',null],['dead-owner',withPid(dead.stdout.trim())],['foreign-live-owner',withPid(process.ppid)],['stale-generation',primaryOwner.replace(/\n1\n$/,'\nold-generation\n')]]){
  if(replacement===null)unlinkSync(ownerFile);else writeFileSync(ownerFile,replacement);
  await wake(`repair-${name}`);assert.equal(owner(),primaryOwner);assert.ok(existsSync(leaseFile));
 }
 unlinkSync(ownerFile);
 await session.prompt('Local ownership repair boundary check.');
 assert.equal(owner(),primaryOwner);assert.ok(existsSync(leaseFile));
 log('SCENARIO_PASS',{name:'missing/replaced owner recovery without reload, lease cleanup or healthy grant loss'});
 for(const [name,lock] of [['absent',null],['foreign','1\n']]){
  unlinkSync(ownerFile);if(lock===null)unlinkSync(`${state}/.lock`);else writeFileSync(`${state}/.lock`,lock);
  await session.prompt(`Local lost-lock check ${name}.`);assert.ok(!existsSync(ownerFile));
  const offer=createBranchDispatchOffer('signal: owner-probe.status',[`${home}/projects/owner-probe`],false,true);
  bus.emit('fm-branch-supervision:dispatch',offer);assert.equal(offer.accepted,false);
  log('lock-loss-refused',{lock:name,ownerAbsent:true,wakeAccepted:false});
  writeFileSync(`${state}/.lock`,`${process.pid}\n`);await session.prompt('Local regained-lock boundary.');
  assert.equal(owner(),primaryOwner);assert.ok(existsSync(leaseFile));
 }
 await wake('after-lock-restored');
 log('SCENARIO_PASS',{name:'primary cannot reclaim without session lock and resumes when lock restored'});
 await session.extensionRunner.emit({type:'session_shutdown',reason:'exit'});assert.ok(!existsSync(ownerFile));
 log('primary-shutdown',{ownerRemoved:true,reports,requests});
}finally{
 if(session)await session.dispose();
 await new Promise(resolve=>server.close(resolve));
}
