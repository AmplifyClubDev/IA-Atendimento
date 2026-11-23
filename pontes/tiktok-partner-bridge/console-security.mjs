import crypto from 'node:crypto';
export function equal(a,b){if(typeof a!=='string'||typeof b!=='string')return false;let x=Buffer.from(a),y=Buffer.from(b);return x.length===y.length&&crypto.timingSafeEqual(x,y);}
export function session(secret,now=Date.now()){let data=String(now+2*60*60*1000);return data+'.'+crypto.createHmac('sha256',secret).update(data).digest('hex');}
export function validSession(value,secret,now=Date.now()){if(typeof value!=='string')return false;let parts=value.split('.');if(parts.length!==2||!/^\d{13}$/.test(parts[0])||!Number.isSafeInteger(Number(parts[0]))||Number(parts[0])<=now||Number(parts[0])>now+2*60*60*1000)return false;return equal(parts[1],crypto.createHmac('sha256',secret).update(parts[0]).digest('hex'));}
export function cookieSession(headers,secret){let values=String(headers.cookie||'').split(';').map(x=>x.trim()).filter(x=>x.startsWith('__Host-bridge_console='));return values.length===1&&validSession(values[0].slice('__Host-bridge_console='.length),secret);}
export function validOrigin(req){let origin=req.headers.origin;return typeof origin==='string'&&origin==='https://'+req.headers.host;}
export function consoleAuthorized(req,secret){return cookieSession(req.headers,secret);}
export function bearerAuthorized(req,secret){return equal(req.headers.authorization,'Bearer '+secret);}
