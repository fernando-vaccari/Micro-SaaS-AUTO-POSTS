// Local test adapter for the Vercel static output and standard Node handler.
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createGateway} from '../api/gateway.mjs';
const MIME={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.mjs':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json','.ico':'image/x-icon','.svg':'image/svg+xml','.wav':'audio/wav','.png':'image/png'};
export function createSiteServer({root=path.resolve('dist'),gateway=createGateway()}={}){
  return createServer(async(req,res)=>{
    res.setHeader('X-Content-Type-Options','nosniff');res.setHeader('Permissions-Policy','camera=(), microphone=(self), geolocation=()');
    const pathname=new URL(req.url,'http://localhost').pathname;
    if(/^\/(?:api(?:\/|$)|media(?:\/|$)|health$|privacy$|terms$|data-deletion$)/.test(pathname))return gateway(req,res);
    let file;
    try{const relative=['/','/login','/cadastro'].includes(pathname)?'/index.html':decodeURIComponent(pathname);file=path.resolve(root,'.'+relative);if(!file.startsWith(path.resolve(root)+path.sep))throw new Error();
      const data=await readFile(file);res.statusCode=200;res.setHeader('content-type',MIME[path.extname(file)]||'application/octet-stream');res.end(req.method==='HEAD'?undefined:data);
    }catch{res.statusCode=404;res.end('Not found');}
  });
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  let fetchImpl=globalThis.fetch;
  if(process.env.LOCAL_TEST_BACKEND){
    const target=new URL(process.env.LOCAL_TEST_BACKEND);
    if(process.env.NODE_ENV!=='test'||target.protocol!=='http:'||!['127.0.0.1','localhost'].includes(target.hostname))throw new Error('Local test backend must be loopback HTTP in NODE_ENV=test.');
    fetchImpl=(url,options)=>{const original=new URL(url);return fetch(target.origin+original.pathname+original.search,options);};
  }
  createSiteServer({gateway:createGateway({fetchImpl})}).listen(Number(process.env.PORT||8012),'127.0.0.1',()=>console.log('Local Vercel delivery test server ready.'));
}
