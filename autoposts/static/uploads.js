// Fit large photos before a serverless gateway receives the upload.
export async function preparePhoto(file, maximum=10*1024*1024) {
  if(file.size<=maximum)return file;
  if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>25*1024*1024)
    throw new Error('Envie uma foto JPEG, PNG ou WebP de até 25 MB.');
  if(typeof createImageBitmap!=='function')throw new Error(`Reduza a foto para até ${Math.floor(maximum/1024/1024)} MB antes de enviar.`);
  let image;
  try{
    image=await createImageBitmap(file,{imageOrientation:'from-image'});
    const scale=Math.min(1,2000/image.width,2000/image.height);
    const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(image.width*scale));canvas.height=Math.max(1,Math.round(image.height*scale));
    const context=canvas.getContext('2d');if(!context)throw new Error('canvas');
    context.fillStyle='#ffffff';context.fillRect(0,0,canvas.width,canvas.height);context.drawImage(image,0,0,canvas.width,canvas.height);
    for(const quality of [0.92,0.82,0.7]){
      const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',quality));
      if(blob&&blob.size<=maximum)return new File([blob],file.name.replace(/\.[^.]+$/,'')+'.jpg',{type:'image/jpeg'});
    }
  }catch{throw new Error('Não foi possível preparar esta foto. Envie outra imagem JPEG, PNG ou WebP.');}
  finally{image?.close();}
  throw new Error(`Reduza a foto para até ${Math.floor(maximum/1024/1024)} MB antes de enviar.`);
}
