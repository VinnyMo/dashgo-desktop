import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dashcam_finalize import CaptureFinalizer, validate_capture
from dashcam_live import RESERVE_BYTES


def fixture(root, count=2):
    rendered = root / "Rendered"
    rendered.mkdir()
    (root / "session.json").write_text(json.dumps({"state": "stopped"}))
    (rendered / "render.json").write_text(json.dumps({"state": "finished", "completed_segments": count}))
    (rendered / ".capture.shuffled_playlist.m4a").write_bytes(b"playlist")
    for index in range(count):
        (root / f"part_{index:06d}.mkv").write_bytes(b"raw")
        (rendered / f"part_{index:06d}.mp4").write_bytes(b"rendered")


class Process:
    def __init__(self):
        self.stdin = io.BytesIO()
        self.code = None
    def poll(self):
        return self.code
    def wait(self, timeout=None):
        self.code = 0
        return 0
    def kill(self):
        self.code = -1


class FinalizeSafety(unittest.TestCase):
    def test_explicit_recovery_accepts_only_complete_interrupted_render(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            (root / "session.json").write_text(json.dumps({"state": "interrupted"}))
            parts, playlist = validate_capture(root, recover=True)
            self.assertEqual(len(parts), 2)
            self.assertTrue(playlist.exists())
            (root / "Rendered" / "part_000001.mp4").unlink()
            with self.assertRaises(ValueError):
                validate_capture(root, recover=True)

    def test_raw_export_requires_closed_complete_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "session.json").write_text(json.dumps({"state": "stopped"}))
            (root / "part_000000.mkv").write_bytes(b"raw")
            parts, playlist = validate_capture(root, raw_only=True)
            self.assertEqual(len(parts), 1)
            self.assertIsNone(playlist)
            (root / "session.json").write_text(json.dumps({"state": "recording"}))
            with self.assertRaises(ValueError):
                validate_capture(root, raw_only=True, recover=True)

    def test_active_or_interrupted_capture_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            for state in ("recording", "starting", "interrupted", "failed"):
                (root / "session.json").write_text(json.dumps({"state": state}))
                with self.subTest(state=state), self.assertRaises(ValueError):
                    validate_capture(root)

    def test_unfinished_render_and_missing_segment_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            (root / "Rendered" / "render.json").write_text(json.dumps({"state": "waiting", "completed_segments": 2}))
            with self.assertRaises(ValueError):
                validate_capture(root)
            (root / "Rendered" / "render.json").write_text(json.dumps({"state": "finished", "completed_segments": 2}))
            (root / "Rendered" / "part_000001.mp4").unlink()
            with self.assertRaises(ValueError):
                validate_capture(root)

    def test_missing_playlist_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            (root / "Rendered" / ".capture.shuffled_playlist.m4a").unlink()
            with self.assertRaises(ValueError):
                validate_capture(root)

    def test_incompatible_video_rejected_before_output_created(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            with patch("dashcam_finalize.read_rendered_video", side_effect=[
                {"duration": 4, "signature": {"width": 1280}}, {"duration": 4, "signature": {"width": 1920}}]):
                finalizer = CaptureFinalizer(root)
                finalizer.start()
                finalizer.wait()
            self.assertEqual(finalizer.state, "failed")
            self.assertIn("differ", finalizer.reason)
            self.assertEqual(list(root.glob("Finalized_*")), [])

    def test_low_disk_rejected_without_process_or_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            with patch("dashcam_finalize.read_rendered_video", return_value={"duration": 4, "signature": {"codec": "h264"}}), \
                 patch("dashcam_finalize.shutil.disk_usage", return_value=SimpleNamespace(free=0)), \
                 patch("dashcam_finalize.subprocess.Popen") as process:
                finalizer = CaptureFinalizer(root)
                finalizer.start()
                finalizer.wait()
            process.assert_not_called()
            self.assertEqual(finalizer.state, "failed")
            self.assertEqual(list(root.glob("Finalized_*")), [])

    def test_cancel_before_start_preserves_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            finalizer = CaptureFinalizer(root)
            finalizer.stop()
            finalizer.start()
            finalizer.wait()
            self.assertEqual(finalizer.state, "cancelled")
            self.assertEqual((root / "part_000000.mkv").read_bytes(), b"raw")
            self.assertEqual(list(root.glob("Finalized_*")), [])

    def test_disk_failure_during_assembly_stops_owned_process(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            process = Process()
            with patch("dashcam_finalize.read_rendered_video", return_value={"duration": 4, "signature": {"codec": "h264"}}), \
                 patch("dashcam_finalize.media_tool", return_value="ffmpeg"), \
                 patch("dashcam_finalize.shutil.disk_usage", side_effect=[SimpleNamespace(free=RESERVE_BYTES*3), SimpleNamespace(free=0)]), \
                 patch("dashcam_finalize.subprocess.Popen", return_value=process):
                finalizer = CaptureFinalizer(root)
                finalizer.start()
                finalizer.wait()
            self.assertEqual(finalizer.state, "cancelled")
            self.assertIn("disk space", finalizer.reason)
            self.assertIsNotNone(process.poll())
            self.assertTrue(process.stdin.closed)
            self.assertIsNone(finalizer.output)
            self.assertEqual((root / "Rendered" / "part_000000.mp4").read_bytes(), b"rendered")


if __name__ == "__main__":
    unittest.main()
