import tempfile
import unittest
from pathlib import Path
from app.main import parse_subtitle_file, fallback_segments, safe_name

class ClipForgeParserTests(unittest.TestCase):
    def test_parse_srt(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'sample.srt'
            p.write_text('1\n00:00:01,000 --> 00:00:02,500\nHello ClipForge\n',encoding='utf-8')
            rows=parse_subtitle_file(p)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['text'],'Hello ClipForge')
        self.assertAlmostEqual(rows[0]['start'],1.0)
        self.assertAlmostEqual(rows[0]['end'],2.5)

    def test_parse_vtt(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'sample.vtt'
            p.write_text('WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nA VTT caption\n',encoding='utf-8')
            rows=parse_subtitle_file(p)
        self.assertEqual(rows[0]['text'],'A VTT caption')

    def test_fallback_is_bounded(self):
        clips=fallback_segments(120,3,30,[])
        self.assertLessEqual(len(clips),3)
        for clip in clips:
            self.assertGreaterEqual(clip['start'],0)
            self.assertLessEqual(clip['end'],120)
            self.assertGreater(clip['end'],clip['start'])

    def test_safe_name(self):
        self.assertEqual(safe_name('../../My video!!.mp4'),'My_video')

if __name__=='__main__': unittest.main()
