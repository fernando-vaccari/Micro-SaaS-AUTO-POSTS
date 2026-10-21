let csrfToken = '';
export function setCsrf(value: string) { csrfToken = value; }
export class ApiError extends Error { constructor(message: string, public status: number) { super(message); this.name = 'ApiError'; } }
export async function request<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = options.method || 'GET';
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;
  if (options.body instanceof FormData) body = options.body;
  else if (options.body !== undefined) { body = JSON.stringify(options.body); headers['Content-Type'] = 'application/json'; }
  if (method !== 'GET' && method !== 'HEAD' && csrfToken) headers['X-CSRF-Token'] = csrfToken;
  let response: Response;
  try { response = await fetch(path, { method, headers, body, credentials: 'same-origin' }); }
  catch { throw new ApiError('Não foi possível acessar o servidor. Verifique sua conexão e tente novamente.', 0); }
  const data = await response.json().catch(() => ({})) as { detail?: unknown; error?: unknown };
  if (!response.ok) {
    const detail = data.detail ?? data.error;
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((item: { msg?: string; message?: string }) => item.msg || item.message || 'Campo inválido.').join(' ') : `Não foi possível concluir a solicitação (${response.status}).`;
    throw new ApiError(message, response.status);
  }
  return data as T;
}
export function errorText(error: unknown) { return error instanceof Error ? error.message : 'Não foi possível concluir. Tente novamente.'; }
export function date(value?: string | null, options: Intl.DateTimeFormatOptions = {}) { if (!value) return '—'; const d = new Date(value); return Number.isNaN(d.valueOf()) ? '—' : d.toLocaleString('pt-BR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', ...options }); }
export function bytes(size: number) { return size >= 1024 * 1024 ? `${(size / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(size / 1024)} KB`; }
export async function prepareImage(file: File): Promise<File> {
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) throw new Error('Envie uma imagem JPEG, PNG ou WEBP.');
  if (file.size > 10 * 1024 * 1024) throw new Error('Escolha uma imagem de até 10 MB para otimização.');
  const bitmap = await createImageBitmap(file).catch(() => { throw new Error('A imagem não pôde ser aberta. Escolha outro arquivo.'); });
  try {
    const scale = Math.min(1, 720 / bitmap.width, 1280 / bitmap.height);
    const canvas = document.createElement('canvas'); canvas.width = Math.max(1, Math.round(bitmap.width * scale)); canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const ctx = canvas.getContext('2d'); if (!ctx) throw new Error('Seu navegador não conseguiu preparar a imagem.');
    ctx.fillStyle = '#14141c'; ctx.fillRect(0, 0, canvas.width, canvas.height); ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    for (const quality of [0.9, 0.78, 0.64, 0.48]) {
      const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/jpeg', quality));
      if (blob && blob.size <= 512 * 1024) return new File([blob], `${file.name.replace(/\.[^.]+$/, '').slice(0, 100) || 'imagem'}.jpg`, { type: 'image/jpeg' });
    }
    throw new Error('Esta imagem ainda excede 512 KB após otimização. Escolha uma imagem menor.');
  } finally { bitmap.close(); }
}
