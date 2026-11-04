"""Offline tests for the project-local cockpit importer. No account is contacted."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cockpit.py"
SPEC = importlib.util.spec_from_file_location("project_cockpit_importer", MODULE_PATH)
cockpit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cockpit)


class CockpitImporterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.account = {"uid": "11111111-2222-3333-4444-555555555555", "access_token": "test-access", "refresh_token": "test-refresh"}

    def tearDown(self):
        self.directory.cleanup()

    def write(self, value, name="cockpit.json"):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_valid_seller_array(self):
        self.assertEqual(cockpit.load_files([self.write([self.account])]), [self.account])

    def test_empty_download_rejected(self):
        path = self.root / "empty.json"
        path.touch()
        with self.assertRaisesRegex(ValueError, "0 字节"):
            cockpit.load_files([path])

    def test_single_account_object_is_supported(self):
        self.assertEqual(cockpit.load_files([self.write(self.account)]), [self.account])

    def test_empty_array_rejected(self):
        with self.assertRaisesRegex(ValueError, "非空 JSON 数组"):
            cockpit.load_files([self.write([])])

    def test_missing_required_token_rejected(self):
        with self.assertRaisesRegex(ValueError, "refresh_token"):
            cockpit.load_files([self.write([{key: value for key, value in self.account.items() if key != "refresh_token"}])])

    def test_duplicate_uid_across_files_rejected(self):
        with self.assertRaisesRegex(ValueError, "uid 重复"):
            cockpit.load_files([self.write([self.account], "one.json"), self.write([self.account], "two.json")])

    def test_multiple_files_are_merged_without_credentials_in_request_metadata(self):
        second = dict(self.account, uid="66666666-7777-8888-9999-000000000000")
        accounts = cockpit.load_files([self.write([self.account], "one.json"), self.write([second], "two.json")])
        body, boundary = cockpit.multipart_body(accounts)
        self.assertIn(boundary.encode(), body)
        self.assertIn(b'filename="cockpit-import.json"', body)
        self.assertEqual(json.loads(body.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]), accounts)


if __name__ == "__main__":
    unittest.main()
