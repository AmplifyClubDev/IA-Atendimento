import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {activateExistingSession,capturedRelationUrl} from './interactive-policy.mjs';

const source=fs.readFileSync(new URL('./server-quente.mjs',import.meta.url),'utf8');
const command=source.slice(source.indexOf('async function interactiveCommand('),source.indexOf("\nprocess.on('message'"));
function harness({proof={ok:true},busy=false,prepare=false,captured=true,commitThrows=false}={}){
 const originalContext={identity:'same-browser'};
 const state={interactiveChanging:false,ocupadoDesde:busy?1:null,filaTamanho:0,preparando:prepare?{}:null,probeReadinessEmVoo:null,
  contexto:originalContext,pagina:{isClosed:()=>false},partnerContext:{relationListUrl:captured?'https://partner.tiktokshop.com/api/v1/affiliate/partner/relation/list?opaque=private':null},
  operatorLoginMode:true,contextoPronto:false,nascidoEm:0,chamadas:7,ultimoErroContexto:{},bloqueioRisco:{},ultimoProbeReadiness:null,
  cacheRelacoes:new Map(),capturedRelationUrl,activateExistingSession,readCalls:0,opened:0,Date,
  abrirContexto:()=>{state.opened++;throw new Error('must not reopen');},
  listRelations:async(page,context,options)=>{state.readCalls++;assert.equal(context,state.partnerContext);assert.deepEqual(JSON.parse(JSON.stringify(options)),{status:'1',pageSize:1,pageLimit:1});if(commitThrows)throw new Error('uncertain read');return proof;}};
 vm.createContext(state);vm.runInContext(command,state);
 return {state,originalContext,run:()=>vm.runInContext("interactiveCommand('activate')",state)};
}
test('actual activation preserves the browser and performs only bounded authenticated JSON read',async()=>{
 const {state,originalContext,run}=harness();await run();
 assert.equal(state.contexto,originalContext);assert.equal(state.opened,0);assert.equal(state.readCalls,1);
 assert.equal(state.operatorLoginMode,false);assert.equal(state.contextoPronto,true);assert.equal(state.interactiveChanging,false);
});
test('actual activation rejects failed/uncertain reads and missing captured origin',async()=>{
 for(const option of [{proof:{ok:false}},{proof:{ok:'true'}},{commitThrows:true},{captured:false},{busy:true},{prepare:true}]){
  const {state,originalContext,run}=harness(option);await assert.rejects(run());
  assert.equal(state.contexto,originalContext);assert.equal(state.operatorLoginMode,true);assert.equal(state.contextoPronto,false);assert.equal(state.opened,0);
 }
});
const supervisor=fs.readFileSync(new URL('./railway-supervisor.mjs',import.meta.url),'utf8');
const change=supervisor.slice(supervisor.indexOf('async function change(next)'),supervisor.indexOf('\nfunction json('));
test('actual supervisor handoff uses IPC without stopping or spawning a second browser',async()=>{
 const calls=[];const app={pid:123};const state={app,changing:false,mode:'login',bridgeHealth:async()=>({queueLength:0,activeMs:null,interactiveChanging:false}),
 appCommand:async command=>calls.push(command),fs:{writeFileSync(){},renameSync(){}},start:()=>{throw new Error('must not spawn');},profileOwners:()=>{throw new Error('must not restart');}};
 vm.createContext(state);vm.runInContext(change,state);await vm.runInContext("change('bridge')",state);
 assert.deepEqual(calls,['activate']);assert.equal(state.app,app);assert.equal(state.mode,'bridge');
});
test('supervisor keeps login mode when IPC rejects authentication',async()=>{
 const state={app:{pid:123},changing:false,mode:'login',bridgeHealth:async()=>({queueLength:0,activeMs:null}),appCommand:async()=>{throw new Error('rejected');}};
 vm.createContext(state);vm.runInContext(change,state);await assert.rejects(vm.runInContext("change('bridge')",state));assert.equal(state.mode,'login');assert.equal(state.changing,false);
});
