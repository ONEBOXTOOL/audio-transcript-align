#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audio_align.py 的纯逻辑单测（不需要 Whisper / 音频）。

运行：
    python tests/test_audio_align.py -v
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("audio_align", HERE.parent / "audio_align.py")
assert spec and spec.loader
align = importlib.util.module_from_spec(spec)
sys.modules["audio_align"] = align
spec.loader.exec_module(align)


class SentenceSplitTest(unittest.TestCase):
    def test_abbreviations_and_decimals(self):
        self.assertEqual(len(align.split_sentences("Dr. Smith went home. He slept.")), 2)
        self.assertEqual(len(align.split_sentences("It costs 3.14 dollars. OK.")), 2)
        self.assertEqual(len(align.split_sentences("Use e.g. this one. Next.")), 2)
        self.assertEqual(len(align.split_sentences("U.S. policy changed. Really?")), 2)

    def test_quotes(self):
        self.assertEqual(
            align.split_sentences('He said "Stop." Then left.'),
            ['He said "Stop."', "Then left."],
        )


class TranscriptParseTest(unittest.TestCase):
    def test_bold_speaker(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.txt"
            p.write_text(
                "Note: This is not a word-for-word transcript.\n"
                "**Neil**\nHello there. I'm Neil.\n"
                "**Georgie**\nAnd I'm Georgie.\n",
                encoding="utf-8",
            )
            seeds = align.parse_transcript(p)
            self.assertEqual(seeds[0].speaker, "Neil")
            self.assertEqual(seeds[-1].speaker, "Georgie")
            self.assertNotIn("Note:", seeds[0].text)

    def test_plain_speaker_and_colon(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.txt"
            p.write_text(
                "Neil\nHello there, this is 6 Minute English.\n"
                "Georgie\nAnd I'm Georgie, welcome back.\n"
                "Neil: One more line from Neil.\n",
                encoding="utf-8",
            )
            seeds = align.parse_transcript(p)
            self.assertEqual(seeds[0].speaker, "Neil")
            self.assertEqual(seeds[-1].speaker, "Neil")
            self.assertTrue(any(s.speaker == "Georgie" for s in seeds))

    def test_skips_front_matter_until_transcript(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.txt"
            p.write_text(
                "6 Minute English\nStress-free family meals\n"
                "This week's question: what should parents do?\n"
                "Vocabulary: pressure, reward\n"
                "**TRANSCRIPT**\n"
                "Note: This is not a word-for-word transcript.\n"
                "**Neil**\nHello, this is 6 Minute English.\n",
                encoding="utf-8",
            )
            seeds = align.parse_transcript(p)
            self.assertEqual(len(seeds), 1)
            self.assertEqual(seeds[0].speaker, "Neil")
            self.assertNotIn("Vocabulary", seeds[0].text)

    def test_merge_ellipsis_fragment(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.txt"
            p.write_text(
                "John\nIt's... it's virtual, it's online.\n"
                "Phil\nOK. Well, we'll give you the answer.\n",
                encoding="utf-8",
            )
            seeds = align.parse_transcript(p)
            self.assertEqual(len(seeds), 3)  # It's... 已并入下一句；OK. / Well... 仍是两句
            self.assertTrue(seeds[0].text.startswith("It's... it's virtual"))
            self.assertEqual(seeds[1].text, "OK.")
            self.assertEqual(seeds[2].speaker, "Phil")


class TokenTest(unittest.TestCase):
    def test_expand(self):
        self.assertEqual(align.expand_token("don't"), ["do", "not"])
        self.assertEqual(align.expand_token("thirty"), ["30"])
        self.assertEqual(align.expand_token("long-term"), ["long", "term"])
        self.assertEqual(align.expand_token("U.S."), ["us"])
        self.assertEqual(align.expand_token("50,000"), ["50", "000"])
        self.assertEqual(align.expand_token("okay"), ["ok"])
        self.assertEqual(align.expand_token("tonnes"), ["tons"])
        self.assertEqual(align.expand_token("bbclearningenglish.com."), ["bbclearningenglish", "com"])


class ClusterTest(unittest.TestCase):
    def test_repeated_phrase_prefers_later_cluster(self):
        # 两个等长簇（中间隔了 3 个 ASR 词）时，取靠后的那个
        pairs = [(0, 10, 10), (1, 14, 14)]
        chosen = align._pick_cluster(pairs)
        self.assertEqual(chosen[-1][2], 14)


class EndToEndTest(unittest.TestCase):
    def test_asr_json_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.wav").write_bytes(b"")  # 只校验存在，不真的解码
            (root / "t.txt").write_text(
                "Neil\nHello there. How are you?\n"
                "Georgie\nFine, thanks.\n",
                encoding="utf-8",
            )
            words = [
                {"word": "Hello", "start": 0.0, "end": 0.4},
                {"word": "there.", "start": 0.4, "end": 0.8},
                {"word": "How", "start": 1.0, "end": 1.3},
                {"word": "are", "start": 1.3, "end": 1.5},
                {"word": "you?", "start": 1.5, "end": 1.8},
                {"word": "Fine,", "start": 2.0, "end": 2.3},
                {"word": "thanks.", "start": 2.3, "end": 2.8},
            ]
            (root / "w.json").write_text(json.dumps({"words": words}), encoding="utf-8")
            rc = align.main([
                "--audio", str(root / "a.wav"),
                "--transcript", str(root / "t.txt"),
                "--asr-json", str(root / "w.json"),
                "--out", str(root / "out"),
                "--title", "T",
                "--no-preview",
            ])
            self.assertEqual(rc, 0)
            data = json.loads((root / "out" / "episode.json").read_text(encoding="utf-8"))
            self.assertEqual(len(data["sentences"]), 3)
            self.assertEqual(data["sentences"][0]["speaker"], "Neil")
            self.assertAlmostEqual(data["sentences"][0]["confidence"], 1.0)
            for a, b in zip(data["sentences"], data["sentences"][1:]):
                self.assertLessEqual(a["end"], b["start"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
