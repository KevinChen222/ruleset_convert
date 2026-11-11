#!/usr/bin/env python3
"""Download rule providers and compile domain and IP CIDR MRS files."""

import argparse
import ipaddress
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen

import yaml


NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
INTERVAL = timedelta(hours=25)
STATE_FILE = ".last-success"


def is_due(output_dir, now=None):
    state = output_dir / STATE_FILE
    if not state.exists():
        return True
    last = datetime.fromisoformat(state.read_text(encoding="utf-8").strip())
    if last.tzinfo is None:
        raise ValueError(f"{state}: timestamp must include a timezone")
    return (now or datetime.now(timezone.utc)) - last >= INTERVAL


def source_url(value):
    if not isinstance(value, str):
        raise ValueError("source URL must be an HTTPS file URL")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("source URL must be an HTTPS file URL without credentials or fragment")
    if parsed.hostname == "github.com":
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 5 or parts[2] not in {"blob", "raw"}:
            raise ValueError("GitHub URL must point to a file under blob/ or raw/")
        parsed = parsed._replace(netloc="raw.githubusercontent.com", path="/" + "/".join(parts[:2] + parts[3:]))
    return urlunsplit(parsed)


def read_rules(url):
    with urlopen(url, timeout=30) as response:
        content = response.read().decode("utf-8-sig")
    if Path(urlsplit(url).path).suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(content)
        if not isinstance(data, dict) or not isinstance(data.get("payload"), list):
            raise ValueError(f"{url}: YAML must contain a payload list")
        lines = data["payload"]
    else:
        lines = content.splitlines()
    for index, line in enumerate(lines, 1):
        location = f"{url}:{index}"
        if not isinstance(line, str):
            raise ValueError(f"{location}: rule must be a string")
        line = line.strip()
        if line and not line.startswith("#"):
            yield location, line


def domain_value(value, wildcards=False):
    bare = value
    if wildcards:
        bare = bare.removeprefix("+.").removeprefix(".")
    if not bare or any(c.isspace() or c in ",/:\\#+" for c in bare):
        raise ValueError("invalid domain")
    for label in bare.split("."):
        if not label or ("*" in label and not (wildcards and label == "*")):
            raise ValueError("invalid domain label or wildcard")
    return value


def normalize_rule(line, behavior):
    if behavior == "domain":
        return "domain", domain_value(line, wildcards=True)
    if behavior == "ipcidr":
        return "ipcidr", str(ipaddress.ip_network(line, strict=False))
    parts = [part.strip() for part in line.split(",")]
    kind = parts[0].upper()
    if len(parts) == 3 and kind in {"IP-CIDR", "IP-CIDR6"} and parts[2].lower() == "no-resolve":
        parts.pop()
    if len(parts) != 2 or not all(parts):
        raise ValueError("expected TYPE,value; only IP-CIDR/IP-CIDR6 may add no-resolve")
    value = parts[1]
    if kind in {"DOMAIN", "DOMAIN-SUFFIX"}:
        value = domain_value(value)
        return "domain", ("+." if kind == "DOMAIN-SUFFIX" else "") + value
    if kind in {"IP-CIDR", "IP-CIDR6"}:
        network = ipaddress.ip_network(value, strict=False)
        if kind == "IP-CIDR6" and network.version != 6:
            raise ValueError("IP-CIDR6 requires IPv6")
        return "ipcidr", str(network)
    raise ValueError(f"rule type {kind!r} cannot be represented in MRS")


def load_sources(manifest):
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list) or not data["sources"]:
        raise ValueError(f"{manifest}: sources must be a nonempty list")
    names = set()
    sources = []
    for source in data["sources"]:
        if not isinstance(source, dict) or set(source) != {"name", "urls", "behavior"}:
            raise ValueError(f"{manifest}: each source needs name, urls, and behavior")
        name, behavior, urls = source["name"], source["behavior"], source["urls"]
        if not isinstance(name, str) or not NAME_RE.fullmatch(name) or name.casefold() in names:
            raise ValueError(f"{manifest}: invalid or duplicate name {name!r}")
        if behavior not in ("classical", "domain", "ipcidr"):
            raise ValueError(f"{manifest}: unsupported behavior {behavior!r}")
        if not isinstance(urls, list) or not urls:
            raise ValueError(f"{manifest}: urls must be a nonempty list")
        names.add(name.casefold())
        sources.append((name, behavior, [source_url(url) for url in urls]))
    return sources


def convert(manifest, output_dir, mihomo="mihomo", now=None):
    sources = load_sources(manifest)
    with tempfile.TemporaryDirectory(prefix="mrs-convert-") as temporary:
        staging = Path(temporary)
        for name, behavior, urls in sources:
            groups = {"domain": set(), "ipcidr": set()}
            for url in urls:
                count = 0
                for location, line in read_rules(url):
                    try:
                        kind, value = normalize_rule(line, behavior)
                    except ValueError as error:
                        raise ValueError(f"{location}: {error}") from error
                    groups[kind].add(value)
                    count += 1
                if not count:
                    raise ValueError(f"{url}: source has no rules")
            for kind, values in groups.items():
                if not values:
                    continue
                source = staging / f"{name}.{kind}.txt"
                target = staging / f"{name}.{kind}.mrs"
                source.write_text("\n".join(sorted(values)) + "\n", encoding="utf-8")
                subprocess.run([str(mihomo), "convert-ruleset", kind, "text", str(source), str(target)], check=True)
                if not target.is_file() or target.stat().st_size == 0:
                    raise ValueError(f"{target.name}: compiler produced no MRS file")
                print(f"{target.name}: {len(values)} rules from {len(urls)} source(s)")
        output_dir.mkdir(parents=True, exist_ok=True)
        targets = list(staging.glob("*.mrs"))
        for target in targets:
            (output_dir / target.name).write_bytes(target.read_bytes())
        expected = {target.name for target in targets}
        for target in output_dir.glob("*.mrs"):
            if target.name not in expected:
                target.unlink()
        updated_at = now or datetime.now(timezone.utc)
        (output_dir / STATE_FILE).write_text(updated_at.isoformat() + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("mrs-sources.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("mrs"))
    parser.add_argument("--mihomo", default="mihomo")
    parser.add_argument("--check-due", action="store_true")
    args = parser.parse_args()
    try:
        if args.check_due:
            print("true" if is_due(args.output_dir) else "false")
        else:
            convert(args.manifest, args.output_dir, args.mihomo)
    except (OSError, ValueError, yaml.YAMLError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
