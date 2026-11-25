import {randomBytes} from 'node:crypto';
import {validRole,roleAllows} from './interactive-policy.mjs';
const role=process.env.BRIDGE_ROLE;if(!validRole(role))throw new Error('EXPLICIT_BRIDGE_ROLE_REQUIRED');
import http from 'node:http';import net from 'node:net';import fs from 'node:fs';import {spawn} from 'node:child_process';import {once} from 'node:events';
import {bearerAuthorized,consoleAuthorized,validOrigin,session} from './console-security.mjs';
const consoleToken=process.env.BRIDGE_CONSOLE_TOKEN,bridgeToken=process.env.TIKTOK_INVITE_SERVER_TOKEN;
if(!consoleToken||consoleToken.length<40||!bridgeToken||bridgeToken.length<40||consoleToken===bridgeToken)throw new Error('MISSING_DISTINCT_SECRETS');
if(process.env.RAILWAY_VOLUME_MOUNT_PATH!=='/data'||process.env.TIKTOK_PLAYWRIGHT_PROFILE_DIR!=='/data/partner-profile')throw new Error('PERSISTENT_VOLUME_REQUIRED');
fs.mkdirSync('/data/partner-profile',{recursive:true,mode:0o700});fs.chmodSync('/data/partner-profile',0o700);
const children=[];let app=null,mode='starting',changing=false,closing=false;
// DESKTOP_DIAGNOSTIC_BEGIN
const desktopState={phase:'starting',code:null};
const desktopChildren=new WeakMap();
function desktopError(code){const error=new Error(code);error.code=code;return error;}
function desktopClass(value){
 const text=String(value||'').slice(0,4096).toLowerCase();
 if(/already active for display|server is already active/.test(text))return'display_in_use';
 if(/address already in use|eaddrinuse/.test(text))return'bind_in_use';
 if(/xauthority|authorization required|no protocol specified|magic.cookie|authentication/.test(text))return'display_authorization';
 if(/cannot open display|unable to open display|xopendisplay|connection refused/.test(text))return'display_unavailable';
 if(/shared librar|cannot open shared object|not found|enoent/.test(text))return'dependency_missing';
 if(/permission denied|eacces/.test(text))return'permission_denied';
 return'child_failed';
}
function desktopChildName(command,args){
 if(command==='/usr/bin/Xvfb')return'xvfb';if(command==='/usr/bin/x11vnc')return'x11vnc';
 if(command==='/usr/bin/websockify')return'websockify';return args?.[0]==='server-quente.mjs'?'bridge':'other';
}
function watchDesktopChild(child,name){
 const diagnostic={name,code:null};desktopChildren.set(child,diagnostic);
 child.stderr?.on('data',chunk=>{const code=desktopClass(chunk);if(code!=='child_failed')diagnostic.code=code;});
 child.on('error',error=>{diagnostic.code=desktopClass(error?.code);console.error(JSON.stringify({event:'desktop_child_error',child:name,code:diagnostic.code}));});
 child.on('exit',(exitCode,signal)=>{
  if(closing)return;
  const code=diagnostic.code||'child_exited';
  console.error(JSON.stringify({event:'desktop_child_exit',child:name,code,exitCode:Number.isInteger(exitCode)?exitCode:null,signal:['SIGTERM','SIGKILL','SIGSEGV','SIGABRT','SIGBUS','SIGILL'].includes(signal)?signal:null}));
  if(['xvfb','x11vnc','websockify'].includes(name)&&desktopState.phase==='ready'){desktopState.phase='failed';desktopState.code=code;mode='failed';}
 });
 return child;
}
function desktopExited(child){return Number.isInteger(child?.exitCode)||typeof child?.signalCode==='string';}
function x11Responds(){return new Promise(resolve=>{
 let socket,done=false;const finish=value=>{if(done)return;done=true;socket?.destroy();resolve(value);};
 try{socket=net.connect({path:'/tmp/.X11-unix/X99'});socket.once('connect',()=>socket.write(Buffer.from([108,0,11,0,0,0,0,0,0,0,0,0])));socket.once('data',data=>finish(data[0]===1));socket.once('error',()=>finish(false));socket.setTimeout(500,()=>finish(false));}catch{finish(false);}
});}
async function waitDesktopDisplay(child){for(let i=0;i<50;i++){if(desktopExited(child))throw desktopError(desktopChildren.get(child)?.code||'display_child_exited');if(await x11Responds())return;await new Promise(resolve=>setTimeout(resolve,100));}throw desktopError('display_not_ready');}
async function waitDesktopPort(port,child){for(let i=0;i<100;i++){
 if(desktopExited(child))throw desktopError(desktopChildren.get(child)?.code||'desktop_child_exited');
 if(await new Promise(resolve=>{const socket=net.connect(port,'127.0.0.1');let done=false;const finish=value=>{if(done)return;done=true;socket.destroy();resolve(value);};socket.once('connect',()=>finish(true));socket.once('error',()=>finish(false));socket.setTimeout(300,()=>finish(false));}))return;
 await new Promise(resolve=>setTimeout(resolve,100));
}throw desktopError(desktopChildren.get(child)?.code||'local_port_unavailable');}
// DESKTOP_DIAGNOSTIC_END

function start(command,args,env=process.env,ipc=false){const p=spawn(command,args,{env,stdio:ipc?['ignore','ignore','pipe','ipc']:['ignore','ignore','pipe'],detached:true});p.stderr.on('data',()=>{});p.on('error',()=>console.error('CHILD_START_FAILED'));children.push(p);return watchDesktopChild(p,desktopChildName(command,args));}
async function waitPort(port){for(let i=0;i<100;i++){if(await new Promise(ok=>{let s=net.connect(port,'127.0.0.1');s.on('connect',()=>{s.destroy();ok(true)});s.on('error',()=>ok(false));s.setTimeout(300,()=>{s.destroy();ok(false)});}))return;await new Promise(r=>setTimeout(r,100));}throw new Error('LOCAL_PORT_UNAVAILABLE');}
function profileOwners(){let owners=[];for(let n of fs.readdirSync('/proc')){if(!/^\d+$/.test(n))continue;try{let args=fs.readFileSync('/proc/'+n+'/cmdline','utf8').split('\0');if(args.some((v,i)=>v==='--user-data-dir=/data/partner-profile'||v==='--user-data-dir'&&args[i+1]==='/data/partner-profile'))owners.push(Number(n));}catch{}}return owners;}
async function stopApp(){if(!app)return;let old=app;if(old.exitCode===null&&old.signalCode===null){let stopped=once(old,'exit');old.kill('SIGTERM');let timer;try{await Promise.race([stopped,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('APP_STOP_UNCERTAIN')),20000)})]);}finally{clearTimeout(timer);}}app=null;for(let i=0;i<50&&profileOwners().length;i++)await new Promise(r=>setTimeout(r,100));if(profileOwners().length)throw new Error('PROFILE_OWNER_REMAINS');}
async function bridgeHealth(){return new Promise(resolve=>{let q=http.get('http://127.0.0.1:8788/health',r=>{let text='';r.on('data',b=>{text+=b;if(text.length>200000)q.destroy()});r.on('end',()=>{try{resolve(JSON.parse(text))}catch{resolve(null)}})});q.on('error',()=>resolve(null));q.setTimeout(3000,()=>{q.destroy();resolve(null)});});}
async function appCommand(command){
 if(!app?.connected)throw new Error('APP_IPC_UNAVAILABLE');
 const id=randomBytes(16).toString('hex');
 return await new Promise((resolve,reject)=>{
  const done=()=>{clearTimeout(timer);app.removeListener('message',receive)};
  const receive=m=>{if(m?.id!==id)return;done();if(m.ok===true)resolve(m);else reject(new Error('HUMAN_LOGIN_REQUIRED'));};
  const timer=setTimeout(()=>{done();reject(new Error('ACTIVATION_UNCERTAIN_RECONCILE'));},90000);
  app.on('message',receive);app.send({id,command},e=>{if(e){done();reject(new Error('IPC_SEND_FAILED'));}});
 });
}
async function change(next){
 if(changing||!['login','bridge'].includes(next))throw new Error('MODE_CHANGE_BLOCKED');
 changing=true;
 try{
  if(!app){
   if(profileOwners().length)throw new Error('PROFILE_OWNED');
   app=start(process.execPath,['server-quente.mjs'],{...process.env,TIKTOK_INTERACTIVE_SESSION:'true'},true);
   app.on('exit',()=>{if(!closing){mode='failed';console.error('APP_EXITED_REQUIRES_RECONCILIATION')}});
   await waitPort(8788);mode='login';if(next==='login')return;
  }
  if(next===mode&&next!=='login')return;
  let h=await bridgeHealth();
  if(!h||h.queueLength!==0||h.activeMs!==null||h.interactiveChanging)throw new Error('BRIDGE_NOT_DRAINED');
  if(next==='login'&&typeof h.contextoAberto!=='boolean')throw new Error('CONTEXT_STATE_UNCONFIRMED');
  if(next==='login'&&h.contextoAberto===false&&profileOwners().length)throw new Error('PROFILE_OWNED');
  await appCommand(next==='bridge'?'activate':'login');
  fs.writeFileSync('/data/mode.tmp',next,{mode:0o600});fs.renameSync('/data/mode.tmp','/data/mode');mode=next;
 }finally{changing=false;}
}

function json(res,status,value){res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'});res.end(JSON.stringify(value));}
function proxy(req,res,port,path,bridge=false){const headers={host:'127.0.0.1:'+port};for(let name of ['content-type','content-length','sec-websocket-protocol'])if(req.headers[name])headers[name]=req.headers[name];if(bridge)headers.authorization=req.headers.authorization;let upstream=http.request({hostname:'127.0.0.1',port,path,method:req.method,headers},r=>{res.writeHead(r.statusCode,{...r.headers,'Cache-Control':'no-store','Referrer-Policy':'no-referrer'});r.pipe(res)});upstream.on('error',()=>{if(!res.headersSent)json(res,503,{ok:false,status:'upstream_unavailable'});else res.destroy();});upstream.setTimeout(150000,()=>upstream.destroy());req.pipe(upstream);}
// SESSION_PANEL_BEGIN
// Passive telemetry only: no /ready call, browser command, provider read or cookie mutation.
const SESSION_PANEL_SERVICE = String(process.env.RAILWAY_SERVICE_NAME || process.env.BRIDGE_ROLE || 'TikTok Amplify')
  .replace(/[^A-Za-z0-9À-ÿ _().-]/g, '').slice(0, 80) || 'TikTok Amplify';
const SESSION_PANEL_CODES = new Set(['captcha_required', 'mfa_required', 'human_verification_required',
  'human_login_required', 'login_required', 'session_or_partner_context_invalid', 'partner_probe_rejected',
  'blocked_by_risk_guard', 'timeout', 'browser_missing', 'browser_unavailable', 'unknown']);
function panelCode(value) { return SESSION_PANEL_CODES.has(value) ? value : value ? 'unknown' : null; }
function panelNumber(value) { return Number.isFinite(value) && value >= 0 ? Math.min(Math.trunc(value), 2147483647) : null; }
function panelStamp(value) {
  if (typeof value !== 'string' || value.length > 40) return null;
  const stamp = Date.parse(value);
  return Number.isFinite(stamp) ? new Date(stamp).toISOString() : null;
}
function sessionPanelStatus(value) {
  const health = value && typeof value === 'object' && !Array.isArray(value) ? value : null;
  const effectiveMode = !changing && health?.operatorLoginMode === true ? 'login' : mode;
  const probeAge = panelNumber(health?.probe?.ageMs);
  const lastError = { code: panelCode(health?.lastContextError?.code), at: panelStamp(health?.lastContextError?.at) };
  const blocked = health?.riskGuard?.status === 'blocked';
  const riskCode = blocked ? panelCode(health?.riskGuard?.code) : null;
  const probeCode = panelCode(health?.probe?.errorCode);
  const recentFailure = health?.probe?.status === 'failed' && probeAge !== null && probeAge <= 60000;
  const currentCode = blocked ? riskCode : recentFailure ? probeCode : null;
  const open = health ? health.contextoAberto === true || health.contexto?.aberto === true : null;
  const ready = health ? health.contextoPronto === true || health.contexto?.pronto === true : null;
  const verified = Boolean(health && ready && !blocked && effectiveMode === 'bridge'
    && health.probe?.status === 'ok' && probeAge !== null && probeAge <= 60000
    && health.readiness?.fresh === true && health.readiness?.withinGrace === true);
  let state = 'verification_pending';
  if (changing || effectiveMode === 'starting') state = 'transitioning';
  else if (effectiveMode === 'failed') state = 'unavailable';
  else if (['human_login_required', 'login_required'].includes(currentCode)) state = 'login_required';
  else if (['captcha_required', 'mfa_required', 'human_verification_required'].includes(currentCode)) state = 'human_challenge';
  else if (blocked) state = 'risk_blocked';
  else if (effectiveMode === 'login') state = 'authentication_window';
  else if (!health) state = 'unavailable';
  else if (!open) state = 'context_closed';
  else if (verified) state = 'authenticated';
  else if (currentCode === 'session_or_partner_context_invalid' || currentCode === 'partner_probe_rejected') state = 'session_unconfirmed';
  return { ok: true, service: SESSION_PANEL_SERVICE,
    process: { online: true, mode: effectiveMode, changing: changing === true },
    bridge: { available: Boolean(health) },
    session: { state, authenticated: verified },
    context: { open, ready },
    probe: { status: ['ok', 'failed', 'never'].includes(health?.probe?.status) ? health.probe.status : 'never',
      checkedAt: panelStamp(health?.probe?.checkedAt), ageMs: probeAge, errorCode: probeCode,
      fresh: health?.readiness?.fresh === true, refreshing: health?.readiness?.refreshing === true },
    riskGuard: { status: blocked ? 'blocked' : health ? 'clear' : 'unknown', code: riskCode,
      retryAfterMs: blocked ? panelNumber(health?.riskGuard?.retryAfterMs) : null },
    lastContextError: lastError,
    queue: { length: panelNumber(health?.queue?.length ?? health?.queueLength), activeMs: panelNumber(health?.queue?.activeMs ?? health?.activeMs) } };
}
const SESSION_PANEL_HTML = `<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Amplify · Sessão TikTok</title>
<style>body{font:16px system-ui;margin:0;background:#121724;color:#f4f6fc}header,main{padding:18px 24px}header{display:flex;align-items:center;gap:16px;flex-wrap:wrap}h1{font-size:20px;margin:0}button{padding:11px 16px;border:0;border-radius:8px;cursor:pointer;background:#abd0ff;color:#102034;font:inherit}button:disabled{opacity:.5;cursor:wait}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}.card{padding:15px;border:1px solid #354052;border-radius:10px;background:#192130}.card span{display:block;color:#b8c8db;font-size:13px;margin-bottom:6px}.card strong{font-size:16px}.good{color:#8ce0b4}.warn{color:#ffd68b}.bad{color:#ffaba5}#notice{min-height:24px;line-height:1.5}#detail,#access{font-size:14px;color:#b8c8db;line-height:1.5}#viewer{width:100%;height:65vh;min-height:360px;border:1px solid #354052;border-radius:10px;background:#202020}#empty{padding:22px;border:1px dashed #586275;border-radius:10px;color:#c4d0df}#actions{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}#access-form{padding:18px;border:1px solid #354052;border-radius:10px;margin:16px 0}#access-form label{display:block;margin-bottom:8px}#access-value{padding:11px;border-radius:8px;border:1px solid #586275;background:#101724;color:#f4f6fc;max-width:90%;width:320px;font:inherit}#access-form p{font-size:14px;line-height:1.5;color:#c4d0df}a{color:#abd0ff}</style>
<header><h1>Amplify · TikTok</h1><span id="service">Painel de sessão</span></header><main>
<div class="cards"><div class="card"><span>Serviço</span><strong id="online">Verificando…</strong></div><div class="card"><span>Sessão TikTok</span><strong id="session">Acesso protegido</strong></div><div class="card"><span>Navegador</span><strong id="context">A confirmar</strong></div><div class="card"><span>Última verificação</span><strong id="probe">A confirmar</strong></div><div class="card"><span>Proteção de acesso</span><strong id="risk">A confirmar</strong></div></div>
<p id="notice" role="status" aria-live="polite">Verificando seu acesso ao painel…</p><p id="detail"></p>
<div id="actions"><button id="activate" hidden>Concluí a verificação — ativar</button><button id="login" hidden>Recuperar autenticação</button><button id="refresh">Atualizar estado</button></div>
<p id="access">Este é o endereço fixo deste serviço. O acesso usa a autorização protegida já existente.</p>
<form id="access-form" hidden><label for="access-value">Acesso ao painel</label><input id="access-value" type="password" autocomplete="off" spellcheck="false" minlength="40" maxlength="2048" required aria-describedby="access-help"><button id="open-panel" type="submit">Abrir painel</button><p id="access-help">Copie o acesso <code>BRIDGE_CONSOLE_TOKEN</code> nas variáveis deste serviço no Railway e cole aqui. O campo será limpo ao enviar; o painel não salva esse acesso no navegador. <a href="https://railway.com/dashboard" target="_blank" rel="noopener noreferrer">Abrir Railway</a></p><p id="access-feedback" role="status" aria-live="polite"></p></form>
<p id="empty">A janela remota aparecerá quando houver um navegador disponível. Uma tela sem navegador não confirma que a conta saiu.</p><iframe id="viewer" hidden title="Navegador remoto do serviço TikTok"></iframe>
<script type="module">
const element=id=>document.getElementById(id),viewer=element('viewer'),activate=element('activate'),login=element('login'),accessForm=element('access-form'),accessInput=element('access-value'),openPanel=element('open-panel');
const names={authenticated:'Autenticada',human_challenge:'Verificação humana necessária',login_required:'Login solicitado pelo serviço',authentication_window:'Janela de autenticação',risk_blocked:'Leitura temporariamente bloqueada',context_closed:'Contexto fechado',session_unconfirmed:'Sessão a verificar',verification_pending:'Verificação pendente',transitioning:'Alteração em andamento',unavailable:'Indisponível'};
const reasons={captcha_required:'Desafio de segurança',mfa_required:'Verificação adicional',human_verification_required:'Verificação humana',session_or_partner_context_invalid:'Sessão ou contexto não confirmado',partner_probe_rejected:'Consulta de verificação recusada',browser_missing:'Navegador indisponível',browser_unavailable:'Janela indisponível',timeout:'Tempo de verificação excedido',unknown:'Ocorrência não classificada'};
let busy=false,refreshing=false,authorized=false,accessBusy=false;
function text(id,value){element(id).textContent=value;}
function hideViewer(){viewer.hidden=true;viewer.src='about:blank';element('empty').hidden=false;}
function protectedState(){authorized=false;accessForm.hidden=false;activate.hidden=true;login.hidden=true;hideViewer();text('service','Painel de sessão');text('online','Painel online');text('session','Acesso protegido');element('session').className='';for(const id of ['context','probe','risk'])text(id,'A confirmar');text('notice','Informe o acesso ao painel abaixo para consultar e recuperar a sessão deste serviço.');text('detail','Nenhuma informação privada da sessão é mostrada sem autorização.');}
async function refresh(){
 if(refreshing)return;refreshing=true;
 try{const response=await fetch('/console/status',{cache:'no-store',credentials:'same-origin',redirect:'error'});
  if(response.status===401){protectedState();return;}if(!response.ok)throw Error('status_unavailable');
  const data=await response.json();authorized=true;accessForm.hidden=true;accessInput.value='';text('access-feedback','');text('service',data.service);text('online',data.process.online?'Online':'Indisponível');
  text('session',names[data.session.state]||'A confirmar');element('session').className=data.session.authenticated?'good':['human_challenge','risk_blocked','login_required'].includes(data.session.state)?'warn':'';
  text('context',data.context.open===true?(data.context.ready?'Aberto e preparado':'Aberto'):(data.context.open===false?'Fechado':'A confirmar'));
  text('probe',data.probe.status==='ok'?(data.probe.fresh?'Leitura autenticada recente':'Leitura anterior'):data.probe.status==='failed'?'Não confirmada':'Ainda sem leitura');
  text('risk',data.riskGuard.status==='blocked'?'Aguardando liberação':data.riskGuard.status==='clear'?'Sem bloqueio registrado':'A confirmar');
  const descriptions={authenticated:'A sessão respondeu a uma consulta autenticada recente.',human_challenge:'A conta pode continuar conectada. Conclua a verificação humana na janela remota.',login_required:'O serviço identificou uma solicitação explícita de login.',authentication_window:'A janela está em modo de autenticação. Confira a conta ou o desafio e depois ative a integração.',risk_blocked:'O serviço interrompeu as consultas por segurança. Confira a janela antes de tentar novamente.',context_closed:'O navegador de operação está fechado. Isso não prova que a conta foi desconectada.',session_unconfirmed:'Ainda não há prova atual da sessão. Isso não confirma que a conta foi desconectada.',verification_pending:'Aguarde a próxima verificação do serviço ou confira a janela.',transitioning:'A alteração está em andamento. Aguarde antes de executar outra ação.',unavailable:'O estado do navegador não está disponível. O painel permanece acessível.'};
  text('notice',descriptions[data.session.state]||'Estado a confirmar.');
  const details=[];if(data.probe.checkedAt)details.push('Consulta: '+new Date(data.probe.checkedAt).toLocaleString('pt-BR'));if(data.probe.refreshing)details.push('Nova verificação em andamento');
  if(data.riskGuard.status==='blocked'&&data.riskGuard.retryAfterMs!==null)details.push('Proteção: cerca de '+Math.ceil(data.riskGuard.retryAfterMs/60000)+' min');
  if(data.lastContextError.code){let last='Última ocorrência: '+(reasons[data.lastContextError.code]||'Verificação não confirmada');if(data.lastContextError.at)last+=' em '+new Date(data.lastContextError.at).toLocaleString('pt-BR');details.push(last);}
  text('detail',details.join(' · '));activate.hidden=data.process.mode!=='login';login.hidden=data.process.mode==='login'&&data.context.open===true;activate.disabled=login.disabled=busy||data.process.changing;
  if(data.context.open===true||(data.process.mode==='login'&&data.context.open===null)){if(viewer.hidden){viewer.src='/console/vnc/vnc.html?autoconnect=1&resize=scale&path=console%2Fsocket';viewer.hidden=false;}element('empty').hidden=true;}else hideViewer();
 }catch{text('online','Estado indisponível');text('session','A confirmar');element('session').className='';for(const id of ['context','probe','risk'])text(id,'A confirmar');text('detail','');text('notice','Não foi possível consultar o estado agora. Atualize novamente em instantes.');activate.disabled=login.disabled=true;}finally{refreshing=false;}
}
async function change(path){if(busy||!authorized)return;busy=true;activate.disabled=login.disabled=true;
 let message=null;try{const response=await fetch(path,{method:'POST',credentials:'same-origin',redirect:'error'});if(!response.ok)message='A ação não foi concluída. Nenhuma nova tentativa foi feita; atualize o estado antes de continuar.';}
 catch{message='O resultado da ação não foi confirmado. Atualize o estado antes de tentar novamente.';}
 finally{busy=false;await refresh();if(message&&authorized)text('notice',message);}
}
activate.onclick=()=>change('/console/activate');login.onclick=()=>change('/console/login');element('refresh').onclick=refresh;
accessForm.onsubmit=async event=>{event.preventDefault();if(accessBusy)return;let key=String(accessInput.value||'').trim();accessInput.value='';
 if(key.length<40||key.length>2048||/[\\r\\n]/.test(key)){key=null;text('access-feedback','Copie o acesso completo nas variáveis deste serviço no Railway.');return;}
 accessBusy=true;openPanel.disabled=true;text('access-feedback','Abrindo o painel…');
 try{const response=await fetch('/console/session',{method:'POST',headers:{Authorization:'Bearer '+key},credentials:'same-origin',redirect:'error'});key=null;
  if(!response.ok){text('access-feedback','O acesso não foi aceito. Confira BRIDGE_CONSOLE_TOKEN no serviço correto e tente novamente.');return;}
  await refresh();if(!authorized)text('access-feedback','A autorização ainda não foi confirmada. Atualize o estado antes de tentar novamente.');
 }catch{text('access-feedback','O acesso não foi confirmado. Nenhuma nova tentativa foi feita.');}
 finally{key=null;accessInput.value='';accessBusy=false;openPanel.disabled=false;}
};
const fragment=new URLSearchParams(location.hash.slice(1));let access=fragment.get('access');history.replaceState(null,'','/console/');
if(access){try{await fetch('/console/session',{method:'POST',headers:{Authorization:'Bearer '+access},credentials:'same-origin',redirect:'error'});}catch{}access=null;}
await refresh();setInterval(refresh,10000);
</script></html>`;
// SESSION_PANEL_END
const server=http.createServer(async(req,res)=>{try{
 const url=new URL(req.url,'http://localhost');
 if(req.method==='GET'&&url.pathname==='/health'){const h=await bridgeHealth();return json(res,200,{ok:true,mode,role,persistent_profile:true,precisa_login:h?.precisaLogin===true});}
 if(req.method==='GET'&&['/','/console','/console/'].includes(url.pathname)){res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-src 'self'; connect-src 'self'; frame-ancestors 'none'"});return res.end(SESSION_PANEL_HTML);}
 if(url.pathname==='/console/session'&&req.method==='POST'){if(!validOrigin(req)||!bearerAuthorized(req,consoleToken))return json(res,401,{ok:false});res.setHeader('Set-Cookie','__Host-bridge_console='+session(consoleToken)+'; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=7200');return json(res,200,{ok:true});}
 if(url.pathname.startsWith('/console/')){
  if(!consoleAuthorized(req,consoleToken))return json(res,401,{ok:false});
  if(req.method==='GET'&&url.pathname==='/console/status'){const health=await bridgeHealth();if(!changing&&health?.operatorLoginMode===true)mode='login';return json(res,200,{...sessionPanelStatus(health),infrastructure:{phase:desktopState.phase,code:desktopState.code}});}
  if(req.method==='GET'&&url.pathname==='/console/state'){const health=await bridgeHealth();if(!changing&&health?.operatorLoginMode===true)mode='login';return json(res,200,{mode,changing,role,contextReady:health?.contextoPronto===true});}
  if(req.method==='POST'&&['/console/activate','/console/login'].includes(url.pathname)){if(!validOrigin(req))return json(res,403,{ok:false});if(desktopState.phase!=='ready')return json(res,503,{ok:false,status:'desktop_unavailable'});await change(url.pathname==='/console/activate'?'bridge':'login');return json(res,200,{ok:true,mode});}
  if(req.method==='GET'&&url.pathname.startsWith('/console/vnc/')){let path=decodeURIComponent(url.pathname.slice('/console/vnc'.length));if(path.split('/').some(x=>x==='..'||x==='.')||path.includes('\\'))return json(res,400,{ok:false});return proxy(req,res,6080,path+url.search);}
  return json(res,404,{ok:false});
 }
 if(url.pathname.startsWith('/bridge/')){if(!bearerAuthorized(req,bridgeToken))return json(res,401,{ok:false});if(mode!=='bridge')return json(res,503,{ok:false,status:'login_required'});let path=url.pathname.slice('/bridge'.length);if(!roleAllows(role,req.method,path))return json(res,404,{ok:false});return proxy(req,res,8788,path+url.search,true);}
 json(res,404,{ok:false});
}catch{json(res,409,{ok:false,status:'requires_reconciliation'});}});
server.on('upgrade',(req,socket,head)=>{try{let u=new URL(req.url,'http://localhost');if(u.pathname!=='/console/socket'||!consoleAuthorized(req,consoleToken)||!validOrigin(req)){socket.end('HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n');return;}let upstream=net.connect(6080,'127.0.0.1',()=>{let lines=['GET /websockify HTTP/1.1','Host: 127.0.0.1:6080'];for(let k of ['upgrade','connection','sec-websocket-key','sec-websocket-version','sec-websocket-protocol'])if(req.headers[k])lines.push(k+': '+req.headers[k]);upstream.write(lines.join('\r\n')+'\r\n\r\n');if(head.length)upstream.write(head);socket.pipe(upstream).pipe(socket);});upstream.on('error',()=>socket.destroy());socket.on('error',()=>upstream.destroy());socket.on('close',()=>upstream.destroy());}catch{socket.destroy();}});
async function shutdown(){if(closing)return;closing=true;server.close();try{await stopApp();}catch{console.error('STOP_REQUIRES_RECONCILIATION');}for(let p of [...children].reverse())if(p.exitCode===null&&p.signalCode===null)try{process.kill(-p.pid,'SIGTERM')}catch{}setTimeout(()=>process.exit(0),1000);}
process.on('SIGTERM',shutdown);process.on('SIGINT',shutdown);
async function initializeDesktop(){
 try{
  desktopState.phase='display_starting';
  const display=start('/usr/bin/Xvfb',[':99','-screen','0','1440x1000x24','-nolisten','tcp','-ac']);
  await waitDesktopDisplay(display);
  desktopState.phase='vnc_starting';
  const vnc=start('/usr/bin/x11vnc',['-display',':99','-rfbport','5900','-localhost','-forever','-shared','-nopw','-noxdamage']);
  await waitDesktopPort(5900,vnc);
  desktopState.phase='proxy_starting';
  const web=start('/usr/bin/websockify',['--web','/usr/share/novnc','127.0.0.1:6080','127.0.0.1:5900']);
  await waitDesktopPort(6080,web);
  desktopState.phase='ready';desktopState.code=null;
  let initial='login';try{if(fs.readFileSync('/data/mode','utf8')==='bridge')initial='bridge';}catch{}
  await change('login');
  if(initial==='bridge'){for(let i=0;i<30;i++){let h=await bridgeHealth();if(h&&!h.interactiveChanging&&h.contextoAberto)break;await new Promise(r=>setTimeout(r,1000));}try{await change('bridge');}catch{mode='login';}}
 }catch(error){
  const codes=new Set(['display_in_use','bind_in_use','display_authorization','display_unavailable','dependency_missing','permission_denied','child_failed','child_exited','display_child_exited','desktop_child_exited','display_not_ready','local_port_unavailable']);
  desktopState.code=codes.has(error?.code)?error.code:'startup_unconfirmed';desktopState.phase='failed';mode='failed';
  console.error(JSON.stringify({event:'desktop_startup_failed',code:desktopState.code}));
 }
}
// AUTO_RECONCILE: a ponte se reativa sozinha (auto-recuperacao.mjs); o supervisor acompanha sem humano.
async function reconcileMode(){if(changing||closing||!app||desktopState.phase!=='ready'||!['login','bridge'].includes(mode))return;const h=await bridgeHealth();if(!h||changing)return;if(mode==='login'&&h.operatorLoginMode===false&&h.contextoPronto===true&&!h.interactiveChanging){mode='bridge';try{fs.writeFileSync('/data/mode.tmp','bridge',{mode:0o600});fs.renameSync('/data/mode.tmp','/data/mode');}catch{}console.error(JSON.stringify({event:'auto_reconcile',mode}));}}
setInterval(()=>{void reconcileMode().catch(()=>{});},15000).unref();
server.listen(Number(process.env.PORT||8080),'::',()=>{console.log('RAILWAY_BRIDGE_CONSOLE_STARTED');void initializeDesktop();});
