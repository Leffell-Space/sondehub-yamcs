import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from configure import initialize


class Configure(unittest.TestCase):
    def test_private_configuration_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initialize(root, 'http://127.0.0.1:8090/', 'bridge', 'secret')
            path = root / 'data/secrets.json'
            before = path.read_bytes()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(before)['username'], 'bridge')
            self.assertEqual((root / '.env').read_text(), "YAMCS_URL='http://127.0.0.1:8090'\n")
            with self.assertRaises(FileExistsError):
                initialize(root, 'http://localhost:8090', 'other', 'other')
            self.assertEqual(path.read_bytes(), before)

    def test_reject_unsafe_urls_before_writing(self):
        for url in ['ftp://host', 'http://u:p@host', 'http://host\nEVIL=1',
                    'http://host/$VAR', "http://host/'", 'http://host/?x=1']:
            with self.subTest(url=url), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                with self.assertRaises(ValueError):
                    initialize(root, url, 'bridge', 'secret')
                self.assertFalse((root / 'data').exists())
