// Vercel Node entrypoint. No Python, database, local key, dependencies or worker.
import {isIP} from 'node:net';
import {MAX_UPLOAD,publicConfig,publicPlans} from '../web/config.mjs';
const MAX_BODY=MAX_UPLOAD+65536;
const HOP=new Set(['connection','keep-alive','proxy-authenticate','proxy-authorization','te','trailer','transfer-encoding','upgrade','host','content-length']);
const INTERNAL=['x-autoposts-gateway-token','x-autoposts-client-ip'];
const PRIVATE_PATH=/^\/(?:api(?:\/|$)|media(?:\/|$)|health$|privacy$|terms$|data-deletion$)/;
function publicHost(host){
  const value=host.replace(/^\[|\]$/g,'');
  if(isIP(value)===4){const [a,b]=value.split('.').map(Number);return !(a===0||a===10||a===127||a>=224||a===169&&b===254||a===172&&b>=16&&b<=31||a===192&&b===168||a===100&&b>=64&&b<=127);}
  if(isIP(value)===6)return /^[23]/i.test(value)&&!value.toLowerCase().startsWith('2001:db8:');
  return value.includes('.')&&!value.endsWith('.local')&&!value.endsWith('.internal')&&!value.endsWith('.localhost')&&value.split('.').every(label=>/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(label));
}
export function backendOrigin(env,host){
  const value=(env.AUTOPOSTS_BACKEND_URL||'').trim();if(!value)return {error:'BACKEND_NOT_CONFIGURED'};
  try{
    const url=new URL(value);
    if(url.protocol!=='https:'||url.username||url.password||url.pathname!=='/'||value.includes('?')||value.includes('#')||url.port||!publicHost(url.hostname)||/\s/.test(value))throw new Error();
    const hosts=[host,env.VERCEL_URL,env.VERCEL_PROJECT_PRODUCTION_URL,env.VERCEL_BRANCH_URL].filter(Boolean).map(item=>new URL(item.startsWith('https://')?item:'https://'+item).hostname.toLowerCase().replace(/\.$/,''));
    if(hosts.includes(url.hostname.toLowerCase().replace(/\.$/,'')))return {error:'BACKEND_PROXY_LOOP'};
    return {origin:url.origin};
  }catch{return {error:'BACKEND_CONFIGURATION_INVALID'};}
}
function json(data,status=200){return {status,body:Buffer.from(JSON.stringify(data)),headers:[['content-type','application/json; charset=utf-8']]};}
function unavailable(code='BACKEND_UNAVAILABLE',status=503){return json({detail:'O estúdio está temporariamente indisponível. Tente novamente mais tarde.',code},status);}
function setup(req,path,env,code){
  if(!['GET','HEAD'].includes(req.method))return unavailable(code);
  if(path==='/api/session')return json({user:null,csrf_token:null,service_ready:false,integrations:{instagram:false,stripe:false,mercadopago:false,ai:false}});
  if(path==='/api/public/config')return json(publicConfig(env,code));
  if(path==='/api/plans'){try{return json({plans:publicPlans(env)});}catch{return unavailable('PUBLIC_CATALOG_CONFIGURATION_INVALID');}}
  if(path==='/health')return json({status:'degraded',frontend:'ok',service_ready:false,code},503);
  if(['/privacy','/terms','/data-deletion'].includes(path))return {status:200,headers:[['content-type','text/html; charset=utf-8']],body:Buffer.from('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/styles.css"><title>AUTOPOSTS · Serviço em configuração</title><main class="public-page"><h1>Serviço em configuração</h1><p>O serviço ainda não está ativo. A documentação do operador será disponibilizada antes de liberar cadastros e pagamentos.</p><a href="/">Voltar ao início</a></main>')};
  return unavailable(code);
}
async function readBody(req){let size=0;const chunks=[];for await(const chunk of req){const data=Buffer.isBuffer(chunk)?chunk:Buffer.from(chunk);size+=data.length;if(size>MAX_BODY){const error=new Error('UPLOAD_TOO_LARGE');error.status=413;throw error;}chunks.push(data);}return Buffer.concat(chunks);}
export function createGateway({env=process.env,fetchImpl=globalThis.fetch,deadlineMs=50_000}={}){
  return async function gateway(req,res){
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),deadlineMs);timer.unref?.();
    let result;
    try{
      const requestURL=new URL(req.url,'https://'+(req.headers.host||'gateway.invalid'));
      // Support both original-path and destination-path Vercel rewrite adapters.
      // Remove only our routing parameter; preserve every other query byte.
      const pieces=requestURL.search.slice(1).split('&');
      const internal=pieces.find(part=>part.startsWith('__autoposts_route='));
      if(internal){
        const route=decodeURIComponent(internal.slice('__autoposts_route='.length));
        if(requestURL.pathname==='/api/gateway'&&PRIVATE_PATH.test(route)&&!/[?#\\]/.test(route))requestURL.pathname=route;
        requestURL.search=pieces.filter(part=>!part.startsWith('__autoposts_route=')).join('&');
      }
      if(!PRIVATE_PATH.test(requestURL.pathname)){result=unavailable('ROUTE_NOT_FOUND',404);}
      else{
        const target=backendOrigin(env,req.headers.host);
        if(!target.origin)result=setup(req,requestURL.pathname,env,target.error);
        else if(req.headers['x-autoposts-gateway']==='vercel')result=unavailable('BACKEND_PROXY_LOOP');
        else{
          const body=await readBody(req);const headers=new Headers();
          const skipped=new Set([...HOP,...INTERNAL,'accept-encoding',...(req.headers.connection||'').split(',').map(h=>h.trim().toLowerCase())]);
          for(const [name,value] of Object.entries(req.headers))if(value!==undefined&&!skipped.has(name.toLowerCase()))headers.set(name,Array.isArray(value)?value.join(', '):value);
          headers.set('x-autoposts-gateway','vercel');headers.set('accept-encoding','identity');
          if((env.AUTOPOSTS_GATEWAY_SECRET||'').length>=32){
            const ip=env.VERCEL==='1'?(req.headers['x-vercel-forwarded-for']||req.socket?.remoteAddress||'').split(',')[0].trim():req.socket?.remoteAddress;
            if(ip&&isIP(ip)){headers.set('x-autoposts-client-ip',ip);headers.set('x-autoposts-gateway-token',env.AUTOPOSTS_GATEWAY_SECRET);}
          }
          const upstream=await fetchImpl(target.origin+requestURL.pathname+requestURL.search,{method:req.method,headers,
            body:['GET','HEAD'].includes(req.method)?undefined:body,redirect:'manual',signal:controller.signal});
          if(upstream.status>=500){await upstream.body?.cancel();result=unavailable();}
          else{
            const chunks=[];let size=0;
            if(upstream.body)for await(const chunk of upstream.body){size+=chunk.length;if(size>MAX_UPLOAD)throw new Error('BACKEND_RESPONSE_TOO_LARGE');chunks.push(Buffer.from(chunk));}
            let payload=Buffer.concat(chunks);
            if(upstream.status===200&&['/api/public/config','/api/studio/config'].includes(requestURL.pathname)){
              let config;try{config=JSON.parse(payload);if(!config||Array.isArray(config)||typeof config!=='object')throw new Error();}catch{throw new Error('BACKEND_RESPONSE_INVALID');}
              if(requestURL.pathname==='/api/public/config'){config.backend_connected=config.backend_connected!==false;config.max_upload_bytes=MAX_UPLOAD;}
              else{config.max_photo_upload_bytes=MAX_UPLOAD;config.max_voice_upload_bytes=MAX_UPLOAD;}
              payload=Buffer.from(JSON.stringify(config));
            }
            const blocked=new Set([...HOP,...INTERNAL,'content-encoding','set-cookie',...(upstream.headers.get('connection')||'').split(',').map(h=>h.trim().toLowerCase())]);
            const responseHeaders=[...upstream.headers.entries()].filter(([name])=>!blocked.has(name.toLowerCase()));
            const cookies=upstream.headers.getSetCookie();
            if(cookies.length)responseHeaders.push(['set-cookie',cookies]);
            result={status:upstream.status,body:payload,headers:responseHeaders};
          }
        }
      }
    }catch(error){
      const code=controller.signal.aborted?'BACKEND_TIMEOUT':['BACKEND_RESPONSE_INVALID','BACKEND_RESPONSE_TOO_LARGE','UPLOAD_TOO_LARGE'].includes(error.message)?error.message:'BACKEND_UNAVAILABLE';
      result=unavailable(code,error.status|| (code==='BACKEND_RESPONSE_TOO_LARGE'?502:503));
    }finally{clearTimeout(timer);}
    if(res.destroyed||res.writableEnded)return;
    res.statusCode=result.status;
    for(const [name,value] of result.headers)res.setHeader(name,value);
    res.setHeader('cache-control','no-store');res.setHeader('x-content-type-options','nosniff');res.setHeader('x-frame-options','DENY');
    res.end(req.method==='HEAD'?undefined:result.body);
  };
}
export default createGateway();
