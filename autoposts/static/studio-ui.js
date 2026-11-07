export function createStudioUI({state,api,e,icon,toast,render,refresh}) {
  const newDraft=()=>({title:'',prompt:'',caption:'',kind:'video',duration:30,asset_ids:[],voice_mode:'none',voice_id:'',visual_mode:'photos',company_name:'',color:'#7cdec3',auto_publish:true,account_id:'',publish_time:'09:00',timezone:'America/Sao_Paulo'});
  const draft=newDraft();
  let owner=null,pending=null,lastCreation=null,lastAutomatic=false;
  let generation=0;let voices=[],caps={},recorder=null,stream=null,chunks=[],timer=null,started=0,blob=null,preview=null,busy=false;
  const persist=()=>{
    if(!owner)return;
    try{for(const key of Object.keys(sessionStorage))if(key.startsWith('autoposts.studio.')&&key!=='autoposts.studio.'+owner)sessionStorage.removeItem(key);sessionStorage.setItem('autoposts.studio.'+owner,JSON.stringify({draft,pending,lastCreation,lastAutomatic}));}catch{}
  };
  const collect=()=>{
    const form=document.querySelector('#studio-form');if(!form)return;
    const data=new FormData(form);
    for(const key of ['title','prompt','caption','kind','voice_mode','voice_id','visual_mode','company_name','color','account_id','publish_time'])if(data.has(key))draft[key]=String(data.get(key));
    draft.duration=Number(data.get('duration')||30);draft.auto_publish=data.get('auto_publish')==='on';draft.asset_ids=data.getAll('photo').map(String);persist();
  };
  const load=async()=>{
    const user=state.session?.user?.id;if(!user)return;const current=generation;
    const [v,c]=await Promise.all([api('/api/voices'),api('/api/studio/config')]);
    if(current!==generation||state.session?.user?.id!==user)return;
    let restored=false;
    if(owner!==user){
      dispose(false);owner=user;
      try{
        const saved=JSON.parse(sessionStorage.getItem('autoposts.studio.'+owner)||'null');
        if(saved?.draft){
          for(const [key,value] of Object.entries(newDraft())){
            const item=saved.draft[key];
            if(Array.isArray(value)&&Array.isArray(item))draft[key]=item.filter(x=>typeof x==='string').slice(0,6);
            else if(typeof item===typeof value)draft[key]=item;
          }
          if(saved.pending&&typeof saved.pending.key==='string'&&typeof saved.pending.fingerprint==='string')pending=saved.pending;
          if(typeof saved.lastCreation==='string')lastCreation=saved.lastCreation;
          lastAutomatic=saved.lastAutomatic===true;restored=true;
        }
      }catch{}
    }else restored=true;
    voices=v.voices;state.voices=voices;caps=c;
    if(!restored&&c.voice_tts)draft.voice_mode='synthetic_female';
    persist();
  };
  const redraw=()=>{collect();render();};
  const stop=()=>{if(recorder?.state==='recording')recorder.stop();stream?.getTracks().forEach(t=>t.stop());clearTimeout(timer);};
  const dispose=(clearAll=true)=>{
    generation++;stop();chunks=[];stream=null;recorder=null;busy=false;
    if(preview)URL.revokeObjectURL(preview);preview=null;blob=null;voices=[];caps={};
    try{if(clearAll){for(const key of Object.keys(sessionStorage))if(key.startsWith('autoposts.studio.'))sessionStorage.removeItem(key);}else if(owner)sessionStorage.removeItem('autoposts.studio.'+owner);}catch{}
    owner=null;pending=null;lastCreation=null;lastAutomatic=false;Object.assign(draft,newDraft());
  };
  function progressView(){
    const post=state.posts.find(p=>p.id===lastCreation);if(!post)return '';
    const job=state.jobs.find(j=>j.post_id===post.id);
    const failed=post.status==='failed';let level=0,label='Pedido recebido';
    if(post.status==='rendering'){
      level=1;label=job?.attempts>0&&job.status==='pending'?'Nova tentativa automática programada':job?.status==='processing'?'Montando seu conteúdo':'Na fila de criação';
    }
    if(post.generation_status==='generating')label='Preparando o roteiro';
    if(post.status==='ready'){level=3;label='Pronto na sua biblioteca';}
    if(post.status==='scheduled'){level=3;label='Publicação agendada';}
    if(post.status==='publishing'){level=3;label='Enviando ao Instagram';}
    if(post.status==='published'){level=4;label='Publicado no Instagram';}
    if(post.media_deleted_at)label='Arquivo removido após o prazo de retenção';
    if(failed)label='A criação precisa de atenção';
    const steps=['Pedido recebido','Produção','Biblioteca',lastAutomatic?'Instagram':'Arquivo pronto'];
    return `<section class="panel creation-progress ${failed?'has-error':''}" aria-label="Progresso da última criação" data-status="${e(post.status)}"><div class="creation-progress-heading"><div><span class="eyebrow">SUA ÚLTIMA CRIAÇÃO</span><h2>${e(label)}</h2><p>${e(post.title)}</p></div><a href="#${lastAutomatic?'campaigns':'library'}" class="btn btn-secondary btn-small">${lastAutomatic?'Ver automação':'Ver biblioteca'} ${icon('arrow')}</a></div><ol class="creation-steps">${steps.map((step,i)=>`<li class="${i<level?'done':i===level?'current':''}"><span>${i<level?icon('check'):i+1}</span>${step}</li>`).join('')}</ol>${failed?`<p class="error-note">${e(post.last_error||'Confira a biblioteca para tentar novamente.')}</p>`:job?.next_attempt_at&&job.status==='pending'?`<p class="field-help">Nova tentativa: ${e(new Date(job.next_attempt_at).toLocaleString('pt-BR'))}. Você pode fechar esta página.</p>`:post.status==='scheduled'?'<p class="field-help">O servidor publicará automaticamente. O arquivo fica protegido até concluir ou cancelar o envio.</p>':post.video_url&&post.media_expires_at?`<p class="field-help">Arquivo disponível até ${e(new Date(post.media_expires_at).toLocaleString('pt-BR'))}, conforme a política de retenção.</p>`:'<p class="field-help">O processamento continua no servidor. Você pode fechar esta página.</p>'}</section>`;
  }
  const updateProgress=()=>{const container=document.querySelector('#studio-progress');if(container){const html=progressView();if(container.innerHTML!==html)container.innerHTML=html;}};
  function view(){const activate=state.publicConfig.production&&state.publicConfig.edition!=='demo'&&state.session?.user?.plan==='free';return `${activate?`<section class="panel activation-note"><div><span class="eyebrow">ATIVAÇÃO DO SEU ESTÚDIO</span><h2>${state.session.user.email_verified?'Escolha o Studio para ativar o piloto.':'Primeiro, confirme seu e-mail.'}</h2><p>Assinatura mensal de ${(Number(state.plans[0]?.price_cents||14999)/100).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})}. Depois da confirmação de pagamento, envie suas fotos e ative a campanha.</p></div><button class="btn btn-primary" data-action="${state.session.user.email_verified?'checkout':'verify-email'}" data-plan="studio">${state.session.user.email_verified?'Ativar assinatura':'Enviar confirmação de e-mail'}</button></section>`:''}<div class="studio-heading"><div><span class="eyebrow">SEU NEGÓCIO. SUA IDENTIDADE.</span><h1>Vamos criar algo seu.</h1><p>Fotos reais, palavras certas e uma voz que seus clientes conhecem.</p></div><div class="studio-heading-actions"><span class="studio-badge">${icon('shield')}Estúdio privado</span><button class="btn-link" type="button" data-action="clear-studio-draft">Limpar rascunho</button></div></div><div id="studio-progress" aria-live="polite">${progressView()}</div><div class="studio-layout"><div class="studio-editor"><form id="studio-form"><section class="panel studio-step"><div class="step-heading"><span class="step-digit">01</span><div><h2>Mostre o seu lugar</h2><p>Selecione até 6 fotos do seu estabelecimento.</p></div><label class="btn btn-secondary btn-small">${icon('plus')}Enviar<input id="studio-photos" type="file" accept="image/jpeg,image/png,image/webp" multiple hidden></label></div>${state.assets.length?`<div class="studio-photos">${state.assets.map(a=>`<label class="photo-choice"><input type="checkbox" name="photo" value="${e(a.id)}" ${draft.asset_ids.includes(a.id)?'checked':''}><img src="${e(a.url)}" alt="${e(a.original_name)}" loading="lazy"><span>${e(a.original_name)}</span><i>${icon('check')}</i></label>`).join('')}</div>`:`<label class="photo-drop" for="studio-photos"><span>${icon('image')}</span><strong>Seu espaço merece aparecer.</strong><p>Envie fotos da fachada, do ambiente ou dos seus produtos.</p><small>JPEG, PNG ou WebP · até 10 MB por foto</small></label>`}</section><section class="panel studio-step"><div class="step-heading"><span class="step-digit">02</span><div><h2>O que vamos contar?</h2><p>Escreva o que sua marca quer dizer.</p></div></div><div class="field"><label for="studio-title">Nome do conteúdo</label><input id="studio-title" name="title" required minlength="2" maxlength="120" value="${e(draft.title)}" placeholder="Ex.: Um convite para conhecer nosso café"></div><div class="field"><label for="studio-prompt">Roteiro e direção criativa <span class="optional">até 650 caracteres</span></label><textarea id="studio-prompt" name="prompt" rows="5" required minlength="3" maxlength="650" placeholder="Venha conhecer nosso espaço. Aqui, cada café é preparado com carinho. Estamos esperando você!">${e(draft.prompt)}</textarea><small class="field-help">Na voz clonada, este texto será narrado. A gravação original reproduz o áudio que você enviou.</small></div><div class="form-grid"><div class="field"><label for="studio-kind">Formato</label><select name="kind" id="studio-kind"><option value="video" ${draft.kind==='video'?'selected':''}>Vídeo vertical · Reels</option><option value="image" ${draft.kind==='image'?'selected':''}>Imagem · feed</option></select></div><div class="field"><label for="studio-duration">Duração</label><select id="studio-duration" name="duration">${[15,30,45,60].map(d=>`<option value="${d}" ${draft.duration===d?'selected':''}>${d} segundos</option>`).join('')}</select></div><div class="field"><label for="studio-company">Seu estabelecimento</label><input id="studio-company" name="company_name" maxlength="80" value="${e(draft.company_name)}" placeholder="Nome da sua marca"></div><div class="field"><label for="studio-color">Cor da marca</label><input id="studio-color" type="color" name="color" value="${e(draft.color)}"></div></div><details><summary>Legenda e variação de imagem</summary><div class="field mt-20"><label>Legenda do Instagram<textarea name="caption" maxlength="2200" rows="3" placeholder="Se deixar vazio, usaremos o texto do roteiro.">${e(draft.caption)}</textarea></label></div><label class="field">Tratamento visual<select name="visual_mode"><option value="photos" ${draft.visual_mode==='photos'?'selected':''}>Fotos reais, com sua identidade visual</option><option value="variation" ${draft.visual_mode==='variation'?'selected':''} ${!caps.image_variation?'disabled':''}>Variação de imagem com IA local ${!caps.image_variation?'· indisponível':''}</option></select></label><p class="field-help">Variação por IA funciona em imagens e pode alterar detalhes. Revise antes de publicar. Vídeos usam montagem das fotos reais, sem inventar cenas do local.</p></details></section><section class="panel studio-step"><div class="step-heading"><span class="step-digit">03</span><div><h2>Uma voz que combina com a sua marca.</h2><p>Escolha a voz feminina ou masculina de IA, ou use uma gravação sua.</p></div><span class="badge">PRIVADO</span></div><div class="sample-voices"><label>Ouvir voz feminina<audio controls preload="metadata" src="/art/voice-female.wav"></audio></label><label>Ouvir voz masculina<audio controls preload="metadata" src="/art/voice-male.wav"></audio></label></div><div class="voice-options"><label class="field">Narração<select name="voice_mode" id="studio-voice-mode"><option value="synthetic_female" ${draft.voice_mode==='synthetic_female'?'selected':''} ${!caps.voice_tts?'disabled':''}>Voz feminina natural · Kokoro ${!caps.voice_tts?'· não configurado':''}</option><option value="synthetic_male" ${draft.voice_mode==='synthetic_male'?'selected':''} ${!caps.voice_tts?'disabled':''}>Voz masculina natural · Kokoro ${!caps.voice_tts?'· não configurado':''}</option><option value="none" ${draft.voice_mode==='none'?'selected':''}>Sem narração</option><option value="original" ${draft.voice_mode==='original'?'selected':''}>Usar minha gravação original</option><option value="cloned" ${draft.voice_mode==='cloned'?'selected':''} ${!caps.voice_cloning?'disabled':''}>Narrar o roteiro com minha voz por IA ${!caps.voice_cloning?'· processador não configurado':''}</option></select></label><label class="field own-voice-select" ${['original','cloned'].includes(draft.voice_mode)?'':'hidden'}>Minha gravação<select name="voice_id"><option value="">Selecione uma voz</option>${voices.map(v=>`<option value="${e(v.id)}" ${draft.voice_id===v.id?'selected':''}>${e(v.name)} · ${Math.round(v.duration)}s</option>`).join('')}</select></label></div><details class="own-voice-details" ${recorder?.state==='recording'||blob||['original','cloned'].includes(draft.voice_mode)?'open':''}><summary>Usar uma gravação minha (opcional)</summary><div class="voice-recorder"><span class="mic-symbol ${recorder?.state==='recording'?'recording':''}">${icon('activity')}</span><div><strong>${recorder?.state==='recording'?'Gravando sua voz…':'Uma voz. A sua.'}</strong><p>De 3 a 30 segundos. Gravação limitada a 25s no navegador.</p><div class="voice-wave" aria-hidden="true">${Array.from({length:30},(_,i)=>`<i style="--bar:${14+(i*13)%28}px"></i>`).join('')}</div></div><button class="btn btn-secondary" type="button" data-action="${recorder?.state==='recording'?'stop-voice':'record-voice'}">${recorder?.state==='recording'?'Parar gravação':'Gravar minha voz'}</button></div><div class="voice-upload-row"><label class="upload-link">Ou enviar um áudio<input id="voice-file" type="file" accept="audio/wav,audio/webm,audio/ogg,audio/mpeg,audio/mp4" hidden></label><span class="field-help">WAV, WebM, MP3, Ogg ou M4A · até 8 MB</span></div>${preview?`<div class="audio-preview"><audio controls src="${e(preview)}"></audio><span>Prévia da sua gravação</span></div>`:''}<div class="consent-box"><label><input type="checkbox" id="voice-consent"><span>Esta é a minha própria voz. Autorizo seu uso para narrar meus conteúdos e, quando disponível, a síntese por IA. Posso revogar essa autorização a qualquer momento.</span></label><button type="button" class="btn btn-secondary btn-small" data-action="save-voice" ${!blob?'disabled':''}>Salvar minha gravação</button></div>${voices.length?`<div class="saved-voices">${voices.map(v=>`<div><span>${icon('activity')} ${e(v.name)}</span><button class="btn-link" type="button" data-action="remove-voice" data-id="${e(v.id)}">Revogar e excluir</button></div>`).join('')}</div>`:''}<p class="field-help">Clonagem usa Chatterbox em CPU, se instalado pelo operador, e pode ser lenta. A qualidade varia com a amostra. Este estúdio não cria pessoas falando nem sincroniza lábios.</p></details></section><section class="panel studio-step autopilot-step"><div class="step-heading"><span class="step-digit">04</span><div><h2>Pronto para o piloto automático.</h2><p>Uma autorização agora. Sem aprovar cada post depois.</p></div></div><label class="autopilot-toggle"><input name="auto_publish" type="checkbox" ${draft.auto_publish?'checked':''}><span><strong>Ativar criação e publicação automáticas</strong><small>Autoriza gerar, montar, narrar e publicar na conta selecionada. A primeira criação começa agora; as próximas seguem a rotina diária. Você pode pausar em Automações.</small></span></label><div class="form-grid"><label class="field">Instagram profissional<select name="account_id"><option value="">Selecione uma conta conectada</option>${(state.dashboard?.accounts||[]).map(a=>`<option value="${e(a.id)}" ${draft.account_id===a.id?'selected':''}>@${e(a.platform_username)}</option>`).join('')}</select></label><label class="field">Horário diário · Brasília<input type="time" name="publish_time" value="${e(draft.publish_time)}"></label></div>${!state.dashboard?.accounts?.length?'<button type="button" class="btn btn-secondary" data-action="connect-instagram">Conectar meu Instagram</button>':''}<p class="field-help">Para apenas testar uma criação sem publicar, desmarque o piloto automático. Para escolher outros dias ou horários, ajuste a campanha em Automações.</p></section><div class="studio-submit"><p class="form-error" role="alert"></p><button class="btn btn-primary btn-large" type="submit" ${busy?'disabled':''}>${icon('spark')}${busy?'Preparando sua criação…':draft.auto_publish?'Ativar meu piloto automático':'Criar meu conteúdo'}${icon('arrow')}</button><p>Cada criação usa 1 crédito. Ativar o piloto autoriza publicações futuras.</p></div></form></div><aside class="studio-preview"><div class="preview-heading"><span class="eyebrow">DIREÇÃO CRIATIVA</span><span class="live-dot">Sua prévia</span></div><div class="phone-frame"><div class="phone-screen">${state.assets.find(a=>draft.asset_ids.includes(a.id))?`<img src="${e(state.assets.find(a=>draft.asset_ids.includes(a.id)).url)}" alt="Sua foto selecionada">`:`<div class="phone-placeholder">${icon('image')}<span>Sua próxima história<br>começa com uma foto.</span></div>`}<div class="phone-copy"><span>${e(draft.company_name||'SUA MARCA')}</span><h2>${e(draft.title||'Um lugar. Muitas histórias.')}</h2><p>${e((draft.prompt||'O seu negócio, do seu jeito.').slice(0,110))}</p></div><div class="phone-caption">${draft.voice_mode.startsWith('synthetic_')?'Voz de IA · português':draft.voice_mode==='cloned'?'Narração por IA':draft.voice_mode==='original'?'Sua gravação original':'Fotos reais · movimento e identidade'}</div></div></div><div class="preview-foot"><span>${icon('shield')}Seus arquivos são privados</span><p>Esta composição é uma prévia visual do editor. O resultado aparece na biblioteca após o processamento.</p><p>Arquivos gerados expiram após ${e(state.publicConfig.media_ttl_hours||10)} horas. Publicações pendentes são protegidas.</p></div></aside></div>`;}
  document.addEventListener('input',event=>{if(event.target.closest('#studio-form')){collect();const copy=document.querySelector('.phone-copy');if(copy){copy.querySelector('span').textContent=draft.company_name||'SUA MARCA';copy.querySelector('h2').textContent=draft.title||'Um lugar. Muitas histórias.';copy.querySelector('p').textContent=(draft.prompt||'O seu negócio, do seu jeito.').slice(0,110);}}});
  document.addEventListener('change',async event=>{
    const target=event.target,current=generation;
    if(target.closest('#studio-form'))collect();
    if(target.id==='voice-file'){
      const file=target.files?.[0];if(!file)return;
      if(file.size>8*1024*1024)return toast('O áudio deve ter no máximo 8 MB.',true);
      blob=file;if(preview)URL.revokeObjectURL(preview);preview=URL.createObjectURL(blob);redraw();
    }
    if(target.id==='studio-photos'){
      const files=[...target.files||[]];if(!files.length)return;
      if(files.length+draft.asset_ids.length>6)return toast('Selecione até seis fotos por criação.',true);
      target.disabled=true;
      try{for(const file of files){if(current!==generation)return;if(file.size>10*1024*1024)throw new Error('Cada foto deve ter no máximo 10 MB.');const form=new FormData();form.append('file',file);const result=await api('/api/assets',{method:'POST',body:form});if(current!==generation)return;draft.asset_ids.push(result.asset.id);persist();}await refresh();if(current!==generation)return;render();toast('Fotos adicionadas ao seu estúdio.');}catch(err){if(current===generation)toast(err.message,true);}finally{target.disabled=false;}
    }
    if(target.name==='photo'){if(draft.asset_ids.length>6){target.checked=false;collect();toast('Use no máximo seis fotos.',true);}render();}
    if(target.name==='voice_mode'||target.name==='auto_publish')render();
    if(target.name==='kind'){if(draft.kind==='image'){draft.voice_mode='none';}persist();render();}
  });
  document.addEventListener('click',async event=>{const button=event.target.closest('[data-action]');if(!button)return;const action=button.dataset.action;
    if(!['record-voice','stop-voice','save-voice','remove-voice','clear-studio-draft'].includes(action))return;
    event.preventDefault();collect();const actionGeneration=generation;
    try{
      if(action==='clear-studio-draft'){if(busy)return;if(!window.confirm('Limpar o rascunho deste navegador? Conteúdos e campanhas já criados continuam salvos.'))return;generation++;stop();recorder=null;stream=null;chunks=[];blob=null;if(preview)URL.revokeObjectURL(preview);preview=null;pending=null;Object.assign(draft,newDraft());if(caps.voice_tts)draft.voice_mode='synthetic_female';persist();render();return;}
      if(action==='record-voice'){
        if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder)throw new Error('Gravação exige HTTPS e um navegador compatível. Você também pode enviar um áudio.');
        const current=generation;stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true},video:false});
        if(current!==generation||!state.session?.user){stream.getTracks().forEach(t=>t.stop());return;}const mime=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(t=>MediaRecorder.isTypeSupported(t));
        recorder=new MediaRecorder(stream,mime?{mimeType:mime}:undefined);chunks=[];started=Date.now();
        recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
        recorder.onstop=()=>{if(current!==generation)return;stream?.getTracks().forEach(t=>t.stop());clearTimeout(timer);if(Date.now()-started<3000){toast('Grave pelo menos três segundos.',true);recorder=null;render();return;}blob=new Blob(chunks,{type:recorder.mimeType});if(preview)URL.revokeObjectURL(preview);preview=URL.createObjectURL(blob);recorder=null;if(state.page==='studio')render();};
        recorder.start();timer=setTimeout(stop,25000);render();
      }
      if(action==='stop-voice')stop();
      if(action==='save-voice'){
        if(!blob)throw new Error('Grave ou envie sua voz primeiro.');
        if(!document.querySelector('#voice-consent')?.checked)throw new Error('Confirme a autorização de uso da sua própria voz.');
        button.disabled=true;const data=new FormData();data.append('file',blob,'minha-voz');data.append('name','Minha voz');data.append('consent','true');
        const result=await api('/api/voices',{method:'POST',body:data});if(actionGeneration!==generation)return;draft.voice_id=result.voice.id;draft.voice_mode='original';blob=null;if(preview)URL.revokeObjectURL(preview);preview=null;await load();render();toast('Gravação salva com autorização.');
      }
      if(action==='remove-voice'){
        if(!window.confirm('Revogar esta voz e excluir a amostra? Novas gerações com ela serão bloqueadas.'))return;
        await api('/api/voices/'+button.dataset.id,{method:'DELETE'});if(actionGeneration!==generation)return;if(draft.voice_id===button.dataset.id){draft.voice_id='';draft.voice_mode='none';}await load();render();toast('Autorização revogada e exclusão solicitada.');
      }
    }catch(err){if(actionGeneration!==generation)return;stop();toast(err.name==='NotAllowedError'?'Permita o microfone ou envie um arquivo de áudio.':err.message,true);button.disabled=false;}
  });
  document.addEventListener('submit',async event=>{
    if(event.target.id!=='studio-form')return;event.preventDefault();event.stopImmediatePropagation();if(busy)return;
    collect();const form=event.target,current=generation;const error=form.querySelector('.form-error');error.classList.remove('visible');
    try{
      if(!draft.asset_ids.length)throw new Error('Escolha pelo menos uma foto.');
      if(draft.kind==='image'&&draft.voice_mode!=='none')throw new Error('Imagens não possuem narração.');
      if(draft.auto_publish&&!draft.account_id)throw new Error('Conecte e selecione o Instagram para ativar o piloto automático.');
      const body={...draft,title:draft.title.trim(),prompt:draft.prompt.trim(),voice_id:draft.voice_id||null,account_id:draft.account_id||null};
      const fingerprint=JSON.stringify(body);
      if(!pending||pending.fingerprint!==fingerprint)pending={key:crypto.randomUUID(),fingerprint};
      busy=true;persist();form.querySelector('[type=submit]').disabled=true;
      const result=await api('/api/studio',{method:'POST',headers:{'Idempotency-Key':pending.key},body});
      if(current!==generation)return;
      pending=null;lastCreation=result.post.id;lastAutomatic=!!result.automated;persist();
      state.posts=[result.post,...state.posts.filter(p=>p.id!==result.post.id)];
      toast(lastAutomatic?'Piloto automático ativado. Acompanhe as criações e publicações.':'Criação enfileirada. Acompanhe o resultado na biblioteca.');
      location.hash=lastAutomatic?'campaigns':'library';await refresh();
    }catch(err){if(current===generation){error.textContent=err.message;error.classList.add('visible');if(err.status===410){pending=null;persist();}}}
    finally{if(current===generation){busy=false;form.querySelector('[type=submit]').disabled=false;}}
  },true);
  return {view,load,dispose,updateProgress,isRecording:()=>recorder?.state==='recording',leave:()=>{collect();if(recorder)stop();}};
}
