import {state,$,esc,fmt,date,time,parseTime,icon,api,toast,busy,sourceTag,empty,errorPanel,loading,safeURL,showDialog,dialogHeader,highlight} from './ui.js';
import {refreshStats} from './app.js';

export async function saveMoment(id,button){
 const done=button?busy(button,'Saving…'):()=>{};
 try{const clip=await api('/clips',{method:'POST',body:{passage_id:id}});await refreshStats();toast('Moment saved to your clip desk');return clip;}catch(error){toast(error.message,true);}finally{done();}
}

function preview(p){
 if(p.has_render)return `<video class="clip-video ${p.format==='9:16'?'portrait':p.format==='1:1'?'square':''}" controls preload="metadata" src="/api/clips/${p.id}/video" aria-label="Rendered clip preview"></video>`;
 if(p.asset_id)return `<video class="source-video" controls preload="metadata" src="/api/media/${p.asset_id}#t=${p.start},${p.end}" aria-label="Source video preview"></video>`;
 if(p.youtube_id)return `<div class="source-preview" id="source-preview"><span class="preview-label">ORIGINAL EPISODE</span><button class="play-circle" id="load-youtube" aria-label="Load YouTube source preview">${icon('play')}</button><span>${time(p.start)} <span class="muted-light">/ ${time(p.duration)}</span></span><p>Preview the source on YouTube</p></div>`;
 return `<div class="source-preview audio-preview"><span class="preview-label">PODCAST TRANSCRIPT</span>${icon('file')}<h3>Start with the story.</h3><p>This passage uses the podcast's timeline.<br>Add the matching video to prepare a cut.</p><a class="btn on-dark" href="${safeURL(p.source_url)}" target="_blank" rel="noopener noreferrer">Open original episode ${icon('arrow')}</a></div>`;
}

function wirePreview(p){
 $('#load-youtube')?.addEventListener('click',()=>{
  const el=$('#source-preview');
  el.innerHTML=`<iframe title="Original episode preview" src="https://www.youtube-nocookie.com/embed/${p.youtube_id}?start=${Math.floor(p.start)}&end=${Math.ceil(p.end)}&autoplay=1&rel=0" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen referrerpolicy="no-referrer"></iframe>`;
 });
}

export async function openPassage(id){
 showDialog(dialogHeader('ARCHIVE MOMENT','A little more context')+loading());
 try{
  const data=await api(`/passages/${id}`),p=data.passage;
  showDialog(dialogHeader('ARCHIVE MOMENT',p.title)+`<div class="drawer-body">${preview(p)}<div class="drawer-meta">${sourceTag(p)}<span>${date(p.published)}</span><span>${time(p.start)}–${time(p.end)}</span></div><div class="notice">${icon('clock')}<span>These are paragraph boundaries. Confirm the exact start and finish against your source video before rendering.</span></div><div class="detail-quote">“${esc(p.text)}”</div><div class="drawer-section"><h3>Around this moment</h3><div class="context-list">${data.context.map(c=>`<div class="context-item ${c.id===id?'current':''}"><span>${time(c.start)}</span><p>${esc(c.text)}</p></div>`).join('')}</div></div></div><div class="drawer-actions"><a class="btn secondary" href="${safeURL(p.source_link)}" target="_blank" rel="noopener noreferrer">Open source ↗</a><button class="btn primary" id="save-context">${icon('plus')} Save to clip desk</button></div>`);
  wirePreview(p);$('#save-context').onclick=async e=>{const clip=await saveMoment(id,e.currentTarget);if(clip)openClip(clip.id);};
 }catch(error){showDialog(dialogHeader('ARCHIVE MOMENT','Unable to open passage')+errorPanel(error));}
}

export async function openEpisode(id){
 showDialog(dialogHeader('EPISODE','Opening transcript…')+loading());
 try{
  const ep=await api(`/episodes/${encodeURIComponent(id)}`);let lastEnd=-1;
  const sequential=ep.passages.filter(p=>{if(p.start<lastEnd)return false;lastEnd=p.end;return true;});
  showDialog(dialogHeader('EPISODE',ep.title)+`<div class="drawer-body"><div class="drawer-meta">${sourceTag(ep)}<span>${date(ep.published)}</span><span>${time(ep.duration)}</span></div><div class="notice">${icon('book')}<span>${fmt(ep.word_count)} words · ${ep.speaker_labels?'Generic speaker labels from the source':'Speaker identities are not labeled in this transcript'}</span></div><form class="compact-search transcript-search" id="within-form">${icon('search')}<input id="within" placeholder="Find a word in this episode" aria-label="Find in transcript"><button class="btn subtle">Find</button></form><div class="transcript-list">${sequential.map(p=>`<article class="transcript-piece" data-text="${esc(p.text.toLowerCase())}"><div><span class="time-range">${time(p.start)}</span><button class="text-btn" data-read="${p.id}">Review moment ${icon('arrow')}</button></div><p>${esc(p.text)}</p></article>`).join('')}</div></div>`);
  document.querySelectorAll('[data-read]').forEach(b=>b.onclick=()=>openPassage(b.dataset.read));
  $('#within-form').onsubmit=e=>{e.preventDefault();const term=$('#within').value.toLowerCase().trim();let first=null;document.querySelectorAll('.transcript-piece').forEach(el=>{const matches=term&&el.dataset.text.includes(term);el.classList.toggle('found',Boolean(matches));if(matches&&!first)first=el;});if(first)first.scrollIntoView({behavior:'smooth',block:'center'});else if(term)toast('No matches in this episode');};
 }catch(error){showDialog(dialogHeader('EPISODE','Unable to open episode')+errorPanel(error));}
}

export async function clipDesk(){
 $('#main').innerHTML=`<section class="page-head"><div><span class="eyebrow">CLIP DESK</span><h1>From a good find to a great cut.</h1><p>Your saved moments, ready for a closer look.</p></div><a href="#discover" class="btn primary">${icon('plus')} Find a moment</a></section><div class="desk-tabs" role="group" aria-label="Clip status"><button class="selected" data-status="all">All moments <span id="all-count"></span></button><button data-status="draft">Drafts</button><button data-status="ready">Ready to review</button><button data-status="approved">Approved</button></div><div id="clip-list">${loading()}</div>`;
 try{
  state.clips=await api('/clips');$('#all-count').textContent=state.clips.length;
  function cards(status){const items=state.clips.filter(c=>status==='all'||c.status===status);$('#clip-list').innerHTML=items.length?`<div class="clip-grid">${items.map(c=>`<article class="clip-card"><button class="clip-poster" data-open="${c.id}" aria-label="Review ${esc(c.title)}"><span class="poster-format">${esc(c.format)}</span><span class="poster-play">${icon(c.has_render?'play':'clips')}</span><span class="poster-bottom"><span>${time(c.start)}–${time(c.end)}</span><span>${Math.round(c.end-c.start)}s</span></span></button><div class="clip-card-body"><div class="card-meta"><span class="pill ${c.status==='approved'?'success':''}">${esc(c.status==='rendering'?'Rendering…':c.status==='ready'?'Ready to review':c.status==='approved'?'Approved':'Draft')}</span><span>Revision ${c.revision}</span></div><h3>${esc(c.title)}</h3><p>${esc(c.transcript_text.slice(0,160))}…</p>${c.error?`<p class="danger small">${esc(c.error)}</p>`:''}<div class="clip-card-actions"><button class="text-btn" data-open="${c.id}">Open clip desk ${icon('arrow')}</button><a class="icon-button" href="/api/clips/${c.id}/export" aria-label="Export ${esc(c.title)}">${icon('download')}</a></div></div></article>`).join('')}</div>`:empty(status==='all'?'Your clip desk is ready':'No clips in this stage',status==='all'?'Save a moment from Discover to start shaping your next post.':'Clips move here as you render and approve them.',status==='all'?'<a class="btn primary" href="#discover">Explore the archive</a>':'');document.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>openClip(b.dataset.open));}
  document.querySelectorAll('[data-status]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-status]').forEach(x=>x.classList.toggle('selected',x===b));cards(b.dataset.status);});cards('all');
 }catch(error){$('#clip-list').innerHTML=errorPanel(error);}
}

export async function openClip(id){
 showDialog(dialogHeader('CLIP DESK','Opening moment…')+loading());
 try{
  let clip=await api(`/clips/${id}`);let dirty=false;
  const connections=await api('/connections');
  showDialog(dialogHeader('CLIP DESK',clip.title)+`<form id="clip-form"><div class="drawer-body"><div class="clip-stage"><span class="pill ${clip.approved?'success':''}">${esc(clip.status==='ready'?'Ready to review':clip.status)}</span><span class="small muted">Revision ${clip.revision} · ${clip.has_render?'Rendered video available':'Original source preview'}</span></div>${preview(clip)}<div class="drawer-meta"><a href="${safeURL(clip.source_link)}" target="_blank" rel="noopener noreferrer">${esc(clip.episode_title)} ↗</a></div>${clip.error?errorPanel(clip.error):''}<label>Clip title<input name="title" value="${esc(clip.title)}" required maxlength="250"></label><div class="trim-row"><label>Start time<input name="start" value="${time(clip.start)}" placeholder="0:00" required aria-describedby="time-help"></label><span class="trim-dash">—</span><label>End time<input name="end" value="${time(clip.end)}" placeholder="1:00" required></label><span class="duration-display" id="clip-duration">${Math.round(clip.end-clip.start)}s</span></div><p id="time-help" class="small muted">Use mm:ss or hh:mm:ss. Up to 180 seconds. Check the cut against your source video.</p><fieldset class="format-choices"><legend>Format</legend>${[['9:16','Portrait'],['1:1','Square'],['16:9','Landscape']].map(([v,label])=>`<label class="format-choice"><input type="radio" name="format" value="${v}" ${clip.format===v?'checked':''}><span class="format-symbol ${label.toLowerCase()}"></span><span>${label}<small>${v}</small></span></label>`).join('')}</fieldset><p class="small muted">Video is center-cropped to the selected format.</p><label>Post caption<textarea name="caption" rows="4" maxlength="5000">${esc(clip.caption)}</textarea></label><details class="source-passage"><summary>Read the saved passage</summary><p>${esc(clip.transcript_text)}</p><span class="small muted">The saved source text is unchanged by trim edits.</span></details><div class="media-section"><div class="section-heading"><h3>Source video</h3><span class="small muted">${clip.source_kind==='podcast'?'Podcast timing needs alignment':'Match this episode’s video'}</span></div><label class="sr-only" for="asset-choice">Source video</label><select name="asset_id" id="asset-choice"><option value="">Choose or upload a source video</option>${clip.assets.map(a=>`<option value="${a.id}" ${a.id===clip.asset_id?'selected':''}>${esc(a.name)} · ${time(a.duration)}</option>`).join('')}</select><div class="upload-row"><button class="btn secondary" type="button" id="upload-media">${icon('upload')} Upload video</button><span class="small muted">MP4, MOV, WebM, MKV, AVI</span><input id="media-file" type="file" accept=".mp4,.mov,.webm,.mkv,.avi" hidden></div><label class="checkbox-label"><input type="checkbox" name="alignment_confirmed" ${clip.alignment_confirmed?'checked':''}><span>I checked that these start and end times match the selected source video.</span></label></div>${clip.delivery?`<div class="notice"><span>Publisher delivery: <strong>${esc(clip.delivery.status)}</strong><br>${esc(clip.delivery.receipt||'Waiting for the connected workflow')}</span></div>`:''}<div id="clip-message" role="status"></div></div><div class="drawer-actions clip-actions"><button class="btn secondary" type="submit" id="save-clip">Save changes</button><button class="btn primary" type="button" id="render-clip" ${clip.status==='rendering'?'disabled':''}>${icon('clips')} ${clip.status==='rendering'?'Rendering…':'Render preview'}</button><div class="secondary-actions"><a href="/api/clips/${id}/export" class="text-btn" id="export-clip">${icon('download')} ${clip.has_render?'Export clip package':'Export editorial notes'}</a><button class="text-btn" type="button" id="approve-clip" ${!clip.has_render||clip.approved?'disabled':''}>${icon('check')} ${clip.approved?'Approved':'Approve cut'}</button>${connections.publisher?`<button class="text-btn" type="button" id="publish-clip" ${!clip.approved||clip.delivery?'disabled':''}>Send to publisher ${icon('arrow')}</button>`:''}</div></div></form>`);
  wirePreview(clip);
  const form=$('#clip-form');
  form.oninput=()=>{dirty=true;$('#approve-clip').disabled=true;if($('#publish-clip'))$('#publish-clip').disabled=true;const duration=parseTime(form.elements.end.value)-parseTime(form.elements.start.value);$('#clip-duration').textContent=Number.isFinite(duration)?`${Math.round(duration)}s`:'—';$('#clip-message').textContent='Unsaved changes';};
  form.elements.asset_id.onchange=()=>{form.elements.alignment_confirmed.checked=false;dirty=true;};
  async function save(){
   if(!dirty)return clip;
   if(!form.reportValidity())throw new Error('Complete the required clip fields');
   const values=Object.fromEntries(new FormData(form));const start=parseTime(values.start),end=parseTime(values.end);
   if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start||end-start>180)throw new Error('Choose a valid start and end time, up to 180 seconds apart');
   clip=await api(`/clips/${id}`,{method:'PATCH',body:{title:values.title,caption:values.caption,start,end,format:values.format,asset_id:values.asset_id||null,alignment_confirmed:form.elements.alignment_confirmed.checked,revision:clip.revision}});
   dirty=false;$('#clip-message').textContent='Changes saved. Render this revision to preview the updated cut.';return clip;
  }
  form.onsubmit=async e=>{e.preventDefault();const done=busy(e.submitter,'Saving…');try{await save();toast('Clip saved');await openClip(id);}catch(error){toast(error.message,true);}finally{done();}};
  $('#render-clip').onclick=async e=>{const done=busy(e.currentTarget,'Queuing render…');try{await save();const job=await api(`/clips/${id}/render`,{method:'POST'});toast('Render queued');await openClip(id);pollJob(job.job_id,id);}catch(error){toast(error.message,true);}finally{done();}};
  $('#approve-clip').onclick=async e=>{const done=busy(e.currentTarget,'Approving…');try{await api(`/clips/${id}/approve`,{method:'POST'});toast('This cut is approved');await openClip(id);}catch(error){toast(error.message,true);}finally{done();}};
  $('#publish-clip')?.addEventListener('click',async e=>{const done=busy(e.currentTarget,'Sending…');try{const job=await api(`/clips/${id}/publish`,{method:'POST'});toast('Publisher delivery queued');await openClip(id);pollJob(job.job_id,id);}catch(error){toast(error.message,true);}finally{done();}});
  $('#upload-media').onclick=()=>$('#media-file').click();
  if(clip.youtube_id){
   $('#upload-media').insertAdjacentHTML('afterend','<button class="btn secondary" type="button" id="fetch-video">'+icon('download')+' Fetch from YouTube</button>');
   $('#fetch-video').onclick=async e=>{const done=busy(e.currentTarget,'Queuing download…');try{await save();const job=await api(`/episodes/${encodeURIComponent(clip.episode_id)}/fetch-video`,{method:'POST'});toast('Source video download queued');pollJob(job.job_id,id);}catch(error){toast(error.message,true);}finally{done();}};
  }
  $('#media-file').onchange=async e=>{if(!e.target.files.length)return;const button=$('#upload-media'),done=busy(button,'Uploading video…');const data=new FormData();data.append('file',e.target.files[0]);try{const asset=await api(`/episodes/${encodeURIComponent(clip.episode_id)}/media`,{method:'POST',body:data});const option=document.createElement('option');option.value=asset.id;option.textContent=`${asset.name} · ${time(asset.duration)}`;form.elements.asset_id.append(option);form.elements.asset_id.value=asset.id;form.elements.alignment_confirmed.checked=false;dirty=true;$('#clip-message').textContent='Video uploaded. Save to preview it, then confirm the timing.';toast('Source video uploaded');}catch(error){toast(error.message,true);}finally{done();}};
  $('#export-clip').onclick=e=>{if(dirty){e.preventDefault();toast('Save your changes before exporting',true);}};
  if(clip.active_job)pollJob(clip.active_job,id);
 }catch(error){showDialog(dialogHeader('CLIP DESK','Unable to open clip')+errorPanel(error));}
}

const polling=new Set();
async function pollJob(jobId,clipId){
 if(polling.has(jobId))return;polling.add(jobId);
 try{for(let tries=0;tries<1000;tries++){await new Promise(r=>setTimeout(r,2000));const job=await api(`/jobs/${jobId}`);if(['done','failed'].includes(job.state)){toast(job.state==='done'?(job.kind==='render'?'Your clip is ready to review':job.kind==='fetch_media'?'Source video is ready. Select it and confirm timing.':'Sent to the connected publisher'):job.error,job.state==='failed');if($('#detail').open&&$('#clip-form'))await openClip(clipId);if(state.route==='clips')await clipDesk();break;}}}catch(error){toast(error.message,true);}finally{polling.delete(jobId);}
}
