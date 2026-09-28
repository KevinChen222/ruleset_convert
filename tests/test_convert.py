import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from scripts.convert import convert


class ConverterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "rules").mkdir()

    def run_source(self, filename, content, behavior):
        (self.root / "rules" / filename).write_text(content, encoding="utf-8")
        manifest = self.root / "sources.json"
        manifest.write_text(json.dumps({"sources": [{"name": "sample", "path": f"rules/{filename}", "behavior": behavior}]}), encoding="utf-8")
        convert(manifest, self.root / "dist")
        return json.loads((self.root / "dist" / "sample.json").read_text(encoding="utf-8"))

    def test_classical_text_preserves_independent_rules(self):
        result = self.run_source("sample.list", "DOMAIN-SUFFIX,example.com\nIP-CIDR,192.0.2.1/24\nDST-PORT,443\n", "classical")
        self.assertEqual(result, {"version": 2, "rules": [
            {"domain_suffix": ["example.com"]},
            {"ip_cidr": ["192.0.2.0/24"]},
            {"port": [443]},
        ]})

    def test_yaml_payload_and_domain_wildcards(self):
        result = self.run_source("sample.yaml", "payload:\n  - '+.example.com'\n  - '.example.org'\n  - '*.example.net'\n", "domain")
        self.assertEqual(result["rules"], [
            {"domain_suffix": ["example.com"]},
            {"domain_regex": [r"^.+\.example\.org$"]},
            {"domain_regex": [r"^[^.]+\.example\.net$"]},
        ])

    def test_unsupported_type_fails_instead_of_dropping_rule(self):
        with self.assertRaisesRegex(ValueError, "sample.list:2: unsupported rule type 'GEOIP'"):
            self.run_source("sample.list", "DOMAIN,example.com\nGEOIP,CN\n", "classical")

    def test_ip_no_resolve_suffix_is_removed(self):
        result = self.run_source("sample.list", "IP-CIDR,192.0.2.0/24,no-resolve\nIP-CIDR6,2001:db8::/32,NO-RESOLVE\n", "classical")
        self.assertEqual(result["rules"], [
            {"ip_cidr": ["192.0.2.0/24"]},
            {"ip_cidr": ["2001:db8::/32"]},
        ])

    def test_policy_suffix_still_fails(self):
        with self.assertRaisesRegex(ValueError, "without policy"):
            self.run_source("sample.list", "IP-CIDR,192.0.2.0/24,DIRECT\n", "classical")

    def test_github_file_url_downloads_and_converts(self):
        url = "https://github.com/other/rules/blob/main/deny.list"
        manifest = self.root / "sources.json"
        manifest.write_text(json.dumps({"sources": [{"name": "deny", "url": url, "behavior": "classical"}]}), encoding="utf-8")
        with patch("scripts.convert.urlopen", return_value=BytesIO(b"IP-CIDR,192.0.2.1/24,no-resolve\n")) as download:
            convert(manifest, self.root / "dist")
        download.assert_called_once_with("https://github.com/other/rules/raw/main/deny.list", timeout=20)
        result = json.loads((self.root / "dist" / "deny.json").read_text(encoding="utf-8"))
        self.assertEqual(result["rules"], [{"ip_cidr": ["192.0.2.0/24"]}])

    def test_github_raw_yaml_url(self):
        url = "https://raw.githubusercontent.com/other/rules/main/domains.yaml"
        manifest = self.root / "sources.json"
        manifest.write_text(json.dumps({"sources": [{"name": "domains", "url": url, "behavior": "domain"}]}), encoding="utf-8")
        with patch("scripts.convert.urlopen", return_value=BytesIO(b"payload:\n  - '+.example.com'\n")):
            convert(manifest, self.root / "dist")
        result = json.loads((self.root / "dist" / "domains.json").read_text(encoding="utf-8"))
        self.assertEqual(result["rules"], [{"domain_suffix": ["example.com"]}])

    def test_non_github_url_is_rejected(self):
        manifest = self.root / "sources.json"
        manifest.write_text(json.dumps({"sources": [{"name": "other", "url": "https://example.com/rules.list", "behavior": "classical"}]}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "GitHub HTTPS file URL"):
            convert(manifest, self.root / "dist")

    def test_source_cannot_escape_rules_directory(self):
        (self.root / "outside.list").write_text("DOMAIN,example.com\n", encoding="utf-8")
        manifest = self.root / "sources.json"
        manifest.write_text(json.dumps({"sources": [{"name": "sample", "path": "rules/../outside.list", "behavior": "classical"}]}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unsafe source path"):
            convert(manifest, self.root / "dist")


if __name__ == "__main__":
    unittest.main()
