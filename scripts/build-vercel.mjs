import {cp,mkdir,rm,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {bootstrap} from '../web/config.mjs';
export async function buildSite(output=path.join(fileURLToPath(new URL('..',import.meta.url)),'dist'),env=process.env){
  await rm(output,{recursive:true,force:true});await mkdir(output,{recursive:true});
  await cp(new URL('../autoposts/static/',import.meta.url),output,{recursive:true});
  await writeFile(path.join(output,'site-config.json'),JSON.stringify(bootstrap(env)));
  // Valid 16x16 ICO: no Python, Pillow or external service needed at build time.
  const icon=Buffer.alloc(6+16+40+16*16*4+16*4);
  icon.writeUInt16LE(1,2);icon.writeUInt16LE(1,4);icon[6]=16;icon[7]=16;
  icon.writeUInt16LE(1,10);icon.writeUInt16LE(32,12);icon.writeUInt32LE(icon.length-22,14);icon.writeUInt32LE(22,18);
  icon.writeUInt32LE(40,22);icon.writeInt32LE(16,26);icon.writeInt32LE(32,30);icon.writeUInt16LE(1,34);icon.writeUInt16LE(32,36);
  for(let y=0;y<16;y++)for(let x=0;x<16;x++){const i=62+(y*16+x)*4;const bolt=x>=6&&x<=9&&y>=3&&y<=12;icon.set(bolt?[21,19,11,255]:[195,222,124,255],i);}
  await writeFile(path.join(output,'favicon.ico'),icon);
  console.log('Vercel static build ready: index, assets, favicon and public bootstrap; no private environment or backend URL exported.');
  return output;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))await buildSite();
