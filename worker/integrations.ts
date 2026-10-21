/** Official Meta/Stripe integrations. Remote writes are never replayed after ambiguity. */
import { Hono } from 'hono';
import { deleteCookie, getCookie, setCookie } from 'hono/cookie';
import type { Context } from 'hono';
import {
  all, apiError, base64url, decrypt, encrypt, exec, fromBase64url, isPublicHttps,
  now, one, originFor, randomToken, requireUser, sign, uid, verify,
  type AppEnv, type Env, type Post, type User,
} from './core';

export const integrationsRouter = new Hono<AppEnv>();
const STATE_COOKIE = 'autoposts_instagram_state';
const STATE_PATH = '/api/integrations/instagram';
const GRAPH = 'https://graph.instagram.com';
const STRIPE = 'https://api.stripe.com/v1';
const encoder = new TextEncoder();
interface Account { id:string; user_id:string; provider:string; platform_username:string; external_id:string; access_token:string; expires_at:string|null; created_at:string }
type ProviderObject = Record<string, unknown>;
export class IntegrationError extends Error {
  constructor(message:string, public retryable=false){super(message);this.name='IntegrationError';}
}
const later = (seconds:number) => new Date(Date.now()+seconds*1000).toISOString();
const instagramConfigured = (env:Env) => Boolean(env.INSTAGRAM_APP_ID && env.INSTAGRAM_APP_SECRET);
const stripeConfigured = (env:Env) => Boolean(env.STRIPE_SECRET_KEY && env.STRIPE_WEBHOOK_SECRET && env.STRIPE_PRICE_ID);
const accountPublic = (a:Account) => ({id:a.id,provider:a.provider,platform_username:a.platform_username,external_id:a.external_id,expires_at:a.expires_at,created_at:a.created_at});
function graphVersion(env:Env){const v=env.INSTAGRAM_GRAPH_VERSION||'v25.0';if(!/^v\d{1,3}\.\d{1,2}$/.test(v))throw new IntegrationError('A versão da API do Instagram é inválida.');return v;}
function graphId(value:unknown){const result=String(value||'');if(!/^\d{1,64}$/.test(result))throw new IntegrationError('O Instagram retornou um identificador inválido. Reconecte sua conta.');return result;}
function stringValue(value:unknown, max=8192){if(typeof value!=='string'||!value||value.length>max)throw new IntegrationError('O provedor retornou uma resposta inválida.');return value;}
function object(value:unknown):ProviderObject{if(!value||typeof value!=='object'||Array.isArray(value))throw new IntegrationError('O provedor retornou uma resposta inválida.');return value as ProviderObject;}
async function provider(url:string, init:RequestInit={}, retryable=false):Promise<ProviderObject>{
  let response:Response;
  try{response=await fetch(url,{...init,redirect:'error',signal:AbortSignal.timeout(15000)});}catch{throw new IntegrationError('O provedor não confirmou a operação. Confira sua conta antes de tentar novamente.',retryable);}
  if(!response.ok){const msg=[401,403].includes(response.status)?'A autorização do provedor expirou ou não possui a permissão necessária. Reconecte sua conta.':response.status===429?'O provedor atingiu o limite de uso. Aguarde antes de tentar novamente.':'O provedor não concluiu a operação. Verifique a configuração.';throw new IntegrationError(msg,retryable&&response.status>=500);}
  if(Number(response.headers.get('content-length')||0)>65536)throw new IntegrationError('O provedor retornou uma resposta inválida.');
  let result:ProviderObject;
  try{result=object(await response.json());}catch{throw new IntegrationError('O provedor retornou uma resposta inválida.',retryable);}
  if(result.error)throw new IntegrationError('O provedor recusou a operação. Confira a autorização da conta.');
  return result;
}
function form(data:Record<string,string>){return new URLSearchParams(data);}
function callback(env:Env, origin:string){return env.INSTAGRAM_REDIRECT_URI||origin+'/api/integrations/instagram/callback';}
function cookieOptions(c:Context<AppEnv>){return {httpOnly:true,secure:new URL(c.req.url).protocol==='https:',sameSite:'Lax' as const,path:STATE_PATH,maxAge:600};}
function oauthRedirect(c:Context<AppEnv>,success:boolean){deleteCookie(c,STATE_COOKIE,{...cookieOptions(c),maxAge:undefined});c.header('Cache-Control','no-store');return c.redirect('/?instagram='+(success?'connected':'error'),303);}

integrationsRouter.get('/api/accounts',async c=>{const user=requireUser(c);const accounts=await all<Account>(c.env,'SELECT * FROM accounts WHERE user_id=? ORDER BY created_at DESC',[user.id]);return c.json({accounts:accounts.map(accountPublic)});});
integrationsRouter.delete('/api/accounts/:id',async c=>{
  const user=requireUser(c), id=c.req.param('id');
  if(!await one(c.env,'SELECT id FROM accounts WHERE id=? AND user_id=?',[id,user.id]))apiError(404,'Conta não encontrada.');
  if(await one(c.env,"SELECT id FROM posts WHERE account_id=? AND user_id=? AND status IN ('scheduled','publishing') LIMIT 1",[id,user.id]))apiError(409,'Cancele os agendamentos desta conta antes de desconectá-la.');
  await c.env.DB.batch([
    c.env.DB.prepare("UPDATE campaigns SET enabled=0,next_run_at=NULL,last_error=?,updated_at=? WHERE account_id=? AND user_id=?").bind('Reconecte o Instagram para voltar a publicar.',now(),id,user.id),
    c.env.DB.prepare('UPDATE posts SET account_id=NULL WHERE account_id=? AND user_id=?').bind(id,user.id),
    c.env.DB.prepare('DELETE FROM accounts WHERE id=? AND user_id=?').bind(id,user.id),
  ]);
  return c.json({ok:true});
});
integrationsRouter.get('/api/integrations/instagram/authorize',async c=>{
  const user=requireUser(c), origin=new URL(c.req.url).origin;
  if(!instagramConfigured(c.env))apiError(503,'Configure INSTAGRAM_APP_ID e INSTAGRAM_APP_SECRET nos segredos do Worker.');
  const redirect=callback(c.env,origin);
  if(!isPublicHttps(origin)||!isPublicHttps(redirect))apiError(503,'Conecte o Instagram no endereço HTTPS público do Worker e cadastre o callback exato na Meta.');
  const nonce=randomToken();
  const payload=base64url(encoder.encode(JSON.stringify({user:user.id,nonce,expires:Date.now()+600000})));
  setCookie(c,STATE_COOKIE,payload+'.'+await sign(c.env,'instagram:'+payload),cookieOptions(c));
  const query=form({client_id:c.env.INSTAGRAM_APP_ID!,redirect_uri:redirect,response_type:'code',scope:'instagram_business_basic,instagram_business_content_publish',enable_fb_login:'0',force_authentication:'1',state:nonce});
  return c.json({url:'https://www.instagram.com/oauth/authorize?'+query});
});
integrationsRouter.get('/api/integrations/instagram/callback',async c=>{
  const user=requireUser(c);
  if(!instagramConfigured(c.env))apiError(503,'A integração com o Instagram não está configurada.');
  const raw=getCookie(c,STATE_COOKIE)||'';
  const [payload,signature]=raw.split('.');
  if(!payload||!signature||raw.length>2048||!await verify(c.env,'instagram:'+payload,signature))apiError(400,'A autorização expirou. Inicie a conexão novamente.');
  let state:{user:string;nonce:string;expires:number};
  try{state=JSON.parse(new TextDecoder().decode(fromBase64url(payload))) as typeof state;}catch{return oauthRedirect(c,false);}
  if(state.user!==user.id||typeof state.nonce!=='string'||state.nonce!==c.req.query('state')||!Number.isFinite(state.expires)||state.expires<Date.now())apiError(400,'Estado de autorização inválido. Inicie a conexão novamente.');
  if(c.req.query('error'))return oauthRedirect(c,false);
  const code=c.req.query('code')||'';
  if(!code||code.length>4096)apiError(400,'Código de autorização ausente ou inválido.');
  try{
    const origin=new URL(c.req.url).origin;
    let short=await provider('https://api.instagram.com/oauth/access_token',{method:'POST',body:form({client_id:c.env.INSTAGRAM_APP_ID!,client_secret:c.env.INSTAGRAM_APP_SECRET!,grant_type:'authorization_code',redirect_uri:callback(c.env,origin),code})});
    if(Array.isArray(short.data))short=object(short.data[0]);
    const shortToken=stringValue(short.access_token);
    const long=await provider(GRAPH+'/access_token?'+form({grant_type:'ig_exchange_token',client_secret:c.env.INSTAGRAM_APP_SECRET!,access_token:shortToken}));
    const token=stringValue(long.access_token);
    const profile=await provider(GRAPH+'/'+graphVersion(c.env)+'/me?fields=user_id,username',{headers:{Authorization:'Bearer '+token}});
    const externalId=graphId(profile.user_id||profile.id||short.user_id), username=stringValue(profile.username,100);
    const lifetime=Number(long.expires_in||5184000);
    if(!Number.isFinite(lifetime)||lifetime<86400||lifetime>31622400)throw new IntegrationError('Validade de autorização inválida.');
    await exec(c.env,`INSERT INTO accounts(id,user_id,provider,platform_username,external_id,access_token,expires_at,created_at) VALUES(?,?,'instagram',?,?,?,?,?) ON CONFLICT(user_id,provider,external_id) DO UPDATE SET platform_username=excluded.platform_username,access_token=excluded.access_token,expires_at=excluded.expires_at,created_at=excluded.created_at`,[uid(),user.id,username,externalId,await encrypt(c.env,token),later(lifetime),now()]);
    return oauthRedirect(c,true);
  }catch{return oauthRedirect(c,false);}
});

async function tokenFor(env:Env,account:Account):Promise<string>{
  let token:string;
  try{token=await decrypt(env,account.access_token);}catch{throw new IntegrationError('Não foi possível abrir a autorização. Reconecte o Instagram.');}
  if(!account.expires_at)return token;
  const expires=Date.parse(account.expires_at), issued=Date.parse(account.created_at);
  if(!Number.isFinite(expires)||expires<=Date.now())throw new IntegrationError('A autorização do Instagram expirou. Reconecte sua conta.');
  if(expires-Date.now()>7*86400000||Date.now()-issued<86400000)return token;
  if(!Number.isFinite(issued))throw new IntegrationError('A validade da autorização é inválida. Reconecte o Instagram.');
  const refreshed=await provider(GRAPH+'/refresh_access_token?'+form({grant_type:'ig_refresh_token',access_token:token}));
  token=stringValue(refreshed.access_token);
  const lifetime=Number(refreshed.expires_in);
  if(!Number.isFinite(lifetime)||lifetime<=86400||lifetime>31622400)throw new IntegrationError('Não foi possível renovar a autorização do Instagram.');
  await exec(env,'UPDATE accounts SET access_token=?,expires_at=?,created_at=? WHERE id=? AND user_id=?',[await encrypt(env,token),later(lifetime),now(),account.id,account.user_id]);
  return token;
}
async function fail(env:Env,id:string,message:string){await exec(env,"UPDATE posts SET status='failed',last_error=?,publish_lease_until=NULL,next_attempt_at=NULL,updated_at=? WHERE id=? AND status='publishing'",[message,now(),id]);}
async function pollLater(env:Env,post:Post){await exec(env,"UPDATE posts SET publish_phase='polling',publish_lease_until=NULL,next_attempt_at=?,retry_count=retry_count+1,updated_at=? WHERE id=? AND status='publishing'",[later(60),now(),post.id]);}

/** One durable state transition per Cron. Each remote mutation has a committed fence first. */
export async function processPublishing(env:Env,origin:string):Promise<void>{
  if(!isPublicHttps(origin))return;
  const current=now();
  const interrupted=await one<{id:string}>(env,"UPDATE posts SET status='failed',last_error=?,publish_lease_until=NULL,next_attempt_at=NULL,updated_at=? WHERE id=(SELECT id FROM posts WHERE status='publishing' AND publish_phase IN ('creating','sending') AND publish_lease_until<=? LIMIT 1) RETURNING id",['Uma publicação foi interrompida. Confira seu Instagram antes de tentar novamente para evitar duplicação.',current,current]);
  if(interrupted)return;
  let post=await one<Post>(env,"SELECT * FROM posts WHERE (status='scheduled' AND scheduled_at<=? AND (ready_at IS NULL OR ready_at<=?)) OR (status='publishing' AND publish_phase='polling' AND (next_attempt_at IS NULL OR next_attempt_at<=?) AND (publish_lease_until IS NULL OR publish_lease_until<=?)) ORDER BY scheduled_at,id LIMIT 1",[current,current,current,current]);
  if(!post)return;
  const creating=post.status==='scheduled';
  if(creating){post=await one<Post>(env,"UPDATE posts SET status='publishing',publish_phase='creating',publish_lease_until=?,retry_count=0,last_error=NULL,updated_at=? WHERE id=? AND status='scheduled' RETURNING *",[later(120),current,post.id]);}
  else{post=await one<Post>(env,"UPDATE posts SET publish_lease_until=?,updated_at=? WHERE id=? AND status='publishing' AND publish_phase='polling' AND (publish_lease_until IS NULL OR publish_lease_until<=?) RETURNING *",[later(120),current,post.id,current]);}
  if(!post)return;
  try{
    if(post.caption.length>2200)throw new IntegrationError('A legenda deve ter até 2.200 caracteres.');
    if(post.retry_count>=30)throw new IntegrationError('O Instagram excedeu o tempo de processamento. Confira a conta antes de tentar novamente.');
    if(!post.output_path||!await one(env,'SELECT id FROM media_files WHERE id=? AND user_id=? AND complete=1',[post.output_path,post.user_id]))throw new IntegrationError('O vídeo não está disponível. Gere-o novamente antes de agendar.');
    const account=await one<Account>(env,"SELECT * FROM accounts WHERE id=? AND user_id=? AND provider='instagram'",[post.account_id,post.user_id]);
    if(!account)throw new IntegrationError('A conta do Instagram foi desconectada. Reconecte-a para publicar.');
    const accountId=graphId(account.external_id), token=await tokenFor(env,account), headers={Authorization:'Bearer '+token};
    const root=GRAPH+'/'+graphVersion(env);
    if(creating){
      const created=await provider(root+'/'+accountId+'/media',{method:'POST',headers,body:form({media_type:'REELS',video_url:origin+'/media/'+post.public_token+'.mp4',caption:post.caption,share_to_feed:'true'})});
      await exec(env,"UPDATE posts SET container_id=?,publish_phase='polling',publish_lease_until=NULL,next_attempt_at=?,updated_at=? WHERE id=? AND status='publishing' AND publish_phase='creating'",[graphId(created.id),later(60),now(),post.id]);
      return;
    }
    const container=graphId(post.container_id);
    const state=await provider(root+'/'+container+'?fields=status_code,status',{headers},true);
    if(state.status_code==='IN_PROGRESS'){await pollLater(env,post);return;}
    if(state.status_code==='PUBLISHED'){
      await exec(env,"UPDATE posts SET status='published',publish_phase='complete',publish_lease_until=NULL,next_attempt_at=NULL,last_error=NULL,updated_at=? WHERE id=? AND status='publishing'",[now(),post.id]);return;
    }
    if(state.status_code!=='FINISHED')throw new IntegrationError('O Instagram recusou ou expirou o vídeo. Confira o formato e a autorização antes de tentar novamente.');
    const fenced=await one<{id:string}>(env,"UPDATE posts SET publish_phase='sending',publish_lease_until=?,updated_at=? WHERE id=? AND status='publishing' AND publish_phase='polling' RETURNING id",[later(120),now(),post.id]);
    if(!fenced)return;
    const published=await provider(root+'/'+accountId+'/media_publish',{method:'POST',headers,body:form({creation_id:container})});
    await exec(env,"UPDATE posts SET status='published',publish_phase='complete',publish_lease_until=NULL,media_id=?,next_attempt_at=NULL,last_error=NULL,updated_at=? WHERE id=? AND status='publishing' AND publish_phase='sending'",[graphId(published.id),now(),post.id]);
  }catch(e){
    if(!creating&&e instanceof IntegrationError&&e.retryable){const latest=await one<Post>(env,'SELECT * FROM posts WHERE id=?',[post.id]);if(latest?.publish_phase==='polling'){await pollLater(env,post);return;}}
    await fail(env,post.id,e instanceof IntegrationError?e.message:'Não foi possível confirmar a publicação. Confira seu Instagram antes de repetir a operação.');
  }
}

async function stripeRequest(env:Env,method:string,path:string,data?:Record<string,string>,key?:string):Promise<ProviderObject>{
  const headers:Record<string,string>={Authorization:'Bearer '+env.STRIPE_SECRET_KEY,'Stripe-Version':'2025-02-24.acacia'};
  if(key)headers['Idempotency-Key']=key;
  return provider(STRIPE+path,{method,headers,body:data?form(data):undefined});
}
function requireStripe(env:Env,origin:string){if(!stripeConfigured(env))apiError(503,'A cobrança é opcional. Configure STRIPE_SECRET_KEY, STRIPE_PRICE_ID e STRIPE_WEBHOOK_SECRET para ativá-la.');if(!isPublicHttps(origin))apiError(503,'Use o endereço HTTPS público do Worker para gerenciar assinaturas.');}
integrationsRouter.post('/api/billing/checkout',async c=>{
  const user=requireUser(c),origin=new URL(c.req.url).origin;requireStripe(c.env,origin);
  if(user.plan==='pro')apiError(409,'Sua conta já está no Pro. Use o portal para gerenciar a assinatura.');
  const data:Record<string,string>={mode:'subscription','line_items[0][price]':c.env.STRIPE_PRICE_ID!,'line_items[0][quantity]':'1',client_reference_id:user.id,'metadata[user_id]':user.id,'subscription_data[metadata][user_id]':user.id,success_url:origin+'/?billing=success',cancel_url:origin+'/?billing=cancelled'};
  if(user.stripe_customer_id)data.customer=user.stripe_customer_id;else data.customer_email=user.email;
  try{const session=await stripeRequest(c.env,'POST','/checkout/sessions',data,'checkout-'+user.id+'-'+uid());const url=stringValue(session.url);if(!url.startsWith('https://checkout.stripe.com/'))throw new IntegrationError('O Stripe não retornou um checkout válido.');return c.json({url});}catch(e){apiError(502,e instanceof IntegrationError?e.message:'O serviço de cobrança não está disponível.');}
});
integrationsRouter.post('/api/billing/portal',async c=>{
  const user=requireUser(c),origin=new URL(c.req.url).origin;requireStripe(c.env,origin);
  if(!user.stripe_customer_id)apiError(409,'Sua conta ainda não possui uma assinatura para gerenciar.');
  try{const session=await stripeRequest(c.env,'POST','/billing_portal/sessions',{customer:user.stripe_customer_id!,return_url:origin+'/'});const url=stringValue(session.url);if(!url.startsWith('https://billing.stripe.com/'))throw new IntegrationError('O Stripe não retornou um portal válido.');return c.json({url});}catch(e){apiError(502,e instanceof IntegrationError?e.message:'O serviço de cobrança não está disponível.');}
});
export async function verifyStripeSignature(payload:string,signature:string,secret:string,timestamp=Math.floor(Date.now()/1000)){
  if(!secret)apiError(503,'O webhook Stripe não está configurado.');
  if(signature.length>4096)apiError(400,'Assinatura de cobrança inválida.');
  const parts=signature.split(',').map(v=>v.split('='));
  const times=parts.filter(p=>p[0]==='t'),signatures=parts.filter(p=>p[0]==='v1').map(p=>p[1]);
  if(times.length!==1||!/^\d{1,15}$/.test(times[0]?.[1]||'')||!signatures.length)apiError(400,'Assinatura de cobrança inválida.');
  const signed=Number(times[0]![1]);
  if(Math.abs(timestamp-signed)>300)apiError(400,'A assinatura de cobrança expirou.');
  const key=await crypto.subtle.importKey('raw',encoder.encode(secret),{name:'HMAC',hash:'SHA-256'},false,['verify']);
  const data=encoder.encode(signed+'.'+payload);
  for(const candidate of signatures){if(candidate&&/^[a-f0-9]{64}$/.test(candidate)){const bytes=Uint8Array.from(candidate.match(/../g)!,v=>parseInt(v,16));if(await crypto.subtle.verify('HMAC',key,bytes,data))return;}}
  apiError(400,'Assinatura de cobrança inválida.');
}
interface SubscriptionChange {userId:string;customer:string;subscriptionId:string;plan:'free'|'pro'}
async function subscriptionChange(env:Env,event:ProviderObject):Promise<SubscriptionChange|null>{
  const data=object(event.data),item=object(data.object),type=event.type;
  let sub:unknown;
  if(type==='checkout.session.completed'){if(item.mode!=='subscription'||!item.subscription)return null;sub=item.subscription;}
  else if(['customer.subscription.created','customer.subscription.updated','customer.subscription.deleted'].includes(String(type)))sub=item.id;
  else return null;
  if(typeof sub!=='string'||!/^sub_[a-zA-Z0-9]+$/.test(sub))apiError(400,'Assinatura inválida no evento Stripe.');
  const subscription=await stripeRequest(env,'GET','/subscriptions/'+sub);
  const customer=typeof subscription.customer==='string'?subscription.customer:object(subscription.customer).id;
  const metadata=object(subscription.metadata||{}),userId=metadata.user_id;
  if(typeof customer!=='string'||!/^cus_[a-zA-Z0-9]+$/.test(customer)||typeof userId!=='string')return null;
  const items=object(subscription.items||{}).data;
  if(!Array.isArray(items)||!items.some(v=>{const item=object(v);return object(item.price||{}).id===env.STRIPE_PRICE_ID;}))return null;
  return {userId,customer,subscriptionId:sub,plan:['active','trialing'].includes(String(subscription.status))?'pro':'free'};
}
integrationsRouter.post('/api/billing/webhook',async c=>{
  if(!stripeConfigured(c.env))apiError(503,'O webhook Stripe não está configurado.');
  if(Number(c.req.header('Content-Length')||0)>65536)apiError(413,'Evento Stripe muito grande.');
  const payload=await c.req.text();if(encoder.encode(payload).length>65536)apiError(413,'Evento Stripe muito grande.');
  await verifyStripeSignature(payload,c.req.header('Stripe-Signature')||'',c.env.STRIPE_WEBHOOK_SECRET!);
  let event:ProviderObject;
  try{event=object(JSON.parse(payload));if(typeof event.id!=='string'||!/^evt_[a-zA-Z0-9]+$/.test(event.id))throw new Error();}catch{apiError(400,'Evento Stripe inválido.');}
  if(await one(c.env,'SELECT id FROM webhook_events WHERE id=?',[event.id]))return c.json({received:true,duplicate:true});
  let change:SubscriptionChange|null;
  try{change=await subscriptionChange(c.env,event);}catch(e){if(e instanceof IntegrationError)apiError(502,e.message);throw e;}
  const statements=[c.env.DB.prepare('INSERT OR IGNORE INTO webhook_events(id,created_at) VALUES(?,?)').bind(event.id,now())];
  if(change){statements.push(c.env.DB.prepare(`UPDATE users SET plan=?,stripe_customer_id=?,stripe_subscription_id=? WHERE id=? AND changes()=1 AND (stripe_customer_id IS NULL OR stripe_customer_id=?) AND NOT EXISTS(SELECT 1 FROM users WHERE stripe_customer_id=? AND id<>?) AND (stripe_subscription_id IS NULL OR stripe_subscription_id=? OR (plan<>'pro' AND ?='pro'))`).bind(change.plan,change.customer,change.subscriptionId,change.userId,change.customer,change.customer,change.userId,change.subscriptionId,change.plan));}
  await c.env.DB.batch(statements);
  return c.json({received:true});
});
