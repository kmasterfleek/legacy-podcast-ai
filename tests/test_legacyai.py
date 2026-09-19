"""Offline unit tests for the Legacy Podcast AI harness (no network)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from legacyai import render, config  # noqa: E402
from legacyai.providers import pick_caption_urls  # noqa: E402
from legacyai import sources  # noqa: E402

RSS = """<?xml version="1.0"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:podcast="https://podcastindex.org/namespace/1.0">
<channel><title>Old Time Radio</title>
<item><title>Episode 1</title><guid>ep-1</guid><link>https://x/1</link>
<pubDate>Tue, 20 Jul 1945 00:00:00 GMT</pubDate><itunes:duration>1:02:03</itunes:duration>
<itunes:season>1</itunes:season><itunes:episode>1</itunes:episode>
<enclosure url="https://x/1.mp3" type="audio/mpeg" length="1"/>
<podcast:transcript url="https://x/1.vtt" type="text/vtt"/>
<podcast:transcript url="https://x/1.json" type="application/json"/>
</item>
<item><title>No audio</title><guid>ep-2</guid></item>
</channel></rss>"""

VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.500 align:start position:0%

hello<00:00:00.500><c> there</c><00:00:01.000><c> everyone.</c>

00:00:02.500 --> 00:00:02.510 align:start position:0%
hello there everyone.


00:00:02.510 --> 00:00:05.000 align:start position:0%
hello there everyone.
welcome<00:00:03.000><c> to</c><00:00:03.500><c> the</c><00:00:04.000><c> show!</c>

"""

SRT = """1
00:00:01,000 --> 00:00:03,000
First line here.

2
00:00:03,000 --> 00:00:05,000
Second line here.
"""


class RenderTests(unittest.TestCase):
    def test_parse_vtt_dedupes_rolling_cues(self):
        cues = list(render.parse_vtt(VTT))
        paras, words = render.build_paragraphs(cues)
        self.assertEqual(words, 7)
        self.assertEqual(paras[0][1], "hello there everyone. welcome to the show!")

    def test_parse_srt(self):
        cues = list(render.parse_vtt(SRT))
        self.assertEqual([c[1] for c in cues], ["First line here.", "Second line here."])
        self.assertAlmostEqual(cues[0][0], 1.0)

    def test_paragraph_break_on_time(self):
        cues = [(0, "one two three."), (100, "four five six."), (200, "seven eight nine.")]
        paras, _ = render.build_paragraphs(cues)
        self.assertEqual(len(paras), 2)
        self.assertEqual(paras[1][0], 200)

    def test_render_and_frontmatter_roundtrip(self):
        ep = {"id": "abc123", "title": 'A "quoted" title', "url": "https://www.youtube.com/watch?v=abc123",
              "upload_date": "20260101", "duration": 3661}
        md = render.render_markdown(ep, "Show", [(0, "hi there.")], 2, "test source")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.md"
            p.write_text(md, encoding="utf-8")
            fm = render.read_frontmatter(p)
        self.assertEqual(fm["video_id"], "abc123")
        self.assertEqual(fm["title"], 'A "quoted" title')
        self.assertEqual(fm["duration"], "01:01:01")
        self.assertEqual(fm["upload_date"], "2026-01-01")
        self.assertIn("&t=0s", md)


class RegressionTests(unittest.TestCase):
    def test_vtt_without_hours_and_first_cue_kept(self):
        vtt = "WEBVTT\n\n00:01.000 --> 00:03.000\nfirst words here.\n \n00:03.000 --> 00:05.000\n[Music] second words here.\n"
        cues = list(render.parse_vtt(vtt))
        self.assertEqual(cues[0], (1.0, "first words here."))
        self.assertEqual(cues[1][1], "second words here.")

    def test_out_name_collision_and_unicode(self):
        from legacyai.build import out_name
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            a = {"id": "aaaaaaaaaaa", "title": "日本語のタイトル", "upload_date": "20260101"}
            b = {"id": "bbbbbbbbbbb", "title": "日本語のタイトル", "upload_date": "20260101"}
            na = out_name(a, out)
            self.assertEqual(na, "20260101-aaaaaaaaaaa.md")
            (out / na).write_text(render.render_markdown(a, "S", [(0, "x")], 1, "t"), encoding="utf-8")
            self.assertEqual(out_name(a, out), na)  # same episode: stable
            self.assertNotEqual(out_name(b, out), na)  # different episode: no clobber

    def test_tlang_strip_respects_source_language(self):
        info = {"automatic_captions": {
            "en": [{"ext": "vtt", "url": "https://x/tt?tlang=en&lang=es&v=1"}],
            "de": [{"ext": "vtt", "url": "https://x/tt?tlang=de&lang=es&v=1"}],
        }}
        cands = pick_caption_urls(info, "en")
        self.assertEqual(len(cands), 1)
        self.assertIn("machine-translated", cands[0][1])
        info_en = {"automatic_captions": {"de": [{"ext": "srt", "url": "https://x/tt?tlang=de&lang=en&v=1"}]}}
        self.assertEqual(pick_caption_urls(info_en, "en")[0][0], "https://x/tt?lang=en&v=1")

    def test_frontmatter_backslash_roundtrip(self):
        ep = {"id": "id1", "title": "C:\\path\\to", "url": "", "upload_date": "20260101", "duration": 10}
        md = render.render_markdown(ep, "S", [(0, "x")], 1, "t")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.md"; p.write_text(md, encoding="utf-8")
            self.assertEqual(render.read_frontmatter(p)["title"], "C:\\path\\to")


class SourceTests(unittest.TestCase):
    def test_kind_of(self):
        self.assertEqual(sources.kind_of("https://archive.org/details/mighty-mouse-and-the-wolf-1945"), "archive")
        self.assertEqual(sources.kind_of("ia:collection:prelinger"), "archive")
        self.assertEqual(sources.kind_of("https://example.com/feed.xml", sniff=False), "rss")
        self.assertEqual(sources.kind_of("rss:https://example.com/podcast"), "rss")
        self.assertEqual(sources.kind_of("https://www.youtube.com/@lexfridman/videos"), "ytdlp")
        self.assertEqual(sources.kind_of("https://example.com/feed", sniff=False), "ytdlp")  # no path guessing

    def test_normalize_date(self):
        self.assertEqual(sources.normalize_date("1945-07-20"), "19450720")
        self.assertEqual(sources.normalize_date("1945"), "1945")
        self.assertEqual(sources.normalize_date("Tue, 20 Jul 1945 00:00:00 GMT"), "19450720")
        self.assertEqual(sources.normalize_date(None), "")

    def test_parse_rss(self):
        eps = sources.parse_rss(RSS, "https://x/feed.xml")
        self.assertEqual(len(eps), 1)  # item without enclosure is skipped
        ep = eps[0]
        self.assertEqual(ep["upload_date"], "19450720")
        self.assertEqual(ep["duration"], 3723)
        self.assertEqual(ep["media_url"], "https://x/1.mp3")
        self.assertEqual(ep["transcript_urls"], ["https://x/1.vtt", "https://x/1.json"])
        self.assertEqual((ep["season"], ep["episode"]), (1, 1))
        self.assertTrue(ep["id"].startswith("rss-"))

    def test_archive_query_forms(self):
        self.assertEqual(sources.archive_query("ia:title:(mighty mouse)"), "title:(mighty mouse)")
        self.assertEqual(sources.archive_query("https://archive.org/search?query=mighty+mouse"), "mighty mouse")

    def test_podcast_json_transcript(self):
        cues = sources.parse_podcast_json_transcript('{"segments":[{"startTime":1.5,"body":"hi"},{"startTime":3,"body":""}]}')
        self.assertEqual(cues, [(1.5, "hi")])

    def test_word_level_json_keeps_repeats(self):
        words = "no no no I I think that that is is it .".split()
        segs = [{"startTime": i, "body": w} for i, w in enumerate(words)]
        cues = sources.parse_podcast_json_transcript(json.dumps({"segments": segs}))
        paras, n = render.build_paragraphs(cues)
        self.assertEqual(n, len(words))

    def test_normalize_date_archival_forms(self):
        self.assertEqual(sources.normalize_date("1945-07"), "19450701")
        self.assertEqual(sources.normalize_date("c. 1945"), "1945")
        self.assertEqual(sources.normalize_date("[1945]"), "1945")
        self.assertEqual(sources.normalize_date("Mon, 01 Jan 2024"), "2024")

    def test_archive_item_list_fields_and_extension_fallback(self):
        meta = {"metadata": {"mediatype": ["movies"], "title": ["Wolf! Wolf!"], "date": ["1944-06-22"],
                             "creator": ["Terrytoons", "Fox"], "licenseurl": ["https://cc/pdm"]},
                "files": [{"name": "Wolf Wolf [1944].flv", "format": "Unknown", "size": "100", "length": "6:09"},
                          {"name": "wolf.srt", "format": "Unknown"}]}
        orig = sources.http_json
        sources.http_json = lambda url, timeout=60: meta
        try:
            ep = sources.archive_item("wolf-wolf", log=lambda m: None)
        finally:
            sources.http_json = orig
        self.assertEqual(ep["upload_date"], "19440622")
        self.assertEqual(ep["channel"], "Terrytoons")
        self.assertEqual(ep["license"], "https://cc/pdm")
        self.assertEqual(ep["duration"], 369)
        self.assertTrue(ep["media_url"].endswith("/wolf-wolf/Wolf%20Wolf%20%5B1944%5D.flv"))
        self.assertEqual(len(ep["transcript_urls"]), 1)

    def test_rss_bytes_encoding_and_atom(self):
        latin = RSS.replace('<?xml version="1.0"?>', '<?xml version="1.0" encoding="ISO-8859-1"?>') \
                   .replace("Episode 1", "Caf\u00e9").encode("iso-8859-1")
        self.assertEqual(sources.parse_rss(latin)[0]["title"], "Caf\u00e9")
        with self.assertRaises(ValueError):
            sources.parse_rss('<feed xmlns="http://www.w3.org/2005/Atom"><title>x</title></feed>')

    def test_year_only_frontmatter(self):
        ep = {"id": "ia-x", "title": "Wolf! Wolf!", "url": "https://archive.org/details/x",
              "upload_date": "1944", "duration": 370, "license": "https://creativecommons.org/publicdomain/mark/1.0/"}
        md = render.render_markdown(ep, "Mighty Mouse", [(0, "x")], 1, "Whisper")
        self.assertIn('year: "1944"', md)
        self.assertIn('upload_date: "1944"', md)
        self.assertIn("**License:**", md)
        self.assertIn("##### `00:00:00`", md)  # non-YouTube: no deep link


class SpeakerAndDedupeTests(unittest.TestCase):
    def test_voice_tags_become_speaker_paragraphs(self):
        vtt = ("WEBVTT - Show\n\n0:00:00.070 --> 0:00:03.250\n<v Speaker 1>Welcome to the show.\n\n"
               "0:00:03.470 --> 0:00:07.220\n<v Speaker 1>Great to have you.\n\n"
               "0:00:07.480 --> 0:00:07.680\n<v Speaker 2>Yep.\n\n0:00:08.000 --> 0:00:09.000\n<v Speaker 2>Yep.\n")
        cues = list(render.parse_vtt(vtt))
        self.assertEqual(cues[0], (0.07, "Welcome to the show.", "Speaker 1"))
        paras, n = render.build_paragraphs(cues)
        self.assertEqual([p[2] for p in paras], ["Speaker 1", "Speaker 2"])
        self.assertEqual(paras[1][1], "Yep. Yep.")  # published text is not de-duplicated
        self.assertEqual(n, 10)
        md = render.render_markdown({"id": "x", "title": "t", "url": "", "upload_date": "20260101",
                                     "duration": 9}, "S", paras, n, "published transcript")
        self.assertIn("**Speaker 2:** Yep. Yep.", md)
        self.assertIn("speaker_labels: true", md)

    def test_match_score(self):
        from legacyai.dedupe import match_score
        yt = "Kevin Garnett: The NBA's Greatest Storyteller"
        self.assertTrue(match_score("Kevin Garnett | Greatest Storyteller", "20260822", yt, "2026-08-22"))
        self.assertFalse(match_score("Kevin Garnett | Greatest Storyteller", "20260901", yt, "2026-08-22"))  # too far apart
        self.assertTrue(match_score("T.I. | Ep 170 | ALL THE SMOKE Full Episode", "20230216",
                                    "T.I. | Ep 170 | ALL THE SMOKE Full Episode | SHOWTIME", "2023-02-16"))
        self.assertFalse(match_score("Wiz Khalifa | Ep 90", "20210624", "Leonard Ellerbe | Ep 91", "2021-06-24"))
        self.assertTrue(match_score("FIRST GUEST J.R. SMITH: WHY DOESN'T HE HAVE A TEAM?", "20191024",
                                    "Why is J.R. Smith Still a Free Agent?", "2019-10-24"))
        self.assertFalse(match_score("Kobe stories with Shaq", "20260101", "Kobe's last game", "2026-01-02"))


class ProviderTests(unittest.TestCase):
    def test_caption_priority(self):
        info = {
            "subtitles": {"en": [{"ext": "vtt", "url": "https://x/manual"}]},
            "automatic_captions": {
                "de": [{"ext": "vtt", "url": "https://x/auto?lang=en&tlang=de"}],
                "en": [{"ext": "vtt", "url": "https://x/auto?lang=en&tlang=en"}],
            },
        }
        cands = pick_caption_urls(info, "en")
        self.assertEqual(cands[0], ("https://x/manual", "manual subtitles"))
        # translated track with tlang stripped comes before a translation into en
        self.assertEqual(cands[1][0], "https://x/auto?lang=en")
        self.assertIn("machine-translated", cands[2][1])

    def test_no_tracks(self):
        self.assertEqual(pick_caption_urls({}, "en"), [])


class ConfigTests(unittest.TestCase):
    def test_scope_filters(self):
        s = config.Series(name="S", slug="s", min_minutes=25, exclude="live|watch party")
        self.assertEqual(s.wants({"duration": 600, "title": "x"}), "too short")
        self.assertEqual(s.wants({"duration": 3000, "title": "Watch Party LIVE"}), "title matches exclude pattern")
        self.assertIsNone(s.wants({"duration": 3000, "title": "Episode"}))

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["LEGACY_HOME"] = d
            try:
                s = config.Series(name="My Show", slug="my-show", sources=["https://a"], min_minutes=10)
                s.save()
                back = config.Series.load("my-show")
                self.assertEqual(back.sources, ["https://a"])
                self.assertEqual(back.out_dir, (Path(d) / "series/my-show/transcripts").resolve())
            finally:
                del os.environ["LEGACY_HOME"]

    def test_slugify(self):
        self.assertEqual(config.slugify("Kevin Garnett: The NBA's Greatest!"), "kevin-garnett-the-nba-s-greatest")


if __name__ == "__main__":
    unittest.main()
