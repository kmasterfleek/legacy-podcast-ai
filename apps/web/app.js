import {state,$,esc,fmt,icon,api,toast,busy,errorPanel,closeDialog} from './ui.js';
import {discover,archive,opportunities,connections} from './pages.js';
import {clipDesk} from './panels.js';

const nav=[['discover','spark','Discover'],['opportunities','globe','Opportunities'],['archive','archive','Archive'],['clips','clips','Clip desk'],['connections','link','Connections']];

async function loginScreen(){
 const settings=await api('/bootstrap');
 $('#app').innerHTML=`<main class="auth-screen"><section class="auth-story"><a class="brand" href="/" aria-label="Legacy Studio"><span class="brand-mark">L<span>▶</span></span><span>legacy<span class="brand-sub">STUDIO</span></span></a><div><span class="eyebrow">THE CONVERSATION CONTINUES</span><h1>Your archive.<br>Its next moment.</h1><p>Find the stories that matter now.<br>Bring them back into the conversation.</p></div><span class="auth-foot">DISCOVER &nbsp; / &nbsp; REVIEW &nbsp; / &nbsp; CREATE</span></section><section class="auth-form"><div class="auth-form-inner"><span class="eyebrow">WELCOME TO YOUR STUDIO</span><h2>Pick up the conversation.</h2><p class="muted">Sign in to your podcast workspace.</p><form id="login-form"><label>Email<input name="email" type="email" autocomplete="username" required placeholder="you@yourstudio.com"></label><label>Password<input name="password" type="password" autocomplete="current-password" required placeholder="Your password"></label><div id="login-error" role="alert"></div><button class="btn primary full" type="submit">Sign in ${icon('arrow')}</button></form>${settings.demo?'<div class="auth-divider"><span>LOCAL DEMO</span></div><button class="btn secondary full" id="demo-login">Explore the All The Smoke archive</button><p class="small muted">A local demo with the real transcript archive. Changes stay in this Studio instance.</p>':''}<p class="auth-help muted small">Need access? Ask your workspace administrator.</p></div></section></main>`;
 $('#login-form').onsubmit=async e=>{e.preventDefault();const done=busy(e.submitter,'Signing in…');try{await api('/login',{method:'POST',body:Object.fromEntries(new FormData(e.target))});await start();}catch(error){$('#login-error').innerHTML=errorPanel(error);}finally{done();}};
 $('#demo-login')?.addEventListener('click',async e=>{const done=busy(e.currentTarget,'Opening archive…');try{await api('/demo',{method:'POST'});await start();}catch(error){toast(error.message,true);}finally{done();}});
}

function shell(){
 const initials=state.me.workspace_name.split(/\s+/).slice(0,2).map(w=>w[0]).join('');
 $('#app').innerHTML=`<div class="studio"><aside class="sidebar"><a class="brand" href="#discover"><span class="brand-mark">L<span>▶</span></span><span>legacy<span class="brand-sub">STUDIO</span></span></a><div class="workspace-switch"><span class="workspace-avatar">${esc(initials)}</span><div><strong>${esc(state.me.workspace_name)}</strong><span>Podcast workspace</span></div></div><div class="nav-label">WORKSPACE</div><nav aria-label="Main navigation">${nav.map(([id,ic,label])=>`<a href="#${id}" data-nav="${id}">${icon(ic)}<span>${label}</span>${id==='clips'?'<span class="nav-count" id="clip-count"></span>':''}</a>`).join('')}</nav><div class="sidebar-bottom"><div class="archive-note">${icon('book')}<strong>Your stories keep working.</strong><span>Every moment starts with your archive.</span></div><button class="account" id="logout"><span class="account-avatar">${esc(state.me.name.slice(0,1))}</span><span><strong>${esc(state.me.name)}</strong><small>Sign out</small></span>${icon('logout')}</button></div></aside><div class="workspace-main"><header class="topbar"><span><span class="crumb">Workspace</span><span class="crumb-divider">/</span><strong id="current-page">Discover</strong></span><div class="topbar-right">${state.me.demo?'<span class="demo-tag">Local demo</span>':''}<span class="workspace-name">${esc(state.me.workspace_name)}</span><span class="top-avatar">${esc(initials)}</span></div></header><main id="main" tabindex="-1"></main><footer class="app-footer"><span>LEGACY STUDIO</span><span>Good stories deserve another moment.</span></footer></div></div>`;
 $('#logout').onclick=async()=>{try{await api('/logout',{method:'POST'});state.me=null;await loginScreen();}catch(error){toast(error.message,true);}};
}

export async function refreshStats(){state.stats=await api('/stats');const count=$('#clip-count');if(count)count.textContent=state.stats.clips||'';}

async function route(){
 if(!state.me)return;
 const value=location.hash.slice(1).split('?')[0];state.route=nav.some(x=>x[0]===value)?value:'discover';
 document.querySelectorAll('[data-nav]').forEach(a=>{const active=a.dataset.nav===state.route;a.classList.toggle('active',active);if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
 $('#current-page').textContent=nav.find(x=>x[0]===state.route)[2];
 document.title=`${$('#current-page').textContent} — Legacy Studio`;
 closeDialog();
 try{await ({discover,archive,opportunities,clips:clipDesk,connections}[state.route])();}catch(error){$('#main').innerHTML=errorPanel(error);if(error.status===401)await loginScreen();}
}

async function start(){
 try{state.me=await api('/me');}catch(error){if(error.status===401){await loginScreen();return;}throw error;}
 await refreshStats();shell();$('#clip-count').textContent=state.stats.clips||'';await route();
}
window.addEventListener('hashchange',route);
document.addEventListener('click',event=>{if(event.target.closest('[data-close]'))closeDialog();});
$('#detail').addEventListener('click',event=>{if(event.target===$('#detail'))closeDialog();});
document.addEventListener('keydown',event=>{if(event.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)&&!$('#detail').open){event.preventDefault();$('#query')?.focus();}});
start().catch(error=>{$('#app').innerHTML=`<main class="fatal"><h1>Studio couldn't open</h1>${errorPanel(error)}<button class="btn primary" id="retry">Try again</button></main>`;$('#retry').onclick=()=>location.reload();});
