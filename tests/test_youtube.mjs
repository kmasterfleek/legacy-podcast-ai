import test from 'node:test';
import assert from 'node:assert/strict';
import {youtubeSelection, youtubePreview, mountYouTube} from '../apps/web/youtube.js';

global.location = new URL('http://localhost:8000');
const passage = {youtube_id:'abcdefghijk',start:3825,end:3917};

// Exercise the actual controller against the public YT.Player contract without
// contacting YouTube or needing a browser in the offline test suite.
async function harness(t, loadAPI) {
 const names = ['player-slot','preview-selection','watch-youtube','selection-range','preview-status'];
 const nodes = Object.fromEntries(names.map(name => [name,{innerHTML:'',textContent:'',hidden:false,disabled:false,
  querySelector:() => ({tagName:'IFRAME'})}]));
 const dialog = new EventTarget();
 const root = {querySelector:selector => nodes[selector.slice(6,-1)],closest:() => dialog};
 const instances = [];
 class Player {
  constructor(frame, options) {this.events=options.events;this.calls=[];this.currentTime=3825;instances.push(this);}
  cueVideoById(value) {this.calls.push(['cue',value]);}
  loadVideoById(value) {this.calls.push(['load',value]);}
  playVideo() {this.calls.push(['play']);}
  pauseVideo() {this.calls.push(['pause']);}
  seekTo(value) {this.calls.push(['seek',value]);}
  getCurrentTime() {return this.currentTime;}
  destroy() {this.destroyed=true;}
 }
 const controller=mountYouTube(root,passage,loadAPI || (()=>Promise.resolve({Player})));
 t.after(()=>controller.dispose());
 await Promise.resolve();
 const ready=()=>{const player=instances.at(-1);player.events.onReady({target:player});return player;};
 return {nodes,dialog,controller,instances,ready,Player};
}

test('92-second selection uses absolute end time and a start-only watch URL',()=>{
 const selection=youtubeSelection(passage.youtube_id,3825,3917,location.origin);
 const url=new URL(selection.embed);
 assert.equal(url.searchParams.get('start'),'3825');
 assert.equal(url.searchParams.get('end'),'3917');
 assert.equal(url.searchParams.get('origin'),'http://localhost:8000');
 assert.equal(url.searchParams.get('playsinline'),'1');
 assert.equal(new URL(selection.watch).searchParams.get('t'),'3825s');
 assert.equal(new URL(selection.watch).searchParams.has('end'),false);
 const html=youtubePreview(passage);
 assert.match(html,/ORIGINAL EPISODE/);
 assert.match(html,/<iframe/);
 assert.match(html,/referrerpolicy="strict-origin-when-cross-origin"/);
 assert.doesNotMatch(html,/noreferrer|no-referrer/);
});

test('invalid IDs and invalid bounds never produce an embed',()=>{
 for(const values of [['invalid',0,60],['abcdefghijk',-1,60],['abcdefghijk',60,30],['abcdefghijk',0,NaN]]){
  assert.throws(()=>youtubeSelection(...values,location.origin));
 }
});

test('editing trim times updates the cued selection and watch link before saving',async t=>{
 const h=await harness(t), player=h.ready();
 assert.deepEqual(player.calls.at(-1),['cue',{videoId:'abcdefghijk',startSeconds:3825,endSeconds:3917}]);
 h.controller.update(3830,3900);
 assert.deepEqual(player.calls.at(-1),['cue',{videoId:'abcdefghijk',startSeconds:3830,endSeconds:3900}]);
 assert.match(h.nodes['watch-youtube'].href,/t=3830s$/);
 assert.equal(h.nodes['selection-range'].textContent,'1:03:50–1:05:00 · 70s');
 h.nodes['preview-selection'].onclick();
 assert.deepEqual(player.calls.at(-1),['load',{videoId:'abcdefghijk',startSeconds:3830,endSeconds:3900}]);
});

for(const code of [101,150,153]) test(`YouTube error ${code} offers a thumbnail and timestamped fallback`,async t=>{
 const h=await harness(t),player=h.ready();
 player.events.onError({data:code});
 assert.equal(player.destroyed,true);
 assert.match(h.nodes['player-slot'].innerHTML,/<img/);
 assert.doesNotMatch(h.nodes['player-slot'].innerHTML,/<iframe/);
 assert.match(h.nodes['watch-youtube'].href,/t=3825s$/);
 assert.equal(h.nodes['preview-selection'].textContent,'Retry preview');
 assert.match(h.nodes['preview-status'].textContent,code===153?/verify/:/disabled embedded/);
});

test('invalid edits stop the old player and hide stale links; valid edits recover',async t=>{
 const h=await harness(t),player=h.ready();
 h.controller.update(NaN,3917);
 assert.equal(player.destroyed,true);
 assert.equal(h.nodes['watch-youtube'].hidden,true);
 assert.equal(h.nodes['preview-selection'].disabled,true);
 h.controller.update(3800,3900);
 await Promise.resolve(); h.ready();
 assert.equal(h.nodes['watch-youtube'].hidden,false);
 assert.match(h.nodes['watch-youtube'].href,/t=3800s$/);
});

test('closing the drawer destroys playback; stale API callbacks cannot recreate it',async t=>{
 let resolve;
 const pending=new Promise(r=>{resolve=r;});
 const h=await harness(t,()=>pending);
 h.dialog.dispatchEvent(new Event('preview-dispose'));
 resolve({Player:h.Player}); await Promise.resolve();
 assert.equal(h.instances.length,0);
 const live=await harness(t),player=live.ready();
 live.dialog.dispatchEvent(new Event('close'));
 assert.equal(player.destroyed,true);
});

test('end guard still pauses if seeking has cancelled YouTube endSeconds',async t=>{
 const h=await harness(t),player=h.ready();
 player.events.onStateChange({data:1});
 player.currentTime=3917.2;
 await new Promise(r=>setTimeout(r,190));
 assert.deepEqual(player.calls.at(-1),['pause']);
 assert.match(h.nodes['preview-status'].textContent,/Selection finished/);
});

test('a blocked API script falls back without losing the selected timestamp',async t=>{
 const h=await harness(t,()=>Promise.reject(new Error('blocked')));
 assert.match(h.nodes['player-slot'].innerHTML,/<img/);
 assert.match(h.nodes['watch-youtube'].href,/t=3825s$/);
 assert.match(h.nodes['preview-status'].textContent,/could not load/);
});
