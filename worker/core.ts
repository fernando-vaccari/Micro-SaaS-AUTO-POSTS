import type { Context, MiddlewareHandler } from 'hono';
import { HTTPException } from 'hono/http-exception';
import { getCookie, setCookie } from 'hono/cookie';

export interface Env {
  DB: D1Database; MEDIA: KVNamespace; AI: Ai; BROWSER: Fetcher; ASSETS: Fetcher;
  APP_SECRET: string; APP_URL?: string;
  INSTAGRAM_APP_ID?: string; INSTAGRAM_APP_SECRET?: string; INSTAGRAM_REDIRECT_URI?: string; INSTAGRAM_GRAPH_VERSION?: string;
  STRIPE_SECRET_KEY?: string; STRIPE_WEBHOOK_SECRET?: string; STRIPE_PRICE_ID?: string;
}
export interface User { id: string; email: string; name: string; plan: 'free'|'pro'; created_at: string; password_hash?: string; stripe_customer_id?: string|null; stripe_subscription_id?: string|null }
export interface Post { id: string; user_id: string; title: string; caption: string; scenes: string; duration: number; theme: string; status: string; scheduled_at: string|null; account_id: string|null; public_token: string; output_path: string|null; ready_at: string|null; container_id: string|null; publish_phase: string|null; publish_lease_until: string|null; media_id: string|null; last_error: string|null; retry_count: number; next_attempt_at: string|null; created_at: string; updated_at: string }
export interface Scene {text: string; asset_id?: string|null}
export interface PostInput {title:string;caption:string;scenes:Scene[];duration:number;theme:string}
export type AppEnv = {Bindings:Env;Variables:{user:User|null;sessionId:string|null}};
export const SESSION_COOKIE = 'autoposts_session';
export const CSRF_COOKIE = 'autoposts_csrf';
export const SESSION_SECONDS = 30*86400;
export const now = () => new Date().toISOString();
export const uid = () => crypto.randomUUID().replaceAll('-','');
export const apiError = (status:number,message:string):never => {throw new HTTPException(status as 400,{message});};
export async function one<T=Record<string,unknown>>(env:Env,sql:string,params:unknown[]=[]):Promise<T|null>{return env.DB.prepare(sql).bind(...params).first<T>();}
export async function all<T=Record<string,unknown>>(env:Env,sql:string,params:unknown[]=[]):Promise<T[]>{return (await env.DB.prepare(sql).bind(...params).all<T>()).results;}
export async function exec(env:Env,sql:string,params:unknown[]=[]):Promise<D1Result>{return env.DB.prepare(sql).bind(...params).run();}
export function requireUser(c:Context<AppEnv>):User {const user=c.get('user');if(!user)apiError(401,'Entre na sua conta para continuar.');return user;}
export function publicUser(u:User){return {id:u.id,email:u.email,name:u.name,plan:u.plan,created_at:u.created_at};}
export function requireSecret(env:Env){if(!env.APP_SECRET||env.APP_SECRET.length<32)apiError(503,'Configure APP_SECRET com pelo menos 32 caracteres nos segredos do Worker.');}
const encoder = new TextEncoder();
export function base64url(bytes:Uint8Array):string {let s='';for(const b of bytes)s+=String.fromCharCode(b);return btoa(s).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,'');}
export function fromBase64url(s:string):Uint8Array {if(!/^[a-zA-Z0-9_-]*$/.test(s))throw new Error('Invalid encoding');return Uint8Array.from(atob(s.replaceAll('-','+').replaceAll('_','/')+'='.repeat((4-s.length%4)%4)),c=>c.charCodeAt(0));}
export function randomToken(){return base64url(crypto.getRandomValues(new Uint8Array(32)));}
export async function hash(s:string){return base64url(new Uint8Array(await crypto.subtle.digest('SHA-256',encoder.encode(s))));}
export async function sign(env:Env,data:string){requireSecret(env);const key=await crypto.subtle.importKey('raw',encoder.encode(env.APP_SECRET),{name:'HMAC',hash:'SHA-256'},false,['sign']);return base64url(new Uint8Array(await crypto.subtle.sign('HMAC',key,encoder.encode(data))));}
export async function verify(env:Env,data:string,signature:string){try{requireSecret(env);const key=await crypto.subtle.importKey('raw',encoder.encode(env.APP_SECRET),{name:'HMAC',hash:'SHA-256'},false,['verify']);return await crypto.subtle.verify('HMAC',key,fromBase64url(signature),encoder.encode(data));}catch{return false;}}
async function encryptionKey(env:Env){requireSecret(env);return crypto.subtle.importKey('raw',await crypto.subtle.digest('SHA-256',encoder.encode(env.APP_SECRET)),{name:'AES-GCM'},false,['encrypt','decrypt']);}
export async function encrypt(env:Env,text:string){const iv=crypto.getRandomValues(new Uint8Array(12));const body=await crypto.subtle.encrypt({name:'AES-GCM',iv},await encryptionKey(env),encoder.encode(text));return 'v1.'+base64url(iv)+'.'+base64url(new Uint8Array(body));}
export async function decrypt(env:Env,value:string){const [v,iv,body]=value.split('.');if(v!=='v1'||!iv||!body)throw new Error('Invalid encrypted secret');const result=await crypto.subtle.decrypt({name:'AES-GCM',iv:fromBase64url(iv)},await encryptionKey(env),fromBase64url(body));return new TextDecoder().decode(result);}
export function isPublicHttps(value:string){try{const u=new URL(value);const h=u.hostname.toLowerCase();if(u.protocol!=='https:'||u.username||u.password||!h||!h.includes('.')||h==='localhost'||h.endsWith('.local')||h.endsWith('.internal')||h.endsWith('.localhost'))return false;if(/^\d+\.\d+\.\d+\.\d+$/.test(h)){const [a,b]=h.split('.').map(Number);return ![0,10,127].includes(a)&&!(a===169&&b===254)&&!(a===172&&b>=16&&b<=31)&&!(a===192&&b===168)&&!(a===100&&b>=64&&b<=127)&&a<224;}return !h.includes(':');}catch{return false;}}
export async function originFor(env:Env){if(env.APP_URL){const u=new URL(env.APP_URL);if(isPublicHttps(u.origin)||['localhost','127.0.0.1','[::1]'].includes(u.hostname))return u.origin;}return (await one<{value:string}>(env,"SELECT value FROM app_config WHERE key='public_origin'"))?.value||'';}
export async function rememberOrigin(c:Context<AppEnv>){const u=new URL(c.req.url);if(isPublicHttps(u.origin)&&(!c.env.APP_URL||new URL(c.env.APP_URL).origin===u.origin))await exec(c.env,"INSERT INTO app_config(key,value) VALUES('public_origin',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value WHERE value<>excluded.value",[u.origin]);}
export async function csrfFor(c:Context<AppEnv>){let raw=getCookie(c,CSRF_COOKIE)||'';let [token,signature]=raw.split('.');if(!token||!signature||!(await verify(c.env,'csrf:'+token,signature))){token=randomToken();raw=token+'.'+await sign(c.env,'csrf:'+token);setCookie(c,CSRF_COOKIE,raw,{httpOnly:true,secure:new URL(c.req.url).protocol==='https:',sameSite:'Lax',path:'/',maxAge:SESSION_SECONDS});}return token;}
export const securityMiddleware:MiddlewareHandler<AppEnv>=async(c,next)=>{
  c.set('user',null);c.set('sessionId',null);
  if(!c.req.path.startsWith('/api/'))return next();
  requireSecret(c.env);
  const cookie=getCookie(c,SESSION_COOKIE);
  let session:{id:string;csrf_hash:string}|null=null;
  if(cookie&&cookie.length<=128){const id=await hash(cookie);const row=await one<User&{session_id:string;csrf_hash:string}>(c.env,'SELECT u.*,s.id AS session_id,s.csrf_hash FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id=? AND s.expires_at>?',[id,now()]);if(row){c.set('user',row);c.set('sessionId',row.session_id);session={id:row.session_id,csrf_hash:row.csrf_hash};}}
  if(['POST','PUT','PATCH','DELETE'].includes(c.req.method)&&c.req.path!=='/api/billing/webhook'){
    const origin=c.req.header('Origin');const expected=new URL(c.req.url).origin;
    if((origin&&origin!==expected)||c.req.header('Sec-Fetch-Site')==='cross-site')apiError(403,'Origem da requisição não permitida.');
    const token=c.req.header('X-CSRF-Token')||'';const [cookieToken,signature]=(getCookie(c,CSRF_COOKIE)||'').split('.');
    if(!token||token.length>128||token!==cookieToken||!signature||!(await verify(c.env,'csrf:'+token,signature))||(session&&await hash(token)!==session.csrf_hash))apiError(403,'Sessão de segurança expirada. Recarregue a página.');
    const declared=Number(c.req.header('Content-Length')||0);const max=c.req.path==='/api/assets'?524288+65536:65536;if(declared>max)apiError(413,'O arquivo ou requisição excede o tamanho permitido.');
  }
  await next();
};
export async function usage(env:Env,user:User){const row=await one<{count:number}>(env,'SELECT count FROM post_usage WHERE user_id=? AND month=?',[user.id,now().slice(0,7)]);return {used:row?.count||0,limit:user.plan==='pro'?100:3,plan:user.plan};}
export function publicPost(post:Post){const {user_id,public_token,scenes,...rest}=post;void user_id;void public_token;return {...rest,scenes:JSON.parse(scenes),video_url:post.output_path?`/api/posts/${post.id}/video`:null};}
export async function reservePost(env:Env,user:User,input:PostInput,options:{status?:string;id?:string}={}):Promise<Post>{
  const id=options.id||uid();const existing=await one<Post>(env,'SELECT * FROM posts WHERE id=? AND user_id=?',[id,user.id]);if(existing)return existing;
  const stamp=now();
  try{await exec(env,`INSERT INTO posts(id,user_id,title,caption,scenes,duration,theme,status,public_token,created_at,updated_at) SELECT ?,?,?,?,?,?,?,?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM posts WHERE id=?)`,[id,user.id,input.title,input.caption,JSON.stringify(input.scenes),input.duration,input.theme,options.status||'draft',randomToken(),stamp,stamp,id]);}catch(e){if(String(e).includes('MONTHLY_QUOTA'))apiError(429,'Você atingiu a cota mensal. Ela renova no próximo mês UTC.');throw e;}
  const post=await one<Post>(env,'SELECT * FROM posts WHERE id=? AND user_id=?',[id,user.id]);if(!post)apiError(409,'Esta publicação já foi reservada.');return post;
}
export async function ownedPost(env:Env,id:string,user:User){const post=await one<Post>(env,'SELECT * FROM posts WHERE id=? AND user_id=?',[id,user.id]);if(!post)apiError(404,'Publicação não encontrada.');return post;}
export function publicAccount(account:Record<string,unknown>){const {id,provider,platform_username,external_id,expires_at,created_at}=account;return {id,provider,platform_username,external_id,expires_at,created_at};}
export async function jsonBody(c:Context<AppEnv>){const raw=await c.req.text();if(raw.length>65536)apiError(413,'Requisição muito grande.');try{const value=JSON.parse(raw);if(!value||typeof value!=='object'||Array.isArray(value))throw new Error();return value as Record<string,unknown>;}catch{apiError(400,'Envie um objeto JSON válido.');}}
