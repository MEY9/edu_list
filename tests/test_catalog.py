import copy
import io
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from catalog import ROOT, bucket, load_catalog, load_metrics, load_yaml, local_time, validate, write_json
from build_lists import previous_snapshot, render
from fetch_metrics import fetch_repository, refresh


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config, cls.projects = load_catalog()
        cls.metrics = load_metrics()

    def test_seed_catalog_valid_and_generated(self):
        self.assertEqual([], validate(self.config, self.projects, self.metrics))
        for name, content in render().items():
            self.assertEqual(content, (ROOT / name).read_text(encoding="utf-8"), name)

    def test_threshold_and_review_states(self):
        p = copy.deepcopy(self.projects[0])
        p["status"] = "accepted"
        self.assertEqual("main", bucket(p, {"stars": 1000}, 1000))
        self.assertEqual("watchlist", bucket(p, {"stars": 999}, 1000))
        self.assertEqual("candidates", bucket(p, {}, 1000))
        self.assertEqual("retired", bucket(p, {"stars": 50000, "archived": True}, 1000))
        p["status"] = "candidate"
        self.assertEqual("candidates", bucket(p, {"stars": 100000}, 1000))
        p["status"] = "removed"
        self.assertEqual("retired", bucket(p, {"stars": 100000}, 1000))

    def test_duplicate_repository_case_insensitive(self):
        p = copy.deepcopy(self.projects[0])
        other = copy.deepcopy(p)
        other["github"] = other["github"].upper()
        errors = validate(self.config, [p, other])
        self.assertTrue(any("duplicate repository" in e for e in errors))

    def test_aliases_of_same_repository_rejected(self):
        p, other = copy.deepcopy(self.projects[:2])
        first = self.metrics["repositories"][p["github"].lower()]
        second = dict(first)
        data = {"repositories": {p["github"].lower(): first, other["github"].lower(): second}}
        self.assertTrue(any("canonical id" in e for e in validate(self.config, [p, other], data)))

    def test_unknown_field_and_category_rejected(self):
        p = copy.deepcopy(self.projects[0])
        p["category"] = "typo"
        p["stars"] = 99999
        errors = validate(self.config, [p])
        self.assertTrue(any("unknown" in e for e in errors))
        self.assertTrue(any("category" in e for e in errors))

    def test_duplicate_yaml_key_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.yml"
            path.write_text("status: candidate\nstatus: accepted\n")
            with self.assertRaises(ValueError):
                load_yaml(path)

    def test_invalid_repo_and_review_timestamp_rejected(self):
        p = copy.deepcopy(self.projects[0])
        p["github"] = "owner/../repo"
        self.assertTrue(any("invalid github" in e for e in validate(self.config, [p])))
        p = copy.deepcopy(self.projects[0])
        p["review"]["checked_at"] = "2026-10-05"
        self.assertTrue(any("checked_at" in e for e in validate(self.config, [p])))

    def test_failed_refresh_preserves_counts_and_timestamp(self):
        p = self.projects[0]
        old = copy.deepcopy(self.metrics)
        key = p["github"].lower()
        def fail(repo):
            raise RuntimeError("quota exceeded")
        new, errors = refresh([p], old, fail, "2026-10-06T00:00:00Z")
        self.assertEqual(1, len(errors))
        self.assertEqual(old["repositories"][key]["stars"], new["repositories"][key]["stars"])
        self.assertEqual(old["repositories"][key]["fetched_at"], new["repositories"][key]["fetched_at"])
        self.assertEqual("error", new["repositories"][key]["fetch_status"])
        self.assertEqual("ok", old["repositories"][key]["fetch_status"])

    def test_first_fetch_failure_does_not_fabricate_zero(self):
        def fail(repo):
            raise RuntimeError("not found")
        new, _ = refresh([self.projects[0]], {}, fail, "2026-10-06T00:00:00Z")
        self.assertNotIn("stars", next(iter(new["repositories"].values())))

    def test_transient_network_error_retries(self):
        calls = []
        def opener(req, timeout):
            calls.append(req.full_url)
            if len(calls) == 1:
                raise urllib.error.URLError("temporary")
            return io.StringIO('{"id": 1}')
        self.assertEqual({"id": 1}, fetch_repository("owner/repo", opener=opener, sleeper=lambda _: None))
        self.assertEqual(2, len(calls))

    def test_not_found_does_not_retry_or_leak_token(self):
        calls = []
        def opener(req, timeout):
            calls.append(req.full_url)
            raise urllib.error.HTTPError(req.full_url, 404, "not found", {}, None)
        with self.assertRaises(RuntimeError) as error:
            fetch_repository("owner/repo", token="test-secret", opener=opener, sleeper=lambda _: None)
        self.assertNotIn("test-secret", str(error.exception))
        self.assertEqual(1, len(calls))

    def test_snapshot_ignores_current_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "data/snapshots/2026-09-28.json", {"last_attempt_at": "2026-09-28T02:00:00Z"})
            write_json(root / "data/snapshots/2026-10-05.json", {"last_attempt_at": "2026-10-05T02:00:00Z"})
            previous = previous_snapshot(root, {"last_attempt_at": "2026-10-05T02:00:00Z"})
            self.assertEqual("2026-09-28T02:00:00Z", previous[0])

    def test_generated_main_excludes_pending_low_star_and_retired(self):
        content = render()["README.md"]
        for p in self.projects:
            m = self.metrics["repositories"].get(p["github"].lower(), {})
            if bucket(p, m, self.config["policy"]["min_stars"]) != "main":
                self.assertNotIn("https://github.com/" + p["github"] + ")", content)

    def test_display_dates_use_beijing_time(self):
        self.assertEqual("2026-10-05", local_time("2026-10-04T17:04:00Z", date_only=True))


if __name__ == "__main__":
    unittest.main()
