import { Hono } from 'hono';
import { deleteCookie, setCookie } from 'hono/cookie';
import { type AppEnv, type User, now, uid, one, exec, apiError, jsonBody, publicUser, requireSecret, csrfFor, hash, randomToken, base64url, fromBase64url, SESSION_COOKIE, SESSION_SECONDS, rememberOrigin, isPublicHttps } from './core';

export const authRouter = new Hono<AppEnv>();
const encoder=new TextEncoder();
export async function passwordHash(password:string,salt=crypto.getRandomValues(new Uint8Array(16))):Promise<string>{
  const key=await crypto.subtle.importKey('raw',encoder.encode(password),'PBKDF2',false,['deriveBits']);
  const bits=await crypto.subtle.deriveBits({name:'PBKDF2',hash:'SHA-256',salt,iterations:100000},key,256);
  return `pbkdf2-sha256$100000$${base64url(salt)}$${base64url(new Uint8Array(bits))}`;
}
export async function passwordMatches(password:string,stored:string){
  const [format,rounds,salt,expected]=stored.split('$');
  if(format!=='pbkdf2-sha256'||rounds!=='100000'||!salt||!expected)return false;
  try{const value=(await passwordHash(password,fromBase64url(salt))).split('$')[3];const a=fromBase64url(value),b=fromBase64url(expected);if(a.length!==b.length)return false;let delta=0;for(let i=0;i<a.length;i++)delta|=a[i]^b[i];return delta===0;}catch{return false;}
}
async function rate(c:Parameters<typeof csrfFor>[0],kind:string,maximum:number,seconds:number){
  const key=await hash(kind+':'+(c.req.header('CF-Connecting-IP')||'local'));
  const stamp=now();const until=new Date(Date.now()+seconds*1000).toISOString();
  const row=await one<{count:number}>(c.env,`INSERT INTO auth_attempts(key,count,expires_at) VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=CASE WHEN expires_at<? THEN 1 ELSE count+1 END,expires_at=CASE WHEN expires_at<? THEN excluded.expires_at ELSE expires_at END RETURNING count`,[key,until,stamp,stamp]);
  if(row&&row.count>maximum){c.header('Retry-After',String(seconds));apiError(429,'Muitas tentativas. Aguarde antes de tentar novamente.');}
}
function credentials(body:Record<string,unknown>){
  const email=typeof body.email==='string'?body.email.trim().toLowerCase():'';
  const password=typeof body.password==='string'?body.password:'';
  if(email.length>254||!/^\S+@[^\s@]+\.[^\s@]+$/.test(email))apiError(422,'Informe um email válido.');
  if(password.length<10||password.length>128)apiError(422,'A senha deve ter entre 10 e 128 caracteres.');
  return {email,password};
}
async function setSession(c:Parameters<typeof csrfFor>[0],userId:string){
  const raw=randomToken();const csrf=await csrfFor(c);const stamp=now();
  const previous=c.get('sessionId');
  const sql=c.env.DB.prepare('INSERT INTO sessions(id,user_id,csrf_hash,expires_at,created_at) VALUES(?,?,?,?,?)').bind(await hash(raw),userId,await hash(csrf),new Date(Date.now()+SESSION_SECONDS*1000).toISOString(),stamp);
  await c.env.DB.batch(previous?[c.env.DB.prepare('DELETE FROM sessions WHERE id=?').bind(previous),sql]:[sql]);
  setCookie(c,SESSION_COOKIE,raw,{httpOnly:true,secure:new URL(c.req.url).protocol==='https:',sameSite:'Lax',path:'/',maxAge:SESSION_SECONDS});
}
authRouter.get('/api/session',async c=>{
  requireSecret(c.env);await rememberOrigin(c);
  const origin=new URL(c.req.url).origin;const publicUrl=isPublicHttps(c.env.APP_URL||origin);
  return c.json({user:c.get('user')?publicUser(c.get('user')!):null,csrf_token:await csrfFor(c),integrations:{instagram:!!(c.env.INSTAGRAM_APP_ID&&c.env.INSTAGRAM_APP_SECRET&&publicUrl),stripe:!!(c.env.STRIPE_SECRET_KEY&&c.env.STRIPE_WEBHOOK_SECRET&&c.env.STRIPE_PRICE_ID&&publicUrl),ai:!!c.env.AI},limits:{free_posts:3,pro_posts:100,max_duration:15,max_asset_bytes:524288},setup:{secret:true,public_url:publicUrl,browser:!!c.env.BROWSER},platform:{max_renders_per_day:8,max_ai_calls_per_day:10,max_library_files:20,max_library_bytes:20971520}});
});
authRouter.post('/api/auth/register',async c=>{
  await rate(c,'register',10,3600);const body=await jsonBody(c);const {email,password}=credentials(body);
  const name=typeof body.name==='string'?body.name.trim():'';if(name.length<2||name.length>80)apiError(422,'O nome deve ter entre 2 e 80 caracteres.');
  const user:User={id:uid(),email,name,plan:'free',created_at:now()};const digest=await passwordHash(password);
  try{await exec(c.env,'INSERT INTO users(id,email,name,password_hash,created_at) VALUES(?,?,?,?,?)',[user.id,email,name,digest,user.created_at]);}catch(e){if(String(e).includes('UNIQUE'))apiError(409,'Este email já possui uma conta.');throw e;}
  await setSession(c,user.id);return c.json({user:publicUser(user)},201);
});
authRouter.post('/api/auth/login',async c=>{
  await rate(c,'login',20,600);const {email,password}=credentials(await jsonBody(c));
  const user=await one<User>(c.env,'SELECT * FROM users WHERE email=?',[email]);
  if(!user){await passwordHash(password);apiError(401,'Email ou senha incorretos.');}
  if(!(await passwordMatches(password,user.password_hash||'')))apiError(401,'Email ou senha incorretos.');
  await setSession(c,user.id);return c.json({user:publicUser(user)});
});
authRouter.post('/api/auth/logout',async c=>{const id=c.get('sessionId');if(id)await exec(c.env,'DELETE FROM sessions WHERE id=?',[id]);deleteCookie(c,SESSION_COOKIE,{path:'/'});return c.json({ok:true});});
