import {esc, time, icon} from './ui.js';

export function youtubeSelection(videoId, start, end, origin) {
 if (!/^[A-Za-z0-9_-]{11}$/.test(videoId || '')) throw new Error('No matching YouTube video is linked to this episode.');
 if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) throw new Error('Choose a valid start and end time to preview.');
 const params = new URLSearchParams({start:Math.floor(start), end:Math.ceil(end), playsinline:1, rel:0, enablejsapi:1});
 if (/^https?:\/\//.test(origin || '')) params.set('origin', new URL(origin).origin);
 return {videoId, start, end,
  embed:`https://www.youtube-nocookie.com/embed/${videoId}?${params}`,
  watch:`https://www.youtube.com/watch?v=${videoId}&t=${Math.floor(start)}s`,
  thumbnail:`https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`};
}

function iframe(selection) {
 return `<iframe title="YouTube selection preview" src="${esc(selection.embed)}" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe>`;
}

export function youtubePreview(p) {
 const selection = youtubeSelection(p.youtube_id, p.start, p.end, location.origin);
 return `<section class="youtube-preview" data-youtube-preview aria-label="Preview selected section">
  <div class="preview-heading"><span class="eyebrow">ORIGINAL EPISODE</span><span data-selection-range></span></div>
  <div class="source-preview youtube-player" data-player-slot>${iframe(selection)}</div>
  <div class="preview-controls"><button type="button" class="btn secondary" data-preview-selection>${icon('play')} Preview selection</button>
   <a class="text-btn" data-watch-youtube href="${esc(selection.watch)}" target="_blank" rel="noopener" referrerpolicy="strict-origin-when-cross-origin">Watch from ${time(selection.start)} on YouTube ↗</a></div>
  <p class="small muted preview-status" data-preview-status role="status">Press Play to preview this selection.</p>
  <p class="small muted preview-help">The YouTube link starts at your selected time; it does not stop at the end of the selection.</p>
 </section>`;
}

export function youtubeError(code) {
 if ([101,150].includes(code)) return 'The publisher has disabled embedded playback. Watch this moment on YouTube instead.';
 if (code === 100) return 'This video is unavailable or private. Open YouTube to check access.';
 if (code === 153) return 'YouTube could not verify this embedded player. Open the selected moment on YouTube.';
 return 'The YouTube preview could not load here. You can still open the selected moment on YouTube.';
}

let apiPromise;
function loadYouTubeAPI() {
 if (window.YT?.Player) return Promise.resolve(window.YT);
 if (apiPromise) return apiPromise;
 apiPromise = new Promise((resolve,reject) => {
  const script = document.createElement('script');
  let timer, previous = window.onYouTubeIframeAPIReady;
  const finish = error => {
   clearTimeout(timer);
   if (window.onYouTubeIframeAPIReady === ready) window.onYouTubeIframeAPIReady = previous;
   if (error) { script.remove(); reject(error); } else resolve(window.YT);
  };
  const ready = () => { finish(); if (typeof previous === 'function') previous(); };
  window.onYouTubeIframeAPIReady = ready;
  script.src = 'https://www.youtube.com/iframe_api';
  script.referrerPolicy = 'strict-origin-when-cross-origin';
  script.onerror = () => finish(new Error('YouTube player API unavailable'));
  timer = setTimeout(() => finish(new Error('YouTube player API timed out')), 15000);
  document.head.append(script);
 }).catch(error => {apiPromise = null; throw error;});
 return apiPromise;
}

// Lifecycle stays with the drawer: closing or replacing it stops playback and timers.
export function mountYouTube(root, p, loadAPI = loadYouTubeAPI) {
 let selection = youtubeSelection(p.youtube_id, p.start, p.end, location.origin);
 const slot = root.querySelector('[data-player-slot]');
 const button = root.querySelector('[data-preview-selection]');
 const link = root.querySelector('[data-watch-youtube]');
 const range = root.querySelector('[data-selection-range]');
 const status = root.querySelector('[data-preview-status]');
 const dialog = root.closest('dialog');
 let player, ready = false, disposed = false, valid = true, generation = 0, guard, timeout;
 const stopGuard = () => {clearInterval(guard); guard = null;};
 const resetPlayer = () => {
  stopGuard(); clearTimeout(timeout); ready = false;
  const old = player; player = null;
  try {old?.destroy();} catch {}
 };
 const cue = () => player.cueVideoById({videoId:selection.videoId, startSeconds:selection.start, endSeconds:selection.end});
 const describe = () => {
  range.textContent = `${time(selection.start)}–${time(selection.end)} · ${Math.round(selection.end-selection.start)}s`;
  link.href = selection.watch;
  link.textContent = `Watch from ${time(selection.start)} on YouTube ↗`;
  link.hidden = false;
 };
 const fallback = code => {
  if (disposed || !valid) return;
  generation++; resetPlayer();
  slot.innerHTML = `<img class="youtube-thumbnail" src="${esc(selection.thumbnail)}" alt="Episode thumbnail" referrerpolicy="strict-origin-when-cross-origin">`;
  status.textContent = youtubeError(code);
  button.disabled = false;
  button.textContent = 'Retry preview';
 };
 async function connect(play = false) {
  const current = ++generation;
  resetPlayer();
  slot.innerHTML = iframe(selection);
  button.textContent = 'Preview selection';
  status.textContent = 'Loading selection preview…';
  try {
   const YT = await loadAPI();
   if (disposed || current !== generation || !valid) return;
   timeout = setTimeout(() => {if (current === generation) fallback();},12000);
   player = new YT.Player(slot.querySelector('iframe'), {events:{
    onReady: event => {
     if (disposed || current !== generation) return;
     clearTimeout(timeout); player = event.target; ready = true;
     cue();
     status.textContent = 'Preview plays the selected range. YouTube may begin near the requested start.';
     if (play) player.playVideo();
    },
    onError: event => {if (current === generation) fallback(event.data);},
    onStateChange: event => {
     if (disposed || current !== generation) return;
     stopGuard();
     if (event.data !== 1) return;
     // Seeking in YouTube can cancel endSeconds; keep the selection bounded.
     guard = setInterval(() => {
      if (!ready || disposed) return;
      const currentTime = player.getCurrentTime();
      if (currentTime >= selection.end) {
       player.pauseVideo(); stopGuard();
       status.textContent = 'Selection finished. Press Preview selection to replay.';
      } else if (currentTime < selection.start - 0.5) player.seekTo(selection.start,true);
     },150);
    }
   }});
  } catch {if (current === generation) fallback();}
 }
 function update(start, end) {
  try {
   const next = youtubeSelection(p.youtube_id,start,end,location.origin);
   if (valid && next.start === selection.start && next.end === selection.end) return;
   selection = next; valid = true; button.disabled = false; describe();
   if (ready) {stopGuard(); player.pauseVideo(); cue(); status.textContent = 'Timing updated. Press Preview selection to play this range.';}
   else connect();
  } catch (error) {
   valid = false; generation++; resetPlayer();
   slot.innerHTML = ''; button.disabled = true; link.hidden = true;
   range.textContent = 'Choose a valid range'; status.textContent = error.message;
  }
 }
 button.onclick = () => {
  if (!valid) return;
  if (!ready) {connect(true); return;}
  player.loadVideoById({videoId:selection.videoId, startSeconds:selection.start, endSeconds:selection.end});
  status.textContent = 'Playing selection…';
 };
 function dispose() {
  disposed = true; generation++; resetPlayer(); button.onclick = null;
  dialog?.removeEventListener('preview-dispose',dispose);
  dialog?.removeEventListener('close',dispose);
 }
 dialog?.addEventListener('preview-dispose',dispose,{once:true});
 dialog?.addEventListener('close',dispose,{once:true});
 describe(); connect();
 return {update, dispose};
}
