#!/usr/bin/env python3
"""Convert local Mihomo rule providers into sing-box source rule sets."""

import argparse
import ipaddress
import json
import re
import sys
from pathlib import Path

import yaml


NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
RULE_FIELDS = {
    "DOMAIN": "domain",
    "DOMAIN-SUFFIX": "domain_suffix",
    "DOMAIN-KEYWORD": "domain_keyword",
    "DOMAIN-REGEX": "domain_regex",
    "IP-CIDR": "ip_cidr",
    "IP-CIDR6": "ip_cidr",
    "SRC-IP-CIDR": "source_ip_cidr",
    "SRC-IP-CIDR6": "source_ip_cidr",
    "PROCESS-NAME": "process_name",
    "PROCESS-PATH": "process_path",
    "DST-PORT": "port",
    "SRC-PORT": "source_port",
    "NETWORK": "network",
}


def fail(location, message):
    raise ValueError(f"{location}: {message}")


def read_lines(path):
    if path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or not isinstance(data.get("payload"), list):
            fail(path, "YAML must contain a payload list")
        for index, value in enumerate(data["payload"], 1):
            if not isinstance(value, str):
                fail(f"{path}:payload[{index}]", "rule must be a string")
            yield f"{path}:payload[{index}]", value.strip()
    else:
        for number, value in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            yield f"{path}:{number}", value.strip()


def checked_domain(value, location):
    if not value or any(char.isspace() for char in value) or "," in value:
        fail(location, "invalid domain")
    return value


def convert_classical(line, location):
    parts = [part.strip() for part in line.split(",")]
    if len(parts) == 3 and parts[0].upper() in {"IP-CIDR", "IP-CIDR6"} and parts[2].lower() == "no-resolve":
        parts.pop()
    if len(parts) != 2 or not all(parts):
        fail(location, "expected TYPE,value without policy (only IP-CIDR/IP-CIDR6 may add no-resolve)")
    kind, value = parts
    field = RULE_FIELDS.get(kind.upper())
    if field is None:
        fail(location, f"unsupported rule type {kind!r}")
    if field in {"domain", "domain_suffix", "domain_keyword"}:
        checked_domain(value, location)
    elif field in {"ip_cidr", "source_ip_cidr"}:
        try:
            value = str(ipaddress.ip_network(value, strict=False))
        except ValueError:
            fail(location, "invalid IP CIDR")
        if kind.upper().endswith("CIDR6") and ":" not in value:
            fail(location, "IP-CIDR6 requires IPv6")
    elif field in {"port", "source_port"}:
        if not value.isdecimal() or not 1 <= int(value) <= 65535:
            fail(location, "port must be between 1 and 65535")
        value = int(value)
    elif field == "network":
        if value.lower() not in {"tcp", "udp"}:
            fail(location, "NETWORK supports tcp or udp")
        value = value.lower()
    return {field: [value]}


def convert_domain(line, location):
    if line.startswith("+."):
        return {"domain_suffix": [checked_domain(line[2:], location)]}
    if line.startswith("."):
        domain = checked_domain(line[1:], location)
        return {"domain_regex": [rf"^.+\.{re.escape(domain)}$"]}
    if "*" in line:
        labels = line.split(".")
        if any(label != "*" and "*" in label for label in labels):
            fail(location, "only whole-label * wildcards are supported")
        if not labels or all(label == "*" for label in labels):
            fail(location, "wildcard must include a fixed domain")
        regex = "\\.".join("[^.]+" if label == "*" else re.escape(checked_domain(label, location)) for label in labels)
        return {"domain_regex": [f"^{regex}$"]}
    return {"domain": [checked_domain(line, location)]}


def convert_ipcidr(line, location):
    try:
        return {"ip_cidr": [str(ipaddress.ip_network(line, strict=False))]}
    except ValueError:
        fail(location, "invalid IP CIDR")


CONVERTERS = {"classical": convert_classical, "domain": convert_domain, "ipcidr": convert_ipcidr}


def convert(manifest, output_dir):
    root = manifest.resolve().parent
    data = json.loads(manifest.read_text(encoding="utf-8"))
    sources = data.get("sources")
    if not isinstance(sources, list):
        fail(manifest, "sources must be a list")
    names = set()
    output_dir.mkdir(parents=True, exist_ok=True)
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"name", "path", "behavior"}:
            fail(manifest, "each source needs name, path, and behavior")
        name, path, behavior = source["name"], source["path"], source["behavior"]
        if not isinstance(name, str) or not NAME_RE.fullmatch(name) or name in names:
            fail(manifest, f"invalid or duplicate name {name!r}")
        if not isinstance(path, str) or not path.startswith("rules/"):
            fail(manifest, f"path must be inside rules/: {path!r}")
        source_path = (root / path).resolve()
        if not source_path.is_relative_to(root / "rules") or not source_path.is_file():
            fail(manifest, f"missing or unsafe source path {path!r}")
        if source_path.suffix.lower() == ".mrs":
            fail(source_path, "binary .mrs files are not supported; use the text or YAML source")
        if behavior not in CONVERTERS:
            fail(manifest, f"unsupported behavior {behavior!r}")
        names.add(name)
        rules = []
        for location, line in read_lines(source_path):
            if line and not line.startswith("#"):
                rules.append(CONVERTERS[behavior](line, location))
        if not rules:
            fail(source_path, "source has no rules")
        target = output_dir / f"{name}.json"
        target.write_text(json.dumps({"version": 2, "rules": rules}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{source_path} -> {target} ({len(rules)} rules)")
    if not sources:
        print("No sources listed; add files under rules/ and entries in sources.json.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("sources.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    args = parser.parse_args()
    try:
        convert(args.manifest, args.output_dir)
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
