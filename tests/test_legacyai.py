"""Offline unit tests for the Legacy Podcast AI harness (no network)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from legacyai import render, config  # noqa: E402
from legacyai.providers import pick_caption_urls  # noqa: E402

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
