import { Hono } from 'hono';
import { HTTPException } from 'hono/http-exception';
import { securityMiddleware, originFor, one, type AppEnv, type Env } from './core';
import { authRouter } from './auth';
import { postsRouter } from './posts';
import { automationRouter, runAutomation } from './automation';
import { integrationsRouter, processPublishing } from './integrations';
import { mediaRouter, processRender } from './media';

export const app = new Hono<AppEnv>();

app.use('*', async (c, next) => {
  await next();
  c.header('X-Content-Type-Options', 'nosniff');
  c.header('X-Frame-Options', 'DENY');
  c.header('Referrer-Policy', 'no-referrer');
  c.header('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
  c.header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'");
  if (c.req.path.startsWith('/api/') || c.req.path.startsWith('/internal/') || c.req.path.startsWith('/media/')) c.header('Cache-Control', 'no-store');
  if (new URL(c.req.url).protocol === 'https:') c.header('Strict-Transport-Security', 'max-age=31536000');
});
app.use('*', securityMiddleware);
app.get('/health', async (c) => {
  try {
    await one(c.env, 'SELECT 1 AS alive');
    return c.json({ status: 'ok', database: 'ok', runtime: 'cloudflare-workers' });
  } catch {
    return c.json({ status: 'error', database: 'error', runtime: 'cloudflare-workers' }, 503);
  }
});
app.route('/', authRouter);
app.route('/', postsRouter);
app.route('/', automationRouter);
app.route('/', integrationsRouter);
app.route('/', mediaRouter);
app.all('/api/*', (c) => c.json({ detail: 'Rota da API não encontrada.' }, 404));
app.all('/internal/*', (c) => c.json({ detail: 'Rota interna não encontrada.' }, 404));
app.all('/media/*', (c) => c.json({ detail: 'Arquivo não encontrado.' }, 404));
app.all('*', (c) => {
  if (c.req.method !== 'GET' && c.req.method !== 'HEAD') return c.json({ detail: 'Rota não encontrada.' }, 404);
  return c.env.ASSETS.fetch(c.req.raw);
});
app.onError((error, c) => {
  if (error instanceof HTTPException) return c.json({ detail: error.message }, error.status);
  // Never log provider URLs, OAuth codes, media capabilities, or credentials.
  console.error('Falha interna do Worker; consulte estado dos trabalhos e configuração dos bindings.');
  return c.json({ detail: 'Não foi possível concluir a operação. Tente novamente ou verifique a configuração.' }, 500);
});

export async function scheduledWork(env: Env): Promise<void> {
  let origin: string;
  try { origin = await originFor(env); } catch { origin = ''; }
  // Independent stages: an expired provider token cannot block other tenants' jobs.
  for (const [name, step] of [
    ['automation', () => runAutomation(env)],
    ['render', () => processRender(env, origin)],
    ['publish', () => processPublishing(env, origin)],
  ] as const) {
    try { await step(); } catch { console.error(`Etapa ${name} não concluída; o estado persistido será verificado no próximo Cron.`); }
  }
}

export default {
  fetch: app.fetch,
  scheduled(_controller: ScheduledController, env: Env, ctx: ExecutionContext) {
    ctx.waitUntil(scheduledWork(env));
  },
} satisfies ExportedHandler<Env>;
