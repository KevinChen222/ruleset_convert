import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from mrs_converter.convert import STATE_FILE, convert, is_due, load_sources, normalize_rule


class MrsConverterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest = self.root / "mrs-sources.json"
        self.output = self.root / "mrs"
        self.now = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)
        self.compiled = {}

    def configure(self, sources):
        self.manifest.write_text(json.dumps({"sources": sources}), encoding="utf-8")

    def source(self, name="Claude", urls=None, behavior="classical"):
        return {"name": name, "urls": urls or ["https://example.com/rules.yaml"], "behavior": behavior}

    def compiler(self, command, check):
        self.assertTrue(check)
        self.assertEqual(command[:2], ["mihomo", "convert-ruleset"])
        self.assertEqual(command[3], "text")
        content = Path(command[4]).read_text(encoding="utf-8")
        self.compiled[Path(command[5]).name] = (command[2], content)
        Path(command[5]).write_bytes(b"MRS-test-data")

    def run_conversion(self, downloads):
        def download(url, timeout):
            self.assertEqual(timeout, 30)
            return BytesIO(downloads[url].encode("utf-8"))

        with patch("mrs_converter.convert.urlopen", side_effect=download), patch(
            "mrs_converter.convert.subprocess.run", side_effect=self.compiler
        ):
            convert(self.manifest, self.output, now=self.now)

    def test_claude_preserves_exact_domain_and_suffix_semantics(self):
        self.configure([self.source()])
        self.run_conversion({"https://example.com/rules.yaml": (
            "payload:\n"
            "  - DOMAIN,cdn.usefathom.com\n"
            "  - DOMAIN-SUFFIX,anthropic.com\n"
            "  - DOMAIN-SUFFIX,claude.ai\n"
        )})
        self.assertEqual(self.compiled, {"Claude.domain.mrs": (
            "domain", "+.anthropic.com\n+.claude.ai\ncdn.usefathom.com\n"
        )})
        self.assertEqual((self.output / STATE_FILE).read_text().strip(), self.now.isoformat())

    def test_merges_urls_deduplicates_and_splits_mixed_rules(self):
        self.configure([
            self.source("Mixed", ["https://example.com/a.txt", "https://example.com/b.yaml"]),
            self.source("Other", ["https://example.com/domain.txt"], "domain"),
        ])
        self.run_conversion({
            "https://example.com/a.txt": "# rules\nDOMAIN,example.com\nIP-CIDR,192.0.2.7/24,no-resolve\n",
            "https://example.com/b.yaml": "payload:\n  - DOMAIN,example.com\n  - IP-CIDR6,2001:db8::/32\n",
            "https://example.com/domain.txt": "+.example.org\n*.example.net\n",
        })
        self.assertEqual(self.compiled["Mixed.domain.mrs"], ("domain", "example.com\n"))
        self.assertEqual(self.compiled["Mixed.ipcidr.mrs"], ("ipcidr", "192.0.2.0/24\n2001:db8::/32\n"))
        self.assertEqual(self.compiled["Other.domain.mrs"], ("domain", "*.example.net\n+.example.org\n"))

    def test_failure_in_later_source_preserves_all_published_files_and_timestamp(self):
        self.output.mkdir()
        (self.output / "Claude.domain.mrs").write_bytes(b"previous")
        (self.output / STATE_FILE).write_text(self.now.isoformat())
        self.configure([
            self.source(urls=["https://example.com/a.txt"]),
            self.source("Unsupported", ["https://example.com/b.txt"]),
        ])
        with self.assertRaisesRegex(ValueError, "b.txt:1:.*cannot be represented"):
            self.run_conversion({
                "https://example.com/a.txt": "DOMAIN,new.example.com\n",
                "https://example.com/b.txt": "DOMAIN-KEYWORD,example\n",
            })
        self.assertEqual((self.output / "Claude.domain.mrs").read_bytes(), b"previous")
        self.assertEqual((self.output / STATE_FILE).read_text(), self.now.isoformat())

    def test_download_failure_does_not_publish(self):
        self.configure([self.source()])
        with patch("mrs_converter.convert.urlopen", side_effect=OSError("download failed")):
            with self.assertRaisesRegex(OSError, "download failed"):
                convert(self.manifest, self.output)
        self.assertFalse(self.output.exists())

    def test_failed_compiler_does_not_publish(self):
        self.configure([self.source()])
        with patch("mrs_converter.convert.urlopen", return_value=BytesIO(b"payload: ['DOMAIN,example.com']")), patch(
            "mrs_converter.convert.subprocess.run", side_effect=subprocess.CalledProcessError(1, "mihomo")
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                convert(self.manifest, self.output)
        self.assertFalse(self.output.exists())

    def test_empty_compiler_output_does_not_publish(self):
        self.configure([self.source()])
        with patch("mrs_converter.convert.urlopen", return_value=BytesIO(b"payload: ['DOMAIN,example.com']")), patch(
            "mrs_converter.convert.subprocess.run"
        ):
            with self.assertRaisesRegex(ValueError, "no MRS file"):
                convert(self.manifest, self.output)
        self.assertFalse(self.output.exists())

    def test_success_cleans_stale_mrs_and_preserves_other_files(self):
        self.output.mkdir()
        (self.output / "Old.domain.mrs").write_bytes(b"old")
        (self.output / "notes.txt").write_text("notes")
        self.configure([self.source()])
        self.run_conversion({"https://example.com/rules.yaml": "payload: ['DOMAIN,example.com']"})
        self.assertFalse((self.output / "Old.domain.mrs").exists())
        self.assertEqual((self.output / "notes.txt").read_text(), "notes")

    def test_empty_or_invalid_yaml_source_does_not_publish(self):
        self.configure([self.source()])
        for content in ("payload: []", "payload: [123]", "rules: []", "<html>error</html>"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.run_conversion({"https://example.com/rules.yaml": content})
            self.assertFalse(self.output.exists())

    def test_invalid_manifest_names_urls_and_behaviors_are_rejected(self):
        invalid_sources = [
            [],
            [self.source("../escape")],
            [self.source(), self.source("claude")],
            [self.source(behavior="unknown")],
            [dict(self.source(), urls=[])],
            [self.source(urls=["http://example.com/a.txt"])],
            [self.source(urls=["file:///etc/passwd"])],
            [self.source(urls=["https://user:password@example.com/a.txt"])],
            [self.source(urls=["https://github.com/owner/repo"])],
        ]
        for sources in invalid_sources:
            with self.subTest(sources=sources):
                self.configure(sources)
                with self.assertRaises(ValueError):
                    load_sources(self.manifest)

    def test_github_page_is_downloaded_as_raw_yaml(self):
        self.configure([self.source(urls=["https://github.com/owner/repo/blob/main/domains.yaml"])])
        self.run_conversion({"https://raw.githubusercontent.com/owner/repo/main/domains.yaml": "payload: ['DOMAIN,example.com']"})
        self.assertIn("Claude.domain.mrs", self.compiled)

    def test_unsupported_rules_policies_and_invalid_values_are_rejected(self):
        for line in (
            "DOMAIN-REGEX,.*example.com", "PROCESS-NAME,app", "DST-PORT,443", "GEOIP,CN",
            "DOMAIN,example.com,DIRECT", "IP-CIDR,192.0.2.0/24,PROXY",
            "DOMAIN,*.example.com", "DOMAIN-SUFFIX,+.example.com", "DOMAIN,https://example.com",
            "DOMAIN,example..com", "IP-CIDR6,192.0.2.0/24", "IP-CIDR,invalid",
        ):
            with self.subTest(line=line), self.assertRaises(ValueError):
                normalize_rule(line, "classical")

    def test_native_domain_and_ipcidr_rules(self):
        for domain in ("example.com", "+.example.com", ".example.com", "*.example.com"):
            self.assertEqual(normalize_rule(domain, "domain"), ("domain", domain))
        self.assertEqual(normalize_rule("192.0.2.7/24", "ipcidr"), ("ipcidr", "192.0.2.0/24"))
        self.assertEqual(normalize_rule("IP-CIDR6,2001:db8::/32,NO-RESOLVE", "classical"), ("ipcidr", "2001:db8::/32"))

    def test_schedule_first_run_and_25_hour_boundary(self):
        self.assertTrue(is_due(self.output, self.now))
        self.output.mkdir()
        (self.output / STATE_FILE).write_text(self.now.isoformat())
        self.assertFalse(is_due(self.output, self.now + timedelta(hours=24, minutes=59, seconds=59)))
        self.assertTrue(is_due(self.output, self.now + timedelta(hours=25)))
        self.assertTrue(is_due(self.output, self.now + timedelta(hours=26)))

    def test_invalid_schedule_state_reports_error(self):
        self.output.mkdir()
        for timestamp in ("invalid", "2026-11-11T12:00:00"):
            with self.subTest(timestamp=timestamp):
                (self.output / STATE_FILE).write_text(timestamp)
                with self.assertRaises(ValueError):
                    is_due(self.output, self.now)


if __name__ == "__main__":
    unittest.main()
