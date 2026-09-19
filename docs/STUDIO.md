# Legacy Studio

A browser application in the same repository as the transcription harness.
The Python service serves both the API and `apps/web`; no Node build step is
required. The original `legacy` CLI is unchanged.

## Run the working demo

Python 3.10+ and FFmpeg/ffprobe are recommended. From the repository root:

```bash
make setup
make dev
```

Open http://localhost:8000 and choose **Explore the All The Smoke archive**.
The first start indexes all 471 transcripts; subsequent runs skip unchanged
files. Demo mode starts a background worker in the same process. The corpus
contains about 6.3 million words. All state lives in `.legacy-studio/`.

Demo sign-in is deliberately local: `LEGACY_ENV=production` rejects demo mode.
Do not expose the demo server or its known demo account to customers. Use a
new storage volume and separately provisioned accounts for a pilot.

## Browser workflow

1. **Discover**: enter a person, topic, or headline. Source filters select video
   links or podcast transcripts. Results are BM25-ranked keyword matches with
   explicit name/topic aliases, advertisement filtering, and overlapping-result
   suppression. There are no fabricated confidence scores or semantic embeddings.
   When `ANTHROPIC_API_KEY` is set, Claude Haiku (`claude-haiku-4-5`, pinned in
   `search/rerank.py`) turns longer requests into search words, then reads the top 40
   keyword passages and keeps only those genuinely about the request, each with a
   one-sentence reason. Any API failure falls back to the keyword results.
2. **Read context**: inspect the exact source passage and adjacent text; preview
   linked YouTube media or open the podcast source. YouTube previews load the selected
   start/end range inline, with a **Preview selection** replay button. Editing clip
   times updates the preview and **Watch from … on YouTube** link before saving.
   The external YouTube link only sets the start; it does not enforce an end.
   If embedding is disabled or unavailable, a thumbnail and the timestamped link
   remain available. Times are approximate paragraph
   boundaries. Speaker 1 is not assumed to be a particular person.
3. **Save to clip desk**: title and caption are editable. The original passage and
   transcript hash are preserved as evidence across subsequent archive indexing.
4. **Source video**: the hosted teaser has no upload or YouTube fetch. The clip
   desk explains that the full Studio connects to the owner's own video library,
   cuts clips automatically, and exports to social channels after review. Render
   stays disabled until a clip has a connected source video. The upload and fetch
   API routes remain for the connected build.
5. **Render**: choose portrait, square, or landscape. FFmpeg creates an MP4 from
   the selected range with a center crop. Face tracking and burned-in subtitles
   are not part of this release. Edited clips require a new render and approval.
6. **Export**: the ZIP contains `clip.mp4` when rendered, `caption.txt`, the saved
   source passage, and an edit-decision JSON with provenance. Before rendering,
   the export is clearly labeled as editorial notes only.
7. **Approve / send**: approve the rendered revision, then deliver it to a
   configured publisher webhook. A delivery receipt means the workflow accepted
   the request, not that a social platform has published it.

**Opportunities** stores manual ideas and imported feed headlines. **Connections**
accepts public RSS/Atom feeds; the running worker checks them every 15 minutes.
These are incoming headlines, not measured social engagement velocity. There is
no active source or publisher until it is configured.

## Provision a commercial pilot

The v1 supports isolated workspaces on one persistent-volume host. Workspace
creation is an operator action; self-service signup, billing, and password recovery
are not implemented. A user is assigned to one workspace. Every archive, clip,
job, upload, and export request checks that workspace.

```bash
legacy-studio provision --email producer@example.com --name Producer --workspace "Client Studio"
```

This prompts for a password and prints the new workspace ID. For unattended
provisioning, supply `LEGACY_ADMIN_PASSWORD` through the host's secret manager.
Never put passwords in command arguments or checked-in files.

```bash
legacy-studio index --workspace WORKSPACE_ID --archive transcripts
legacy-studio serve --host 0.0.0.0
legacy-studio worker
```

Run serve and worker as separate processes with the same `LEGACY_STUDIO_DATA`.
Use `legacy-studio accounts` to find workspace IDs. Import a different archive
for each customer. The browser also accepts up to 50 timestamped Markdown files
per import. They must follow the frontmatter and heading format documented in
the root README. New indexing does not remove existing saved clips.

## Container deployment

```bash
docker compose up --build -d
docker compose exec web legacy-studio provision --email producer@example.com --name Producer --workspace "Client Studio"
docker compose exec web legacy-studio index --workspace WORKSPACE_ID --archive /app/transcripts
```

The example binds port 8000 to localhost. Put an HTTPS reverse proxy in front of
it; production cookies are Secure and therefore will not authenticate over plain
HTTP. Set `LEGACY_PUBLIC_URL` to that HTTPS origin. Keep the proxy Host header and
configure an upload body limit compatible with `LEGACY_UPLOAD_MB`. Uvicorn does
not trust arbitrary forwarded headers.

For Railway or another container host, use the included Dockerfile, mount a
persistent volume at `/data`, and launch one web process plus a worker sharing
that volume. If the host cannot share a volume between services, use one service
with `LEGACY_EMBEDDED_WORKER=1`. The web command reads `PORT`; the local Docker
health check assumes 8000, so override the host's health check to `/health` when
using a different port. Do not scale this SQLite version across machines.

On hosts without a shell, set `LEGACY_BOOTSTRAP_EMAIL` and `LEGACY_ADMIN_PASSWORD`
(8+ characters, stored as a secret). On start, `serve` creates that account, or
updates its password if the variable changed, and indexes the bundled archive
into its workspace. Optional: `LEGACY_BOOTSTRAP_NAME`, `LEGACY_BOOTSTRAP_WORKSPACE` (default `All The Smoke`),
`LEGACY_BOOTSTRAP_ARCHIVE` (default `transcripts`).

The image includes the repository's transcript archive. For separate customer
deployments, build with only their authorized corpus or remove the COPY of
`transcripts` and import through the browser. No index is exposed without sign-in.

Back up `/data` before upgrades. Use SQLite's backup API while the service is
running, or stop web and worker before copying the database, media, and renders.
The initial database schema has `user_version=1`; future schema changes must ship
an explicit migration. Generated data and media are excluded from Git.

## Publisher integration

Set these values on both web and worker:

- `LEGACY_PUBLISH_WEBHOOK`: an HTTPS endpoint such as your own n8n workflow.
- `LEGACY_PUBLISH_WORKSPACE`: the one workspace ID authorized for this endpoint.
- `LEGACY_PUBLIC_URL`: reachable HTTPS base URL of Studio.
- `LEGACY_SIGNING_KEY`: a randomly generated secret of at least 32 bytes.

The worker POSTs JSON including `event`, `idempotency_key`, `clip_id`, `revision`,
`title`, `caption`, `format`, and a signed `video_url` valid for one hour.
`X-Legacy-Signature` is HMAC-SHA256 of the raw request body. Verify the signature
and persist `Idempotency-Key` before creating platform posts. Fetch the video
before the link expires. A changed or unapproved clip revokes its old link.

A delivery is attempted once per revision. A network failure is marked uncertain,
because the receiver may already have accepted it; Studio does not automatically
retry potentially duplicate posts. Check the receiver's receipt before taking
further action. Native Instagram/TikTok/YouTube OAuth and scheduled publication
are a later release, not hidden behind working-looking controls.

## Development map

| Change | Location |
|---|---|
| Browser screens | `apps/web/pages.js`, `panels.js`, `styles.css` |
| Accounts / server | `src/legacyai/studio/auth.py`, `app.py`, `db.py` |
| Archive indexing / retrieval | `src/legacyai/search/` |
| Clip workflow | `src/legacyai/studio/clip_api.py` |
| Source downloads / rendering | `src/legacyai/clips/` |
| Jobs / publisher | `src/legacyai/studio/jobs.py` |
| RSS parsing | `src/legacyai/trends/feeds.py` |

Run `make test` for regression and API workflow tests. The integration suite uses
temporary storage, creates test accounts, verifies workspace isolation and CSRF,
and renders a short synthetic video when FFmpeg is available. No test contacts
YouTube, a live feed, or a publisher. The frontend uses native ES modules; syntax
can be checked with `node --check apps/web/app.js` and the other modules.
Run `node --test tests/test_youtube.mjs` with Node 22+ for player lifecycle,
selection timing, replay, and error fallback checks. These checks use a fake
YouTube API; live playback depends on the source video's embedding permissions.

The player uses YouTube's IFrame API with `start`/`end` and an absolute end time.
The server and iframe send an origin referrer (`strict-origin-when-cross-origin`)
for YouTube client identification; suppressing it can produce player error 153.
The CSP permits YouTube API scripts, the privacy-enhanced player, and thumbnails.
Start positions may land near a keyframe, so embedded previews are not frame-exact.
The player also pauses at the selected end if the viewer seeks within the video;
closing the drawer stops playback. No video download is required for this preview.

## Next release priorities

1. Evaluate retrieval using labeled trend/moment pairs; add embeddings and model
   reranking with measured improvements over this baseline.
2. Preserve native cue end times and word timestamps from ingestion. Align
   RSS and video edits explicitly; generic duplicate detection is insufficient.
3. Add accurate subtitles and active-speaker framing to the renderer.
4. Connect measured social trends, native publisher OAuth, and publish receipts.
5. Add managed identity/recovery, billing, quotas, monitoring, object storage,
   and a database/queue suitable for multiple hosts before self-service launch.
