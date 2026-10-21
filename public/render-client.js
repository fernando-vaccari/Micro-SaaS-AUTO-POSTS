/* Executed by Cloudflare Browser Run, not by the Worker isolate. */
(function () {
  'use strict';
  const themes = {
    violet: ['#120e25', '#482763', '#b79aff'],
    ocean: ['#08212b', '#155970', '#76e3dd'],
    ember: ['#281512', '#713122', '#ffc195'],
  };

  function linesFor(ctx, text, width) {
    const lines = [];
    for (const paragraph of text.split('\n')) {
      let line = '';
      for (let word of paragraph.split(/\s+/).filter(Boolean)) {
        if (ctx.measureText(`${line} ${word}`.trim()).width <= width) {
          line = `${line} ${word}`.trim();
          continue;
        }
        if (line) lines.push(line);
        line = '';
        while (ctx.measureText(word).width > width && word.length > 1) {
          let take = word.length - 1;
          while (take > 1 && ctx.measureText(word.slice(0, take)).width > width) take--;
          lines.push(word.slice(0, take));
          word = word.slice(take);
        }
        line = word;
      }
      if (line || !paragraph) lines.push(line);
    }
    return lines;
  }

  function fit(ctx, text, width) {
    for (let size = 66; size >= 30; size -= 2) {
      ctx.font = `700 ${size}px Arial, sans-serif`;
      const lines = linesFor(ctx, text, width);
      if (lines.length * size * 1.3 <= 700) return { lines, size };
    }
    throw new Error('O texto não cabe no vídeo. Reduza ou divida as cenas.');
  }

  async function loadImage(scene, config) {
    if (!scene.image_url) return null;
    const imageUrl = new URL(scene.image_url, location.href);
    if (imageUrl.origin !== location.origin) throw new Error('A imagem precisa pertencer à biblioteca desta conta.');
    const response = await fetch(imageUrl.href, {
      headers: { Authorization: `Bearer ${config.token}` },
      signal: AbortSignal.timeout(6000),
    });
    if (!response.ok) throw new Error('Não foi possível carregar uma imagem da cena.');
    const blob = await response.blob();
    if (blob.size > 512 * 1024) throw new Error('A imagem excede o limite de 512 KB.');
    return createImageBitmap(blob);
  }

  window.renderAutoPosts = async function renderAutoPosts(config) {
    if (!config || !Array.isArray(config.scenes) || config.scenes.length < 1 || config.scenes.length > 6)
      throw new Error('O vídeo precisa ter de uma a seis cenas.');
    if (!Number.isInteger(config.duration) || config.duration < 6 || config.duration > 15)
      throw new Error('A duração precisa estar entre 6 e 15 segundos.');
    const candidates = [
      'video/mp4;codecs=avc1.42E01E',
      'video/mp4;codecs=avc1.42001E',
      'video/mp4;codecs=avc1.4D001F',
    ];
    const mimeType = candidates.find(type => window.MediaRecorder && MediaRecorder.isTypeSupported(type));
    if (!mimeType) throw new Error('O navegador da Cloudflare não oferece gravação MP4/H.264. Nenhum vídeo ou publicação foi criado.');
    const scenes = config.scenes.map(scene => ({ ...scene, text: String(scene.text || '').trim() }));
    if (scenes.some(scene => scene.text.length > 420 || (!scene.text && !scene.image_url)))
      throw new Error('Uma cena está vazia ou excede o limite de texto.');
    const images = await Promise.all(scenes.map(scene => loadImage(scene, config)));
    const canvas = document.createElement('canvas');
    canvas.width = 720;
    canvas.height = 1280;
    const ctx = canvas.getContext('2d', { alpha: false });
    if (!ctx || !canvas.captureStream) throw new Error('O navegador não oferece o renderizador necessário.');
    const palette = themes[config.theme] || themes.violet;
    const layouts = scenes.map(scene => fit(ctx, scene.text, 608));
    const draw = seconds => {
      const index = Math.min(scenes.length - 1, Math.floor(seconds / config.duration * scenes.length));
      const gradient = ctx.createLinearGradient(0, 0, 720, 1280);
      gradient.addColorStop(0, palette[1]);
      gradient.addColorStop(0.7, palette[0]);
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, 720, 1280);
      const photo = images[index];
      if (photo) {
        const scale = Math.max(720 / photo.width, 1280 / photo.height);
        ctx.drawImage(photo, (720 - photo.width * scale) / 2, (1280 - photo.height * scale) / 2,
          photo.width * scale, photo.height * scale);
        ctx.fillStyle = '#070812b8';
        ctx.fillRect(0, 0, 720, 1280);
      }
      ctx.fillStyle = palette[2];
      ctx.fillRect(56, 86, 32, 32);
      ctx.fillStyle = '#fff';
      ctx.font = '700 21px Arial, sans-serif';
      ctx.fillText('AUTOPOSTS', 104, 111);
      ctx.font = '18px Arial, sans-serif';
      ctx.fillText(`${String(index + 1).padStart(2, '0')} / ${String(scenes.length).padStart(2, '0')}`, 602, 110);
      const layout = layouts[index];
      ctx.font = `700 ${layout.size}px Arial, sans-serif`;
      const top = Math.max(300, (1280 - layout.lines.length * layout.size * 1.3) / 2 - 30);
      ctx.fillStyle = palette[2];
      ctx.fillRect(56, top - 52, 60, 6);
      ctx.fillStyle = '#fbfaff';
      layout.lines.forEach((line, lineIndex) => ctx.fillText(line, 56, top + lineIndex * layout.size * 1.3));
      ctx.font = '19px Arial, sans-serif';
      ctx.fillStyle = '#dad6e5';
      const title = String(config.title || '').slice(0, 120);
      linesFor(ctx, title, 608).slice(0, 2).forEach((line, i) => ctx.fillText(line, 56, 1104 + i * 28));
      const width = (608 - (scenes.length - 1) * 8) / scenes.length;
      for (let i = 0; i < scenes.length; i++) {
        ctx.fillStyle = i <= index ? palette[2] : '#62576f';
        ctx.fillRect(56 + i * (width + 8), 1190, width, 5);
      }
    };
    draw(0);
    const stream = canvas.captureStream(30);
    const chunks = [];
    let size = 0;
    let timer;
    let interval;
    let recorder;
    let blob;
    try {
      blob = await new Promise((resolve, reject) => {
        recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 900000 });
        const fail = error => { clearTimeout(timer); clearInterval(interval); reject(error); };
        recorder.ondataavailable = event => {
          if (!event.data.size) return;
          size += event.data.size;
          if (size > 4 * 1024 * 1024) {
            if (recorder.state !== 'inactive') recorder.stop();
            fail(new Error('O vídeo excedeu o limite gratuito de 4 MB.'));
            return;
          }
          chunks.push(event.data);
        };
        recorder.onerror = () => fail(new Error('Falha na codificação MP4/H.264.'));
        recorder.onstop = () => { clearTimeout(timer); clearInterval(interval); resolve(new Blob(chunks, { type: 'video/mp4' })); };
        const startedAt = performance.now();
        recorder.start(1000);
        interval = setInterval(() => draw((performance.now() - startedAt) / 1000), 1000 / 30);
        timer = setTimeout(() => { draw(config.duration); recorder.stop(); }, config.duration * 1000);
      });
      const header = new Uint8Array(await blob.slice(0, 64).arrayBuffer());
      if (header.length < 12 || String.fromCharCode(...header.slice(4, 8)) !== 'ftyp')
        throw new Error('O navegador retornou um arquivo que não é MP4. Nenhuma publicação foi iniciada.');
      if (config.downloadOnly) return { blob, size: blob.size, mime: blob.type, width: 720, height: 1280 };
      const target = new URL(config.upload_url, location.href);
      if (target.origin !== location.origin) throw new Error('Destino de mídia inválido.');
      const response = await fetch(target.href, {
        method: 'POST', headers: { Authorization: `Bearer ${config.token}`, 'Content-Type': 'video/mp4', 'X-Media-Size': String(blob.size) },
        body: blob, signal: AbortSignal.timeout(12000),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(typeof error?.detail === 'string' ? error.detail : 'Não foi possível guardar o vídeo.');
      }
      return { size: blob.size, mime: blob.type, width: 720, height: 1280 };
    } finally {
      clearTimeout(timer);
      clearInterval(interval);
      if (recorder && recorder.state !== 'inactive') recorder.stop();
      stream.getTracks().forEach(track => track.stop());
      images.forEach(image => image?.close());
    }
  };
})();
