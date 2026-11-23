import {test} from 'node:test';import assert from 'node:assert/strict';
import {equal,session,validSession,cookieSession,validOrigin,bearerAuthorized} from './console-security.mjs';
const secret='x'.repeat(48),now=1792420000000;
test('signed session accepted only while valid',()=>{let s=session(secret,now);assert(validSession(s,secret,now));assert(!validSession(s,secret,now+7200000));assert(!validSession(s,'wrong',now));assert(!validSession(s+'x',secret,now));});
test('malformed and excessive lifetime rejected',()=>{for(let x of [null,{},'', '1.a','NaN.a',session(secret,now+1)])assert(!validSession(x,secret,now));});
test('duplicate cookies denied',()=>{let s=session(secret);assert(cookieSession({cookie:'__Host-bridge_console='+s},secret));assert(!cookieSession({cookie:'__Host-bridge_console='+s+'; __Host-bridge_console='+s},secret));assert(!cookieSession({},secret));});
test('csrf origins exact https host',()=>{assert(validOrigin({headers:{origin:'https://example.com',host:'example.com'}}));for(let o of [undefined,'null','http://example.com','https://example.com.evil'])assert(!validOrigin({headers:{origin:o,host:'example.com'}}));});
test('bridge bearer distinct from console cookies',()=>{assert(bearerAuthorized({headers:{authorization:'Bearer '+secret}},secret));assert(!bearerAuthorized({headers:{cookie:'__Host-bridge_console='+session(secret)}},secret));assert(!equal(undefined,undefined));assert(!equal('x','xx'));});
