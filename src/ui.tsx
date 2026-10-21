import { useEffect, useRef, type ReactNode } from 'react';

const paths: Record<string, ReactNode> = {
  bolt: <path d="m13 2-9 12h7l-1 8 10-13h-7l1-7Z" />,
  grid: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
  video: <><rect x="3" y="4" width="18" height="16" rx="3"/><path d="m10 8 6 4-6 4V8Z"/></>,
  image: <><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="2"/><path d="m3 17 5-5 4 4 4-6 5 7"/></>,
  spark: <path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  calendar: <><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18M8 15h2M14 15h2"/></>,
  check: <path d="m5 12 4 4L19 6"/>, plus: <path d="M12 5v14M5 12h14"/>, close: <path d="m6 6 12 12M6 18 18 6"/>,
  arrow: <path d="M4 12h16m-6-6 6 6-6 6"/>, chevron: <path d="m9 5 7 7-7 7"/>,
  logout: <><path d="M9 4H5v16h4M14 8l4 4-4 4m-4-4h8"/></>,
  shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/></>,
  info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/></>,
  link: <><path d="m10 13 4-4M8 16l-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0M16 8l1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0"/></>,
  instagram: <><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r=".8" fill="currentColor" stroke="none"/></>,
  menu: <path d="M4 6h16M4 12h16M4 18h16"/>, pause: <path d="M8 5v14M16 5v14" strokeWidth="4"/>, play: <path d="m7 4 14 8-14 8V4Z"/>,
  edit: <><path d="m15 4 5 5M4 20l5-1L21 7a3.5 3.5 0 0 0-5-5L4 14l-1 7 1-1Z"/></>, trash: <path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>,
  download: <path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>, refresh: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 6a8 8 0 0 1 13 3M5 15a8 8 0 0 0 13 3"/></>,
  eye: <><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></>,
  cloud: <path d="M6 18h12a5 5 0 0 0 .8-9.9A7 7 0 0 0 5.2 8.8 4.6 4.6 0 0 0 6 18Z"/>, activity: <path d="M2 12h5l3-8 4 16 3-8h5"/>,
};
export function Icon({ name, className = '' }: { name: string; className?: string }) { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className={`icon ${className}`} aria-hidden="true">{paths[name] || paths.spark}</svg>; }
export function Brand() { return <a className="brand" href="#overview"><span className="brand-mark"><Icon name="bolt"/></span>AUTOPOSTS<small>CLOUD</small></a>; }
const statuses: Record<string, string> = { draft: 'Rascunho', rendering: 'Gerando vídeo', ready: 'Pronto', scheduled: 'Agendado', publishing: 'Publicando', published: 'Publicado', failed: 'Falha', queued: 'Na fila', generating: 'Gerando roteiro', rendered: 'Vídeo pronto', cancelled: 'Cancelada', complete: 'Concluído', running: 'Processando' };
export function Badge({ status, children }: { status?: string; children?: ReactNode }) { return <span className={`badge ${['published', 'rendered', 'active', 'complete'].includes(status || '') ? 'green' : ['rendering', 'generating', 'publishing', 'running'].includes(status || '') ? 'purple' : status === 'scheduled' ? 'blue' : status === 'failed' ? 'red' : ''}`}>{children || statuses[status || ''] || status}</span>; }
export function Empty({ icon = 'bolt', title, text, children }: { icon?: string; title: string; text: string; children?: ReactNode }) { return <div className="empty-state"><span className="empty-icon"><Icon name={icon}/></span><h3>{title}</h3><p>{text}</p>{children}</div>; }
export function Notice({ children, danger = false }: { children: ReactNode; danger?: boolean }) { return <div role={danger ? 'alert' : undefined} className={`notice ${danger ? 'danger' : ''}`}><Icon name="info"/><div>{children}</div></div>; }
export function Modal({ title, subtitle, children, onClose }: { title: string; subtitle?: string; children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const el = ref.current; if (el && !el.open) el.showModal(); return () => { if (el?.open) el.close(); }; }, []);
  return <dialog ref={ref} className="modal" aria-labelledby="dialog-title" onCancel={e => { e.preventDefault(); onClose(); }} onClick={e => { if (e.target === e.currentTarget) { const r = e.currentTarget.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) onClose(); } }}><header className="modal-header"><div><h2 id="dialog-title">{title}</h2>{subtitle && <p>{subtitle}</p>}</div><button className="icon-btn" type="button" onClick={onClose} aria-label="Fechar janela"><Icon name="close"/></button></header>{children}</dialog>;
}
