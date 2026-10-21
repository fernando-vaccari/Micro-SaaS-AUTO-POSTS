import puppeteer from '@cloudflare/puppeteer';
import { Hono } from 'hono';
import type { Context } from 'hono';
import { all, apiError, exec, now, one, requireUser, sign, verify } from './core';
import type { AppEnv, Env, Post, Scene } from './core';

export const mediaRouter = new Hono<AppEnv>();
export const VIDEO_MAX_BYTES = 4 * 1024 * 1024;
const GLOBAL_STORAGE_BYTES = 100 * 1024 * 1024;
const USER_STORAGE_BYTES = 20 * 1024 * 1024;
const MAX_RENDERS_DAILY = 8;
const RENDER_SECONDS_RESERVED = 45;
interface RenderJob { id: string; user_id: string; status: string; token_hash: string | null; expires_at: string | null }
interface MediaFile { id: string; user_id: string; kind: string; media_type: string; size: number; complete: number }
interface MediaMeta { size: number; media_type: string }

export interface ByteRange { start: number; end: number }
export function parseByteRange(header: string | undefined, size: number): ByteRange | null {
  if (!header) return null;
  const match = /^bytes=(\d*)-(\d*)$/.exec(header.trim());
  if (!match || (!match[1] && !match[2]) || !Number.isSafeInteger(size) || size <= 0) throw new Error('Invalid range');
  let start: number;
  let end: number;
  if (!match[1]) {
    const suffix = Number(match[2]);
    if (!Number.isSafeInteger(suffix) || suffix <= 0) throw new Error('Invalid range');
    start = Math.max(0, size - suffix);
    end = size - 1;
  } else {
    start = Number(match[1]);
    end = match[2] ? Number(match[2]) : size - 1;
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || start >= size || end < start) throw new Error('Invalid range');
    end = Math.min(end, size - 1);
  }
  return { start, end };
}

/** Slice native KV stream chunks without concatenating or JSON-encoding the file. */
export function rangedStream(source: ReadableStream<Uint8Array>, range: ByteRange): ReadableStream<Uint8Array> {
  const reader = source.getReader();
  let offset = 0;
  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) { controller.close(); return; }
          const first = offset;
          offset += value.byteLength;
          if (offset <= range.start) continue;
          const start = Math.max(0, range.start - first);
          const end = Math.min(value.byteLength, range.end + 1 - first);
          if (end > start) controller.enqueue(value.subarray(start, end));
          if (offset > range.end) {
            controller.close();
            await reader.cancel();
          }
          return;
        }
      } catch (error) { controller.error(error); }
    },
    cancel(reason) { return reader.cancel(reason); },
  });
}

async function serveFile(c: Context<AppEnv>, file: MediaFile, key: string, filename: string): Promise<Response> {
  const headers = new Headers({
    'Content-Type': file.media_type, 'Accept-Ranges': 'bytes', 'Cache-Control': 'private, no-store',
    'X-Content-Type-Options': 'nosniff', 'Content-Disposition': `inline; filename="${filename.replace(/[^a-zA-Z0-9_.-]/g, '')}"`,
  });
  let range: ByteRange | null;
  try { range = parseByteRange(c.req.header('Range'), file.size); }
  catch { headers.set('Content-Range', `bytes */${file.size}`); return new Response(null, { status: 416, headers }); }
  const size = range ? range.end - range.start + 1 : file.size;
  headers.set('Content-Length', String(size));
  if (range) headers.set('Content-Range', `bytes ${range.start}-${range.end}/${file.size}`);
  if (c.req.method === 'HEAD') return new Response(null, { status: range ? 206 : 200, headers });
  const object = await c.env.MEDIA.getWithMetadata<MediaMeta>(key, { type: 'stream', cacheTtl: 60 });
  if (!object.value) return c.json({ detail: 'O arquivo está se propagando na rede. Tente novamente em alguns segundos.' }, 503, { 'Retry-After': '5' });
  const body = range ? rangedStream(object.value, range) : object.value;
  return new Response(body, { status: range ? 206 : 200, headers });
}

mediaRouter.on(['GET', 'HEAD'], '/api/posts/:id/video', async c => {
  const user = requireUser(c);
  const post = await one<Post>(c.env, 'SELECT * FROM posts WHERE id=? AND user_id=?', [c.req.param('id'), user.id]);
  if (!post?.output_path) apiError(404, 'O vídeo ainda não está pronto.');
  const file = await one<MediaFile>(c.env, "SELECT * FROM media_files WHERE id=? AND user_id=? AND kind='video' AND complete=1", [post.output_path, user.id]);
  if (!file) apiError(404, 'Vídeo não encontrado.');
  return serveFile(c, file, `video:${post.id}`, `${post.id}.mp4`);
});
mediaRouter.on(['GET', 'HEAD'], '/media/:token.mp4', async c => {
  const token = c.req.param('token');
  if (!token || token.length > 128) apiError(404, 'Vídeo não encontrado.');
  const post = await one<Post>(c.env, 'SELECT * FROM posts WHERE public_token=? AND output_path IS NOT NULL', [token]);
  if (!post) apiError(404, 'Vídeo não encontrado.');
  const file = await one<MediaFile>(c.env, "SELECT * FROM media_files WHERE id=? AND user_id=? AND kind='video' AND complete=1", [post.output_path, post.user_id]);
  if (!file) apiError(404, 'Vídeo não encontrado.');
  return serveFile(c, file, `video:${post.id}`, `${post.id}.mp4`);
});

async function authorizeRender(c: Context<AppEnv>): Promise<{ job: RenderJob; token: string }> {
  const token = c.req.header('Authorization')?.replace(/^Bearer /, '') || '';
  if (!token || token.length > 128) apiError(401, 'Autorização de renderização inválida.');
  const job = await one<RenderJob>(c.env, "SELECT id,user_id,status,token_hash,expires_at FROM render_jobs WHERE id=? AND status='running' AND expires_at>?", [c.req.param('id'), now()]);
  if (!job?.token_hash || !(await verify(c.env, `render:${job.id}:${token}`, job.token_hash))) apiError(401, 'A autorização de renderização expirou.');
  return { job, token };
}

mediaRouter.get('/internal/render/:id/page', async c => {
  await authorizeRender(c);
  // No untrusted HTML is interpolated here. User text is passed through CDP as data.
  return c.html('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Renderizador AUTOPOSTS</title><body><script src="/render-client.js"></script></body></html>');
});
mediaRouter.get('/internal/render/:id/asset/:assetId', async c => {
  const { job } = await authorizeRender(c);
  const asset = await one<{ id: string; media_type: string; size: number }>(c.env, 'SELECT id,media_type,size FROM assets WHERE id=? AND user_id=?', [c.req.param('assetId'), job.user_id]);
  if (!asset) apiError(404, 'Uma imagem não está disponível na biblioteca desta conta.');
  const value = await c.env.MEDIA.get(`image:${asset.id}`, { type: 'stream', cacheTtl: 60 });
  if (!value) apiError(404, 'Uma imagem ainda não está disponível. Tente renderizar novamente depois.');
  return new Response(value, { headers: { 'Content-Type': asset.media_type, 'Content-Length': String(asset.size), 'Cache-Control': 'private, no-store' } });
});

export function isMp4Header(bytes: Uint8Array): boolean {
  if (bytes.byteLength < 12) return false;
  const size = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength).getUint32(0);
  return size >= 12 && size <= VIDEO_MAX_BYTES && bytes[4] === 102 && bytes[5] === 116 && bytes[6] === 121 && bytes[7] === 112;
}

async function reserveStorage(env: Env, job: RenderJob, size: number): Promise<void> {
  const result = await exec(env, `INSERT INTO media_files(id,user_id,kind,media_type,size,complete,created_at)
    SELECT ?,?,'video','video/mp4',?,0,? WHERE
    COALESCE((SELECT SUM(size) FROM media_files),0)-COALESCE((SELECT size FROM media_files WHERE id=? AND user_id=?),0)+?<=?
    AND COALESCE((SELECT SUM(size) FROM media_files WHERE user_id=?),0)-COALESCE((SELECT size FROM media_files WHERE id=? AND user_id=?),0)+?<=?
    ON CONFLICT(id) DO UPDATE SET size=excluded.size,complete=0,media_type=excluded.media_type WHERE media_files.user_id=excluded.user_id`,
  [job.id, job.user_id, size, now(), job.id, job.user_id, size, GLOBAL_STORAGE_BYTES,
    job.user_id, job.id, job.user_id, size, USER_STORAGE_BYTES]);
  if (!result.meta.changes) apiError(429, 'O armazenamento gratuito está cheio. Exclua vídeos antes de gerar novos.');
}

mediaRouter.post('/internal/render/:id/upload', async c => {
  const { job } = await authorizeRender(c);
  const size = Number(c.req.header('X-Media-Size'));
  const contentLength = c.req.header('Content-Length');
  if (!Number.isInteger(size) || size < 12 || size > VIDEO_MAX_BYTES || (contentLength && Number(contentLength) !== size)) apiError(413, 'O vídeo deve ter no máximo 4 MB e tamanho válido.');
  if (!c.req.header('Content-Type')?.startsWith('video/mp4') || !c.req.raw.body) apiError(415, 'Envie um vídeo MP4 válido.');
  const reader = c.req.raw.body.getReader();
  const first = await reader.read();
  if (first.done || !isMp4Header(first.value)) { await reader.cancel(); apiError(415, 'O arquivo gerado não é um MP4 válido.'); }
  const day = now().slice(0, 10);
  const upload = await one<{ count: number }>(c.env, `INSERT INTO global_usage(day,kind,count) VALUES(?,'uploads',1)
    ON CONFLICT(day,kind) DO UPDATE SET count=count+1 WHERE count<100 RETURNING count`, [day]);
  if (!upload) { await reader.cancel(); apiError(429, 'A cota diária de uploads foi atingida. Tente no próximo dia UTC.'); }
  try { await reserveStorage(c.env, job, size); }
  catch (error) { await reader.cancel(); throw error; }
  // FixedLengthStream preserves a known byte length for KV.put and enforces the
  // declared size without concatenating the MP4 in the Worker isolate.
  const fixed = new FixedLengthStream(size);
  const writer = fixed.writable.getWriter();
  const pump = (async () => {
    try {
      await writer.write(first.value);
      while (true) { const chunk = await reader.read(); if (chunk.done) break; await writer.write(chunk.value); }
      await writer.close();
    } catch (error) { await writer.abort(error).catch(() => {}); await reader.cancel().catch(() => {}); throw error; }
  })();
  try {
    await Promise.all([pump, c.env.MEDIA.put(`video:${job.id}`, fixed.readable, { metadata: { size, media_type: 'video/mp4' } })]);
    const stamp = now();
    const readyAt = new Date(Date.now() + 90_000).toISOString();
    const results = await c.env.DB.batch([
      c.env.DB.prepare("UPDATE media_files SET complete=1 WHERE id=? AND user_id=?").bind(job.id, job.user_id),
      c.env.DB.prepare("UPDATE posts SET status='ready',output_path=?,ready_at=?,next_attempt_at=?,last_error=NULL,updated_at=? WHERE id=? AND user_id=? AND status='rendering' AND EXISTS(SELECT 1 FROM render_jobs WHERE id=? AND status='running' AND expires_at>?)").bind(job.id, readyAt, readyAt, stamp, job.id, job.user_id, job.id, stamp),
      c.env.DB.prepare("UPDATE render_jobs SET status='complete',finished_at=?,token_hash=NULL WHERE id=? AND status='running' AND EXISTS(SELECT 1 FROM posts WHERE id=? AND status='ready')").bind(stamp, job.id, job.id),
    ]);
    if (!results[1].meta.changes) apiError(409, 'O trabalho foi cancelado ou expirou durante o envio.');
    return c.json({ ok: true, ready_at: readyAt });
  } catch {
    await exec(c.env, 'DELETE FROM media_files WHERE id=? AND user_id=? AND complete=0', [job.id, job.user_id]);
    apiError(502, 'Não foi possível guardar o vídeo. A renderização não iniciou uma publicação.');
  }
});

async function failJob(env: Env, id: string, message: string): Promise<void> {
  const stamp = now();
  await env.DB.batch([
    env.DB.prepare("UPDATE render_jobs SET status='failed',error=?,finished_at=?,token_hash=NULL WHERE id=? AND status='running'").bind(message, stamp, id),
    env.DB.prepare("UPDATE posts SET status='failed',last_error=?,updated_at=? WHERE id=? AND status='rendering'").bind(message, stamp, id),
  ]);
}

async function timeout<T>(promise: Promise<T>, milliseconds: number, message: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try { return await Promise.race([promise, new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error(message)), milliseconds); })]); }
  finally { if (timer) clearTimeout(timer); }
}

/** One globally leased Browser Run job per minute, max eight/day across tenants. */
export async function processRender(env: Env, origin: string): Promise<void> {
  const stamp = now();
  const stale = await all<{ id: string }>(env, "SELECT id FROM render_jobs WHERE status='running' AND expires_at<=? LIMIT 8", [stamp]);
  for (const job of stale) await failJob(env, job.id, 'A renderização foi interrompida. Gere o vídeo novamente; nenhuma publicação foi iniciada.');
  await exec(env, `INSERT INTO render_jobs(id,user_id,status) SELECT p.id,p.user_id,'queued' FROM posts p
    WHERE p.status='rendering' AND NOT EXISTS(SELECT 1 FROM render_jobs r WHERE r.id=p.id) LIMIT 1`);
  const candidate = await one<RenderJob>(env, "SELECT r.id,r.user_id,r.status,r.token_hash,r.expires_at FROM render_jobs r JOIN posts p ON p.id=r.id WHERE r.status='queued' AND p.status='rendering' ORDER BY p.created_at LIMIT 1");
  if (!candidate) return;
  if (!env.BROWSER || !origin) {
    await exec(env, "UPDATE posts SET last_error=? WHERE id=? AND status='rendering'", ['Configure Browser Run e a origem pública para gerar o vídeo.', candidate.id]);
    return;
  }
  const current = Date.now();
  const lease = await one<{ value: string }>(env, `INSERT INTO app_config(key,value) VALUES('render_launch_lease',?)
    ON CONFLICT(key) DO UPDATE SET value=excluded.value WHERE CAST(app_config.value AS INTEGER)<=? RETURNING value`, [String(current + 60_000), current]);
  if (!lease) return;
  const day = stamp.slice(0, 10);
  const budget = await one<{ count: number }>(env, `INSERT INTO global_usage(day,kind,count) VALUES(?,'browser_seconds',?)
    ON CONFLICT(day,kind) DO UPDATE SET count=count+excluded.count WHERE count+excluded.count<=? RETURNING count`, [day, RENDER_SECONDS_RESERVED, MAX_RENDERS_DAILY * RENDER_SECONDS_RESERVED]);
  if (!budget) {
    await exec(env, "UPDATE posts SET last_error=? WHERE id=? AND status='rendering'", ['A cota diária gratuita de vídeo foi atingida. A fila continua no próximo dia UTC.', candidate.id]);
    return;
  }
  await exec(env, "INSERT INTO global_usage(day,kind,count) VALUES(?,'browser',1) ON CONFLICT(day,kind) DO UPDATE SET count=count+1", [day]);
  const token = crypto.randomUUID() + crypto.randomUUID();
  const signature = await sign(env, `render:${candidate.id}:${token}`);
  const claimed = await exec(env, "UPDATE render_jobs SET status='running',started_at=?,expires_at=?,token_hash=?,error=NULL WHERE id=? AND status='queued'", [stamp, new Date(current + 60_000).toISOString(), signature, candidate.id]);
  if (!claimed.meta.changes) return;
  let browser: Awaited<ReturnType<typeof puppeteer.launch>> | undefined;
  let deadlineExpired = false;
  const task = (async () => {
    const acquired = await puppeteer.launch(env.BROWSER);
    browser = acquired;
    if (deadlineExpired) { await browser.close(); return; }
    const page = await browser.newPage();
    await page.setExtraHTTPHeaders({ Authorization: `Bearer ${token}` });
    await page.goto(new URL(`/internal/render/${candidate.id}/page`, origin).href, { waitUntil: 'load', timeout: 12_000 });
    const post = await one<Post>(env, 'SELECT * FROM posts WHERE id=? AND user_id=?', [candidate.id, candidate.user_id]);
    if (!post) throw new Error('O vídeo foi removido.');
    const scenes = JSON.parse(post.scenes) as Scene[];
    const config = {
      title: post.title, duration: post.duration, theme: post.theme, token,
      scenes: scenes.map(scene => ({ text: scene.text, image_url: scene.asset_id ? `/internal/render/${post.id}/asset/${encodeURIComponent(scene.asset_id)}` : null })),
      upload_url: `/internal/render/${post.id}/upload`,
    };
    await page.evaluate(async value => {
      const render = (globalThis as unknown as { renderAutoPosts?: (input: unknown) => Promise<unknown> }).renderAutoPosts;
      if (!render) throw new Error('O renderizador não está disponível nos assets do deploy.');
      return render(value);
    }, config);
    const finished = await one<{ status: string }>(env, 'SELECT status FROM render_jobs WHERE id=?', [candidate.id]);
    if (finished?.status !== 'complete') throw new Error('O arquivo não foi confirmado no armazenamento.');
  })();
  try { await timeout(task, 43_000, 'A geração excedeu o tempo permitido no plano gratuito.'); }
  catch (error) {
    deadlineExpired = true;
    const text = error instanceof Error ? error.message : '';
    // Never expose raw provider URLs or headers. Only intentional, fixed messages
    // and the remote renderer's codec diagnosis are safe for the customer.
    const message = /MP4\/H\.264|H\.264/.test(text)
      ? 'O navegador da Cloudflare não oferece a codificação MP4/H.264 necessária. Nenhuma publicação foi iniciada.'
      : 'Não foi possível concluir o vídeo dentro dos limites gratuitos. Verifique Browser Run e tente novamente depois.';
    await failJob(env, candidate.id, message);
  } finally {
    if (browser) {
      try { await timeout(browser.close(), 2000, 'Browser close timed out'); }
      catch {
        // A browser whose closure is uncertain may still consume idle seconds.
        // Freeze new launches for today, rather than silently exceeding the budget.
        await exec(env, "UPDATE global_usage SET count=600 WHERE day=? AND kind='browser_seconds'", [day]);
      }
    }
  }
}
