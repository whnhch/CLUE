"""Tests for the raw-data downloader. None of them touch the network."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from datasource import download


def fake_urlopen(payloads: dict[str, bytes]):
    """Stand-in for urlopen that serves bytes by file name and records calls."""
    calls = []

    def urlopen(url):
        name = url.rsplit("/", 1)[-1]
        calls.append(name)
        return io.BytesIO(payloads[name])

    return urlopen, calls


class TestDownload(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raw_dir = Path(self._tmp.name)
        self.files = {"a.csv": 5, "b.csv": 3}
        patches = (
            mock.patch.object(download, "RAW_DIR", self.raw_dir),
            mock.patch.object(download, "RAW_FILES", self.files),
            mock.patch.object(download, "_log"),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_files_at_pinned_size_are_skipped(self):
        (self.raw_dir / "a.csv").write_bytes(b"12345")
        urlopen, calls = fake_urlopen({"b.csv": b"xyz"})
        with mock.patch.object(download.urllib.request, "urlopen", urlopen):
            download.ensure_raw_data()
        self.assertEqual(calls, ["b.csv"])
        self.assertEqual((self.raw_dir / "b.csv").read_bytes(), b"xyz")

    def test_wrong_size_file_is_refetched(self):
        (self.raw_dir / "a.csv").write_bytes(b"12")
        (self.raw_dir / "b.csv").write_bytes(b"xyz")
        urlopen, calls = fake_urlopen({"a.csv": b"12345"})
        with mock.patch.object(download.urllib.request, "urlopen", urlopen):
            download.ensure_raw_data()
        self.assertEqual(calls, ["a.csv"])

    def test_size_mismatch_fails_and_leaves_nothing_behind(self):
        urlopen, _ = fake_urlopen({"a.csv": b"1234"})
        with mock.patch.object(download.urllib.request, "urlopen", urlopen):
            with self.assertRaises(RuntimeError):
                download.fetch("a.csv")
        self.assertEqual(list(self.raw_dir.iterdir()), [])

    def test_force_refetches_everything(self):
        (self.raw_dir / "a.csv").write_bytes(b"12345")
        (self.raw_dir / "b.csv").write_bytes(b"xyz")
        urlopen, calls = fake_urlopen({"a.csv": b"12345", "b.csv": b"xyz"})
        with mock.patch.object(download.urllib.request, "urlopen", urlopen):
            download.ensure_raw_data(force=True)
        self.assertEqual(sorted(calls), ["a.csv", "b.csv"])


if __name__ == "__main__":
    unittest.main()
