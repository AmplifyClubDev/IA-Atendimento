// Run with PGLITE_MODULE pointing to the official installed PGlite dist/index.js.
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const { PGlite } = await import(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const here = path.dirname(fileURLToPath(import.meta.url));
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
const db = new PGlite();
await db.exec("create schema interno; create role service_role bypassrls; create role anon; create role authenticated; grant usage on schema interno to service_role;");
const columns=JSON.parse(fs.readFileSync(path.join(here,'origin_labels_schema_fixture.json')));
for (const table of ['creators','atendimentos','agenciamentos','eventos']) {
 const defs=columns.filter(c=>c.table_name===table).map(c=>{
  const type=c.udt_name==='_text'?'text[]':c.udt_name;
  if (c.column_name==='id') return `id ${type} ${type==='int8'?'generated always as identity':''} primary key`;
  return `${c.column_name} ${type}`+(c.column_default?' default '+c.column_default.replace('extensions.gen_random_uuid()', 'gen_random_uuid()'):'');
 });
 await db.exec(`create table interno.${table} (${defs.join(',')}); grant all on interno.${table} to service_role;`);
}
await db.exec('grant usage,select on all sequences in schema interno to service_role');
const root=path.resolve(here,'..')+'/';
const baseline=fs.readFileSync(root+'registrar_contato_v5_before.sql','utf8');
const migration=fs.readFileSync(root+'20261112_origin_and_chatwoot_labels.sql','utf8');
await db.exec(baseline);
const baselineHash=async()=> (await db.query("select md5(replace(pg_get_functiondef('public.registrar_contato_v5(jsonb)'::regprocedure), E'\\r\\n', E'\\n')) hash")).rows[0].hash;
assert.equal(await baselineHash(),'87fa6a359f17bc04880cc81fe031065d');
// A legitimate intervening function edit must abort the whole migration.
await db.exec(baseline.replace('declare c interno.creators%rowtype;', 'declare /* concurrent change */ c interno.creators%rowtype;'));
const changedHash=await baselineHash();
await assert.rejects(()=>db.exec(migration), /registrar_contato_v5_baseline_changed/);
await db.exec('rollback');
assert.equal(await baselineHash(), changedHash);
assert.equal((await db.query("select to_regclass('interno.chatwoot_etiquetas_historico') t, to_regprocedure('public.registrar_etiquetas_chatwoot_v5(jsonb)') f")).rows[0].t,null);
assert.equal((await db.query("select to_regprocedure('public.registrar_etiquetas_chatwoot_v5(jsonb)') f")).rows[0].f,null);
console.log('PASS changed baseline aborts atomically without function/table/RPC changes');
await db.exec(baseline);
await db.exec(migration);
console.log('migration compiled');
const creator='11111111-1111-4111-8111-111111111111';
const attendance='22222222-2222-4222-8222-222222222222';
await db.exec(`insert into interno.creators(id) values('${creator}'); insert into interno.atendimentos(id,creator_id,instancia,account_id,contact_id,conversation_id,revisao,primeira_mensagem_em) values('${attendance}','${creator}','test','1','2','3',1,now()-interval '1 hour')`);
await db.exec('set role service_role');
const signature=labels=>createHash('sha256').update(JSON.stringify(labels).replaceAll(',', ', ')).digest('hex');
const input=(revision=1,labels=['convite'])=>({instancia:'test',account_id:'1',contact_id:'2',conversation_id:'3',creator_id:creator,atendimento_id:attendance,revision,labels,observed_at:new Date().toISOString(),signature:signature(labels)});
const call=async(p)=> (await db.query('select public.registrar_etiquetas_chatwoot_v5($1::jsonb) result',[JSON.stringify(p)])).rows[0].result;
let passed=0; async function test(name, fn) {await fn();passed++;console.log('PASS '+name);}
await test('record',async()=>assert.equal((await call(input())).status,'recorded'));
await test('replay with renewed read time',async()=>assert.equal((await call(input())).status,'replayed'));
await test('accented two labels canonical signature',async()=>assert.equal((await call(input(2,['encerrado','validação']))).status,'recorded'));
await test('same revision observation regression denied',async()=>await assert.rejects(()=>call({...input(2,['cadastro']),observed_at:new Date(Date.now()-1000).toISOString()}),/labels_clock_invalid/));
await test('history retained',async()=>assert.equal((await db.query('select count(*)::int n from interno.chatwoot_etiquetas_historico')).rows[0].n,2));
await test('stale unknown revision rejected',async()=>await assert.rejects(()=>call(input(1,['conhecer'])),/labels_stale_revision/));
await test('exact old replay allowed without mutation',async()=>assert.equal((await call(input())).status,'replayed'));
await test('wrong contact denied',async()=>await assert.rejects(()=>call({...input(3),contact_id:'99'}),/labels_identity_mismatch/));
await test('unknown attendance denied',async()=>await assert.rejects(()=>call({...input(3),atendimento_id:'33333333-3333-4333-8333-333333333333'}),/labels_identity_mismatch/));
await test('nonowned label denied',async()=>await assert.rejects(()=>call(input(3,['private-team'])),/labels_values_invalid/));
await test('multiple stages denied',async()=>await assert.rejects(()=>call(input(3,['cadastro','convite'])),/labels_canonical_invalid/));
await test('unsorted labels denied',async()=>await assert.rejects(()=>call(input(3,['validação','encerrado'])),/labels_canonical_invalid/));
await test('signature mismatch denied',async()=>await assert.rejects(()=>call({...input(3),signature:'a'.repeat(64)}),/labels_signature_invalid/));
await test('future timestamp denied',async()=>await assert.rejects(()=>call({...input(3),observed_at:'2099-01-01T00:00:00Z'}),/labels_clock_invalid/));
await test('prejourney timestamp denied',async()=>await assert.rejects(()=>call({...input(3),observed_at:'2020-01-01T00:00:00Z'}),/labels_clock_invalid/));
await db.exec('reset role');
await test('anon no execute',async()=>assert.equal((await db.query("select has_function_privilege('anon','public.registrar_etiquetas_chatwoot_v5(jsonb)','EXECUTE') b")).rows[0].b,false));
await test('auth no table read',async()=>assert.equal((await db.query("select has_table_privilege('authenticated','interno.chatwoot_etiquetas_historico','SELECT') b")).rows[0].b,false));
await test('RLS enabled',async()=>assert.equal((await db.query("select relrowsecurity b from pg_class where oid='interno.chatwoot_etiquetas_historico'::regclass")).rows[0].b,true));
await db.exec('set role service_role');
const contact={instancia:'test',account_id:'1',contact_id:'2',conversation_id:'3',message_id:'10',event_id:'chatwoot:1:10',creator_id:creator,atendimento_id:attendance,revision:3,etapa:'tiktok',situacao:'aberto',observado_em:new Date().toISOString(),qualificacao:{origem_declarada:'outro',origem_canal_declarado:'instagram'}};
// Bind creator the same way as the production identity resolver.
await db.exec(`update interno.creators set origem_instancia='test',origem_account_id='1',origem_contact_id='2' where id='${creator}'`);
const register=async(p)=>(await db.query('select public.registrar_contato_v5($1::jsonb) result',[JSON.stringify(p)])).rows[0].result;
await test('organic channel accepted and persisted',async()=>{
 assert.equal((await register(contact)).revision,3);
 assert.equal((await db.query(`select qualificacao->>'origem_canal_declarado' channel from interno.atendimentos where id='${attendance}'`)).rows[0].channel,'instagram');
});
await test('invalid organic channel denied',async()=>await assert.rejects(()=>register({...contact,revision:4,qualificacao:{origem_canal_declarado:'invented'}}),/contato_qualification_invalid/));
await test('prefilled ad provenance accepted',async()=>{
 const p={...contact,revision:4,qualificacao:{origem_declarada:'anuncio'},origem:{at:new Date().toISOString(),source:'ad_prefilled_message',reference:'chatwoot:1:10',value:'anuncio'}};
 assert.equal((await register(p)).revision,4);
 assert.equal((await db.query(`select origem->>'source' source from interno.atendimentos where id='${attendance}'`)).rows[0].source,'ad_prefilled_message');
});
await test('prefilled cannot assert referral',async()=>await assert.rejects(()=>register({...contact,revision:5,origem:{at:new Date().toISOString(),source:'ad_prefilled_message',reference:'chatwoot:1:10',value:'indicacao'}}),/contato_origin_invalid/));
await test('legacy boolean validation unchanged',async()=>await assert.rejects(()=>register({...contact,revision:5,qualificacao:{shop_ativo_declarado:'yes'}}),/contato_qualification_invalid/));
await db.exec('reset role');
await test('retention deletion cannot be blocked by label snapshots',async()=>{
 await db.exec(`delete from interno.atendimentos where id='${attendance}'`);
 assert.equal((await db.query('select count(*)::int n from interno.chatwoot_etiquetas_historico')).rows[0].n,0);
});
console.log(`${passed} passed`);
await db.close();
