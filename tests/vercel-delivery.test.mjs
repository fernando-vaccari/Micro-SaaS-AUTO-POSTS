import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {gzipSync} from 'node:zlib';
import {createGateway,backendOrigin} from '../api/gateway.mjs';
import {buildSite} from '../scripts/build-vercel.mjs';
import {createSiteServer} from '../scripts/serve-vercel-local.mjs';
async function listen(server,t){await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));t.after(()=>new Promise(resolve=>{server.closeAllConnections();server.close(resolve);}));return 'http://127.0.0.1:'+server.address().port;}
async function gateway(t,options={}){return listen(createServer(createGateway(options)),t);}
const env={AUTOPOSTS_BACKEND_URL:'https://backend.example.com'};
const ok=()=>new Response('{}',{headers:{'content-type':'application/json'}});
test('static homepage and favicon survive a completely failed API function',async t=>{
 const lock=JSON.parse(await readFile(new URL('../package-lock.json',import.meta.url)));assert.deepEqual(Object.keys(lock.packages),['']);
 const root=await mkdtemp(path.join(os.tmpdir(),'autoposts-static-'));t.after(()=>rm(root,{recursive:true,force:true}));
 await buildSite(root,{MP_ACCESS_TOKEN:'not-for-browser',AUTOPOSTS_BACKEND_URL:'https://private-backend.example.com',AUTOPOSTS_GATEWAY_SECRET:'private-not-for-browser'});
 const url=await listen(createSiteServer({root,gateway:(req,res)=>{res.statusCode=500;res.end('FUNCTION_INVOCATION_FAILED');}}),t);
 for(const file of ['/','/favicon.ico','/app.js','/uploads.js','/login','/cadastro'])assert.equal((await fetch(url+file)).status,200,file);
 assert.equal((await fetch(url+'/api/session')).status,500);
 const bootstrap=await (await fetch(url+'/site-config.json')).text();assert(!bootstrap.includes('not-for-browser'));assert(!bootstrap.includes('private-backend'));
 const icon=await readFile(path.join(root,'favicon.ico'));assert.equal(icon.readUInt16LE(2),1);assert.equal(icon.readUInt16LE(4),1);
});
test('public fallback has no local accounts, sessions or pretend service',async t=>{
 const url=await gateway(t,{env:{}});
 const session=await (await fetch(url+'/api/session')).json();assert.equal(session.user,null);assert.equal(session.csrf_token,null);
 assert.equal((await (await fetch(url+'/api/plans')).json()).plans[0].price_cents,14999);
 assert.equal((await (await fetch(url+'/api/public/config')).json()).backend_connected,false);
 for(const p of ['/api/auth/register','/api/billing/checkout','/api/studio'])assert.equal((await fetch(url+p,{method:'POST',body:'{}'})).status,503);
 assert.equal((await fetch(url+'/health')).status,503);
});
for(const value of ['http://backend.example.com','https://localhost','https://127.0.0.1','https://127.1','https://10.0.0.1','https://[::1]','https://user:password@backend.example.com','https://backend.example.com/api','https://backend.example.com?token=private','https://backend.example.com:9000','not-a-url'])test('reject invalid backend '+value,()=>assert.equal(backendOrigin({AUTOPOSTS_BACKEND_URL:value},'web.example.com').error,'BACKEND_CONFIGURATION_INVALID'));
test('block self-proxy loops',()=>{
 assert.equal(backendOrigin({AUTOPOSTS_BACKEND_URL:'https://web.example.com'},'web.example.com').error,'BACKEND_PROXY_LOOP');
 assert.equal(backendOrigin({AUTOPOSTS_BACKEND_URL:'https://project.vercel.app',VERCEL_URL:'project.vercel.app'},'web.example.com').error,'BACKEND_PROXY_LOOP');
});
test('forward exact body, query, CSRF, cookie and idempotency once',async t=>{
 const body=gzipSync(Buffer.from('{ "data": {"id":"123"} }'));let calls=0;
 const url=await gateway(t,{env,fetchImpl:async(target,options)=>{calls++;assert.equal(target,'https://backend.example.com/api/billing/mercadopago/webhook?data.id=123&x=a%2Bb');assert.deepEqual(options.body,body);for(const [name,value] of Object.entries({'x-signature':'signature','x-request-id':'request','x-csrf-token':'csrf','cookie':'session=one','idempotency-key':'request-1234567890','content-encoding':'gzip'}))assert.equal(options.headers.get(name),value);assert.equal(options.redirect,'manual');return ok();}});
 const response=await fetch(url+'/api/billing/mercadopago/webhook?data.id=123&x=a%2Bb',{method:'POST',body,headers:{'x-signature':'signature','x-request-id':'request','x-csrf-token':'csrf','cookie':'session=one','idempotency-key':'request-1234567890','content-encoding':'gzip'}});
 assert.equal(response.status,200);assert.equal(calls,1);
});
test('return separate secure cookies and avoid sharing cookies between calls',async t=>{
 const seen=[];const url=await gateway(t,{env,fetchImpl:async(_,options)=>{seen.push(options.headers.get('cookie'));return new Response('{}',{headers:[['set-cookie','autoposts_session=one; Path=/; Secure; HttpOnly'],['set-cookie','autoposts_csrf=two; Path=/; Secure; HttpOnly']]});}});
 const response=await fetch(url+'/api/session',{headers:{cookie:'owner=one'}});assert.equal(response.headers.getSetCookie().length,2);
 await fetch(url+'/api/session');assert.deepEqual(seen,['owner=one',null]);
});
test('preserve redirect to private R2 without fetching media',async t=>{
 let calls=0;const url=await gateway(t,{env,fetchImpl:async()=>{calls++;return new Response(null,{status:307,headers:{location:'https://bucket.r2.cloudflarestorage.com/private.mp4?signature=test'}});}});
 const response=await fetch(url+'/api/posts/post/media',{redirect:'manual'});assert.equal(response.status,307);assert.equal(calls,1);assert(response.headers.get('location').includes('r2.cloudflarestorage.com'));
});
test('authenticate forwarded client identity and never expose the token',async t=>{
 const secret='test-only-shared-key-longer-than-32-characters';const url=await gateway(t,{env:{...env,VERCEL:'1',AUTOPOSTS_GATEWAY_SECRET:secret},fetchImpl:async(_,options)=>{assert.equal(options.headers.get('x-autoposts-client-ip'),'203.0.113.10');assert.equal(options.headers.get('x-autoposts-gateway-token'),secret);return new Response('{}',{headers:{'x-autoposts-gateway-token':secret}});}});
 const response=await fetch(url+'/api/session',{headers:{'x-vercel-forwarded-for':'203.0.113.10','x-autoposts-client-ip':'198.51.100.20','x-autoposts-gateway-token':'forged'}});assert.equal(response.status,200);assert.equal(response.headers.get('x-autoposts-gateway-token'),null);
});
test('return controlled backend failure without leaking details or retrying',async t=>{
 let calls=0;const url=await gateway(t,{env,fetchImpl:async()=>{calls++;throw new Error('private-key-and-host');}});const response=await fetch(url+'/api/session');assert.equal(response.status,503);assert(!(await response.text()).includes('private-key'));assert.equal(calls,1);
});
test('abort a slow upstream before the function deadline',async t=>{
 const url=await gateway(t,{env,deadlineMs:10,fetchImpl:async(_,options)=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new Error('aborted')),{once:true}))});
 const response=await fetch(url+'/api/session');assert.equal(response.status,503);assert.equal((await response.json()).code,'BACKEND_TIMEOUT');
});
test('bound response size',async t=>{
 const url=await gateway(t,{env,fetchImpl:async()=>new Response('x'.repeat(4*1024*1024+1))});const response=await fetch(url+'/api/test');assert.equal(response.status,502);assert.equal((await response.json()).code,'BACKEND_RESPONSE_TOO_LARGE');
});
test('reject oversized input before forwarding',async t=>{
 let called=false;const url=await gateway(t,{env,fetchImpl:async()=>{called=true;return ok();}});const response=await fetch(url+'/api/assets',{method:'POST',body:Buffer.alloc(4*1024*1024+65537)});assert.equal(response.status,413);assert.equal(called,false);
});
test('connected public configuration stays authoritative and bounded',async t=>{
 const url=await gateway(t,{env,fetchImpl:async()=>new Response(JSON.stringify({edition:'demo',production:true}),{headers:{'content-type':'application/json'}})});
 const cfg=await (await fetch(url+'/api/public/config')).json();assert.equal(cfg.backend_connected,true);assert.equal(cfg.edition,'demo');assert.equal(cfg.max_upload_bytes,4*1024*1024);
});
test('configuration of a second unready gateway is not advertised as ready',async t=>{
 const url=await gateway(t,{env,fetchImpl:async()=>new Response('{"backend_connected":false}')});assert.equal((await (await fetch(url+'/api/public/config')).json()).backend_connected,false);
});

test('destination-path rewrite preserves the original API route and query bytes',async t=>{
 const url=await gateway(t,{env,fetchImpl:async(target)=>{assert.equal(target,'https://backend.example.com/api/billing/mercadopago/webhook?data.id=123&x=a%2Bb');return ok();}});
 const response=await fetch(url+'/api/gateway?__autoposts_route=%2Fapi%2Fbilling%2Fmercadopago%2Fwebhook&data.id=123&x=a%2Bb',{method:'POST',body:'{}'});assert.equal(response.status,200);
});
