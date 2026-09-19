# Legacy Studio: build plan

## Product

A browser workspace for podcast producers: turn a current conversation into a
relevant archive moment, review the context, prepare a clip, and export it for
publication. Keep the entire application in this repository. The existing
`legacy` ingestion CLI continues to work independently.

## First release

1. **Archive**: index the committed transcript corpus, search timestamped passages,
   browse episodes, read surrounding context, and open the original source.
2. **Opportunities**: enter a topic or paste a headline, optionally attach its
   source link, and rank relevant passages. Save searches as opportunities.
3. **Clip desk**: save a passage, edit its title/caption/format and timing, attach
   source media, preview a render, approve, and export an MP4 plus editorial notes.
4. **Workspace**: persistent server-side state, authenticated workspaces, isolated
   archives and clips, a clearly labeled local demo, and an account provisioning CLI.
5. **Operations**: one development command, a container deployment, health checks,
   a persistent data directory, and a background worker for rendering and feed sync.

## Architecture

- Python + FastAPI serve a same-origin API and a dependency-light browser client.
- SQLite with FTS5 provides scoped keyword retrieval; common name aliases and
  topical query expansion improve recall. The UI describes this honestly; semantic
  embeddings and model reranking are a subsequent, measured enhancement.
- The archive index is derived; workspace accounts, opportunities, clips, source
  registrations, and job states are durable. Each query is workspace scoped.
- Imported Markdown is immutable source evidence. Paragraph starts are retained;
  ends inferred from the next paragraph are explicitly approximate. No fabricated
  word timing or speaker identities. Video cuts require a registered source asset
  and a human confirmation of its alignment with the transcript.
- FFmpeg renders files in a separate worker. Jobs use an atomic claim, bounded
  retries, and persist errors. A render can never silently become a publication.
- RSS trend inputs are configurable. No source is represented as connected without
  configuration and a successful fetch. A supported webhook publisher is optional;
  native social OAuth, platform scheduling, and billing are future release work.

## Source layout

- `src/legacyai/studio/`: API, storage, authentication, jobs, and management CLI.
- `src/legacyai/search/`: transcript parsing, indexing, and ranking.
- `src/legacyai/clips/`: media validation and rendering.
- `src/legacyai/trends/`: feed ingestion.
- `apps/web/`: responsive client, styles, and assets.
- `tests/`: offline fixtures and API / workflow tests.
- `docs/`: product plan and deployment / operating instructions.

## Commercial rollout

Pilot with one separately provisioned workspace per customer. Before self-service
SaaS launch: managed identity and recovery, billing and entitlements, quotas,
object storage, retention policy, platform OAuth, publish receipts, observability,
and PostgreSQL/queue migration if multiple replicas are needed. The initial SQLite
deployment runs on one persistent-volume host with a separate worker process.

## Acceptance checks

- All 471 source files can be indexed; dates come from transcript metadata.
- Searches produce actual archive passages, relevant source links, and context.
- Empty/error/loading states and mobile navigation work.
- Accounts cannot read or modify another workspace's records, media, or jobs.
- Changed clip edits invalidate prior rendering and approval.
- Render a supplied test video, download the result, and verify its duration.
- Feed import deduplicates items; no configured feed means no claimed live trends.
- No credentials, generated database, full videos, or rendered clips are committed.
