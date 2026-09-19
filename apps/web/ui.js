export const state = {me:null,stats:null,route:'discover',query:'leadership',source:'',results:[],clips:[],opportunities:[],page:1};
export const $ = (selector,root=document)=>root.querySelector(selector);
export const esc = value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const safeURL = value=>{try{const u=new URL(value);return ['http:','https:'].includes(u.protocol)?u.href:'#';}catch{return '#';}};
export const fmt = value=>new Intl.NumberFormat('en-US').format(value||0);
export const date = value=>value?new Date(value+'T12:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'}):'Date unavailable';
export const time = value=>{const n=Math.max(0,Math.floor(value||0));return n>=3600?`${Math.floor(n/3600)}:${String(Math.floor(n/60)%60).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`:`${Math.floor(n/60)}:${String(n%60).padStart(2,'0')}`;};
export const parseTime = value=>String(value).split(':').reduce((n,v)=>n*60+Number(v),0);
const paths={
 search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
 spark:'<path d="m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4L12 3Z"/>',
 archive:'<rect x="3" y="3" width="18" height="5" rx="1"/><path d="M5 8v13h14V8M9 12h6"/>',
 clips:'<rect x="3" y="5" width="18" height="15" rx="2"/><path d="m3 10 18 0M7 5l3 5m4-5 3 5m-7 3 5 2-5 2z"/>',
 link:'<path d="m10 13 4-4m-6 7-2 2a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m2 10a4 4 0 0 0 6 0l5-5a4 4 0 0 0-6-6l-2 2" transform="translate(2 0) scale(.85)"/>',
 arrow:'<path d="M4 12h16m-6-6 6 6-6 6"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',
 play:'<path d="m8 4 12 8-12 8z"/>',
 close:'<path d="m6 6 12 12M6 18 18 6"/>',
 check:'<path d="m4 12 5 5L20 6"/>',
 upload:'<path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5"/>',
 download:'<path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4"/>',
 clock:'<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
 logout:'<path d="M9 4H4v16h5m6-14 6 6-6 6M9 12h12"/>',
 globe:'<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
 book:'<path d="M12 5c-3-3-7-2-9-1v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-2-1-6-2-9 1zm0 0v15"/>',
 help:'<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 4 2c-1 .5-1.5 1-1.5 2m0 3h.01"/>',
 refresh:'<path d="M20 8a8 8 0 1 0 1 7M20 3v5h-5"/>',
 file:'<path d="M5 3h9l5 5v13H5zm9 0v6h5M8 13h8m-8 4h6"/>'
};
export const icon=(name,cls='')=>`<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]||paths.file}</svg>`;
export function toast(message,error=false){const t=$('#toast');t.textContent=message;t.className='visible'+(error?' error':'');clearTimeout(toast.timer);toast.timer=setTimeout(()=>t.className='',5000);}
export async function api(path,options={}){
 const headers={'X-CSRF-Token':state.me?.csrf||'',...options.headers};
 if(options.body && !(options.body instanceof FormData)){headers['Content-Type']='application/json';options.body=JSON.stringify(options.body);}
 const response=await fetch('/api'+path,{...options,headers,credentials:'same-origin'});
 let data;try{data=await response.json();}catch{data={detail:'The server returned an unexpected response'};}
 if(!response.ok){const detail=Array.isArray(data.detail)?data.detail.map(e=>e.msg).join('; '):data.detail;const err=new Error(detail||'Something went wrong');err.status=response.status;throw err;}
 return data;
}
export function busy(button,label='Working…'){const original=button.innerHTML;button.disabled=true;button.textContent=label;return()=>{button.disabled=false;button.innerHTML=original;};}
export function sourceTag(p){return `<span class="source-tag ${p.source_kind==='youtube'?'video':'audio'}">${icon(p.source_kind==='youtube'?'play':'file')}${p.source_kind==='youtube'?'Video linked':p.source_kind==='podcast'?'Podcast transcript':'Archive'}</span>`;}
export function empty(title,description,action=''){return `<div class="empty">${icon('archive')}<h3>${esc(title)}</h3><p>${esc(description)}</p>${action}</div>`;}
export function errorPanel(error){return `<div class="error-panel" role="alert">${esc(error.message||error)}</div>`;}
export function loading(label='Loading…'){return `<div class="loading"><span class="spinner"></span>${esc(label)}</div>`;}
export function showDialog(html){$('#detail-content').innerHTML=html;if(!$('#detail').open)$('#detail').showModal();$('#detail').scrollTop=0;}
export function closeDialog(){$('#detail').close();$('#detail-content').innerHTML='';}
export const dialogHeader=(eyebrow,title)=>`<div class="drawer-top"><div><span class="eyebrow">${esc(eyebrow)}</span><h2 id="detail-title">${esc(title)}</h2></div><button class="icon-button" data-close aria-label="Close panel">${icon('close')}</button></div>`;
export function highlight(text,terms=[]){
 if(!terms.length)return esc(text);
 const escaped=terms.filter(x=>x.length>1).map(x=>x.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'));
 if(!escaped.length)return esc(text);
 const re=new RegExp(`(${escaped.join('|')})`,'gi');
 return String(text).split(re).map((s,i)=>i%2?`<mark>${esc(s)}</mark>`:esc(s)).join('');
}
