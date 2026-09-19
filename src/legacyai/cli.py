"""legacy: harvest transcripts for any podcast, channel, playlist or media series.

    legacy init "All The Smoke" --url https://www.youtube.com/@AllTheSmoke/videos --min-minutes 25
    legacy discover all-the-smoke
    legacy build all-the-smoke --limit 20 --workers 3
    legacy validate all-the-smoke
    legacy run all-the-smoke            # discover + build + validate + index
    legacy init "Mighty Mouse" --url "ia:title:(mighty mouse) AND date:[1942 TO 1961]"   # Internet Archive
    legacy init "My Podcast" --url https://example.com/feed.xml                          # RSS feed
    legacy import my-tv-show ~/Videos/show/*.mp4                                         # local files
    legacy status
"""
import argparse
import json
import sys

from . import __version__
from .config import Series, slugify


def cmd_init(a):
    slug = a.slug or slugify(a.name, 40)
    s = Series(name=a.name, slug=slug, sources=list(a.url or []), language=a.language,
               min_minutes=a.min_minutes, max_minutes=a.max_minutes,
               include=a.include, exclude=a.exclude,
               transcripts_dir=a.transcripts_dir, max_entries=a.max_entries, whisper_model=a.whisper_model,
               providers=[p.strip() for p in a.providers.split(",") if p.strip()])
    if s.config_path.exists() and not a.force:
        sys.exit(f"series '{slug}' already exists at {s.config_path} (use --force to overwrite)")
    s.save()
    print(f"created series '{slug}' -> {s.config_path}")
    print(f"transcripts will go to {s.out_dir}")


def cmd_add_source(a):
    s = Series.load(a.series)
    for u in a.url:
        if u not in s.sources:
            s.sources.append(u)
    s.save()
    print(f"{len(s.sources)} source(s) on '{s.slug}'")


def cmd_config(a):
    s = Series.load(a.series)
    for key in ("language", "min_minutes", "max_minutes", "include", "exclude", "max_entries", "providers",
                "request_sleep", "cookies_from_browser", "cookies_file", "whisper_model",
                "whisper_vad", "min_wpm", "max_wpm", "max_media_mb"):
        val = getattr(a, key)
        if val is None:
            continue
        if key == "providers":
            val = [p.strip() for p in val.split(",") if p.strip()]
        setattr(s, key, val)
    s.save()
    print(json.dumps({k: getattr(s, k) for k in ("language", "min_minutes", "max_minutes", "include",
                                                  "exclude", "max_entries", "providers", "request_sleep",
                                                  "cookies_from_browser", "cookies_file", "whisper_model",
                                                  "whisper_vad", "min_wpm", "max_wpm", "max_media_mb")}, indent=2))


def cmd_discover(a):
    from .catalog import discover, in_scope
    s = Series.load(a.series)
    cat = discover(s, workers=a.workers, max_entries=a.max_entries, only_source=a.source or "")
    print(f"catalog: {len(cat)} episodes, {len(in_scope(s, cat))} in scope")


def cmd_build(a):
    from .build import build, write_index
    s = Series.load(a.series)
    build(s, limit=a.limit, workers=a.workers, retry_failed=a.retry_failed,
          since=a.since or "", only=a.id or None, force=a.force, dedupe=not a.no_dedupe)
    write_index(s)


def cmd_dedupe(a):
    from .dedupe import mark_duplicates
    mark_duplicates(Series.load(a.series), days=a.days, dry_run=a.dry_run)


def cmd_validate(a):
    from .validate import validate
    flags = validate(Series.load(a.series))
    sys.exit(1 if flags and a.strict else 0)


def cmd_run(a):
    from .build import build, write_index
    from .catalog import discover
    from .validate import validate
    s = Series.load(a.series)
    discover(s, workers=a.workers, max_entries=a.max_entries)
    build(s, limit=a.limit, workers=a.build_workers, retry_failed=a.retry_failed)
    write_index(s)
    validate(s)


def cmd_import(a):
    from .catalog import import_local
    s = Series.load(a.series)
    import_local(s, a.path)


def cmd_status(a):
    from .validate import status
    series = [Series.load(a.series)] if a.series else Series.list_all()
    if not series:
        print("no series yet; run: legacy init")
        return
    if a.json:
        print(json.dumps([status(s) for s in series], indent=2))
        return
    for s in series:
        st = status(s)
        lo, hi = st["date_range"]
        print(f"{s.slug:<28} done {st['done']:>4}  failed {st['failed']:>3}  pending {st['pending']:>4}"
              f"  in-scope {st['in_scope']:>4}/{st['catalog']:<4}  {lo}..{hi}  {st['words']:,} words")
        for reason, n in st["failure_reasons"].items():
            print(f"{'':<28}   {n:>3} x {reason}")
        if st["duplicates"]:
            print(f"{'':<28}   {st['duplicates']} entries linked as duplicates of existing transcripts")
        if st["unprobed"]:
            print(f"{'':<28}   {st['unprobed']} catalog entries have no metadata yet (re-run discover)")


def cmd_doctor(_a):
    import shutil
    from .providers import whisper_available
    checks = []
    try:
        import yt_dlp
        checks.append(("yt-dlp", yt_dlp.version.__version__))
    except ImportError:
        checks.append(("yt-dlp", "MISSING (pip install yt-dlp)"))
    checks.append(("ffmpeg", shutil.which("ffmpeg") or "missing (optional; faster-whisper decodes without it)"))
    checks.append(("ffprobe", shutil.which("ffprobe") or "missing (local file durations)"))
    checks.append(("whisper backend", whisper_available() or "none (pip install faster-whisper)"))
    checks.append(("python", sys.version.split()[0]))
    for k, v in checks:
        print(f"{k:<16} {v}")


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="legacy", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"legacy {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("init", help="create a series")
    i.add_argument("name")
    i.add_argument("--slug")
    i.add_argument("--url", action="append", help="channel/playlist/video URL (repeatable)")
    i.add_argument("--language", default="en")
    i.add_argument("--min-minutes", type=float, default=0)
    i.add_argument("--max-minutes", type=float)
    i.add_argument("--include", help="regex; keep only titles that match")
    i.add_argument("--exclude", help="regex; drop titles that match")
    i.add_argument("--providers", default="captions,sidecar,whisper")
    i.add_argument("--whisper-model", default="small")
    i.add_argument("--transcripts-dir", help="output dir relative to the series folder")
    i.add_argument("--max-entries", type=int, default=0, help="newest N entries per source (0 = all)")
    i.add_argument("--force", action="store_true")
    i.set_defaults(fn=cmd_init)

    s = sub.add_parser("add-source", help="add a source URL to a series")
    s.add_argument("series"); s.add_argument("url", nargs="+")
    s.set_defaults(fn=cmd_add_source)

    c = sub.add_parser("config", help="change series settings")
    c.add_argument("series")
    c.add_argument("--language"); c.add_argument("--min-minutes", type=float)
    c.add_argument("--max-minutes", type=float); c.add_argument("--include"); c.add_argument("--exclude")
    c.add_argument("--max-entries", type=int); c.add_argument("--providers")
    c.add_argument("--request-sleep", type=float, help="seconds between requests (default 1.0)")
    c.add_argument("--cookies-from-browser", help="chrome|firefox|safari|edge|brave")
    c.add_argument("--cookies-file", help="Netscape cookies.txt path")
    c.add_argument("--whisper-model", help="tiny|base|small|medium|large-v3 (default small)")
    c.add_argument("--whisper-vad", type=lambda v: v.lower() in ("1", "true", "yes", "on"), help="true|false")
    c.add_argument("--min-wpm", type=float); c.add_argument("--max-wpm", type=float)
    c.add_argument("--max-media-mb", type=int)
    c.set_defaults(fn=cmd_config)

    d = sub.add_parser("discover", help="enumerate sources and probe episode metadata")
    d.add_argument("series"); d.add_argument("--workers", type=int, default=3)
    d.add_argument("--max-entries", type=int, default=0, help="override series max_entries")
    d.add_argument("--source", help="only list sources whose URL contains this text")
    d.set_defaults(fn=cmd_discover)

    b = sub.add_parser("build", help="fetch transcripts for pending episodes")
    b.add_argument("series")
    b.add_argument("--limit", type=int, default=0)
    b.add_argument("--workers", type=int, default=3)
    b.add_argument("--since", help="YYYY-MM-DD; skip older episodes")
    b.add_argument("--id", action="append", help="build only this episode id (repeatable)")
    b.add_argument("--retry-failed", action="store_true")
    b.add_argument("--force", action="store_true", help="rebuild even if already done (pair with --id)")
    b.add_argument("--no-dedupe", action="store_true", help="skip cross-source duplicate linking")
    b.set_defaults(fn=cmd_build)

    dd = sub.add_parser("dedupe", help="link episodes that arrive from two sources (runs automatically in build)")
    dd.add_argument("series"); dd.add_argument("--days", type=int, default=3)
    dd.add_argument("--dry-run", action="store_true", help="list matches without recording them")
    dd.set_defaults(fn=cmd_dedupe)

    v = sub.add_parser("validate", help="sanity-check built transcripts")
    v.add_argument("series"); v.add_argument("--strict", action="store_true")
    v.set_defaults(fn=cmd_validate)

    r = sub.add_parser("run", help="discover + build + index + validate")
    r.add_argument("series")
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--workers", type=int, default=3)
    r.add_argument("--build-workers", type=int, default=3)
    r.add_argument("--max-entries", type=int, default=0)
    r.add_argument("--retry-failed", action="store_true")
    r.set_defaults(fn=cmd_run)

    m = sub.add_parser("import", help="add local media files to a series")
    m.add_argument("series"); m.add_argument("path", nargs="+")
    m.set_defaults(fn=cmd_import)

    st = sub.add_parser("status", help="progress per series")
    st.add_argument("series", nargs="?"); st.add_argument("--json", action="store_true")
    st.set_defaults(fn=cmd_status)

    sub.add_parser("doctor", help="check tools").set_defaults(fn=cmd_doctor)
    return p


def main(argv=None):
    args = make_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
