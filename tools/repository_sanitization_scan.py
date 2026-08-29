"""Scan tracked content and reachable Git blobs without echoing sensitive values.

Private research markers are supplied at runtime and are never persisted by this
tool.  Reports contain only category counts, repository-relative location hashes,
and redacted content fingerprints.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import re
import subprocess
import tarfile
import zipfile
from collections import Counter
from pathlib import Path


TEXT_LIMIT = 16 * 1024 * 1024
REPORT_PREFIX = "output/repository_sanitization/"


def _git(*args: str, text: bool = False) -> bytes | str:
    if text:
        return subprocess.check_output(
            ["git", *args], text=True, encoding="utf-8", errors="surrogateescape"
        )
    return subprocess.check_output(["git", *args])


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]


def _decode(payload: bytes) -> str | None:
    if len(payload) > TEXT_LIMIT or b"\x00" in payload[:8192]:
        return None
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return payload.decode("utf-16")
        except UnicodeDecodeError:
            return None


def _patterns(markers: list[str]) -> list[tuple[str, re.Pattern[str]]]:
    values: list[tuple[str, str]] = [
        ("WINDOWS_ABSOLUTE_PATH", r"(?<![A-Za-z0-9_])[A-Z]:[\\/](?![<>])"),
        ("POSIX_HOME_PATH", r"(?i)(?:/home/|/Users/)[^/\s]+/"),
        ("PRIVATE_KEY_HEADER", r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        ("LIKELY_CREDENTIAL", r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*['\"][^'\"\s]{8,}"),
    ]
    values.extend(("PRIVATE_RESEARCH_MARKER", re.escape(marker)) for marker in markers if marker)
    return [(category, re.compile(pattern)) for category, pattern in values]


def _scan_text(text: str, identity: str, patterns: list[tuple[str, re.Pattern[str]]]) -> list[dict[str, str | int]]:
    hits: list[dict[str, str | int]] = []
    newlines = [index for index, char in enumerate(text) if char == "\n"]
    for category, pattern in patterns:
        for match in pattern.finditer(text):
            line = bisect.bisect_left(newlines, match.start()) + 1
            hits.append({
                "category": category,
                "location_hash": _fingerprint(identity),
                "line": line,
                "redacted_fingerprint": _fingerprint(match.group(0)),
            })
    return hits


def _summary(scope: str, scanned: int, binaries: int, hits: list[dict[str, str | int]]) -> dict[str, object]:
    counts = Counter(str(item["category"]) for item in hits)
    return {
        "schema_version": "1.0",
        "scope": scope,
        "files_or_blobs_scanned": scanned,
        "binary_or_oversize_skipped": binaries,
        "hit_count": len(hits),
        "category_counts": dict(sorted(counts.items())),
        "hits": hits,
    }


def scan_current(root: Path, patterns: list[tuple[str, re.Pattern[str]]]) -> dict[str, object]:
    paths = _git("ls-files", "-z").split(b"\0")
    hits: list[dict[str, str | int]] = []
    scanned = binaries = 0
    for raw in paths:
        if not raw:
            continue
        rel = raw.decode("utf-8", errors="surrogateescape")
        if rel.startswith(REPORT_PREFIX) or rel == "tools/repository_sanitization_scan.py":
            continue
        candidate = root / rel
        if not candidate.is_file():
            continue
        payload = candidate.read_bytes()
        text = _decode(payload)
        if text is None:
            binaries += 1
            continue
        scanned += 1
        hits.extend(_scan_text(text, rel, patterns))
    return _summary("CURRENT_TRACKED_TREE", scanned, binaries, hits)


def scan_history(patterns: list[tuple[str, re.Pattern[str]]]) -> dict[str, object]:
    objects = _git("rev-list", "--objects", "--all", text=True).splitlines()
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for record in objects:
        object_id, _, path = record.partition(" ")
        if (not path or object_id in seen or path.startswith(REPORT_PREFIX)
                or path == "tools/repository_sanitization_scan.py"):
            continue
        seen.add(object_id)
        entries.append((object_id, path))
    hits: list[dict[str, str | int]] = []
    scanned = binaries = 0
    process = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    request = "".join(f"{object_id}\n" for object_id, _ in entries).encode("ascii")
    batch_output, _ = process.communicate(input=request)
    offset = 0
    for requested_id, path in entries:
        header_end = batch_output.find(b"\n", offset)
        if header_end < 0:
            break
        header = batch_output[offset:header_end].decode("ascii", errors="replace").strip()
        offset = header_end + 1
        fields = header.split()
        if len(fields) < 3 or fields[1] == "missing":
            continue
        object_id, object_type, raw_size = fields[:3]
        size = int(raw_size)
        payload = batch_output[offset:offset + size]
        offset += size + 1
        if object_type != "blob":
            continue
        text = _decode(payload)
        if text is None:
            binaries += 1
            continue
        scanned += 1
        hits.extend(_scan_text(text, f"{requested_id}:{path}", patterns))
    report = _summary("ALL_REACHABLE_GIT_BLOBS", scanned, binaries, hits)
    report["refs_scanned"] = len(_git("for-each-ref", "--format=%(refname)", text=True).splitlines())
    report["commits_scanned"] = int(_git("rev-list", "--all", "--count", text=True).strip())
    return report


def scan_archives(paths: list[Path], patterns: list[tuple[str, re.Pattern[str]]]) -> dict[str, object]:
    """Scan wheel/zip and source-tar members without extracting them."""
    hits: list[dict[str, str | int]] = []
    scanned = binaries = 0
    for path in paths:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                members = ((item.filename, archive.read(item)) for item in archive.infolist() if not item.is_dir())
                for name, payload in members:
                    text = _decode(payload)
                    if text is None:
                        binaries += 1
                    else:
                        scanned += 1
                        hits.extend(_scan_text(text, f"{path.name}:{name}", patterns))
        elif tarfile.is_tarfile(path):
            with tarfile.open(path) as archive:
                for item in archive.getmembers():
                    handle = archive.extractfile(item) if item.isfile() else None
                    if handle is None:
                        continue
                    text = _decode(handle.read())
                    if text is None:
                        binaries += 1
                    else:
                        scanned += 1
                        hits.extend(_scan_text(text, f"{path.name}:{item.name}", patterns))
        else:
            raise ValueError(f"unsupported archive: {path.name}")
    report = _summary("BUILT_DISTRIBUTION_ARCHIVES", scanned, binaries, hits)
    report["archives_scanned"] = len(paths)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=("current", "history", "both"), default="both")
    parser.add_argument("--private-marker", action="append", default=[])
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--archive", action="append", type=Path, default=[])
    parser.add_argument("--fail-on-hit", action="store_true")
    args = parser.parse_args()
    patterns = _patterns(args.private_marker)
    root = Path.cwd()
    result: dict[str, object] = {"schema_version": "1.0"}
    if args.scope in {"current", "both"}:
        result["current"] = scan_current(root, patterns)
    if args.scope in {"history", "both"}:
        result["history"] = scan_history(patterns)
    if args.archive:
        result["packages"] = scan_archives(args.archive, patterns)
    if args.summary_only:
        for value in result.values():
            if isinstance(value, dict):
                value.pop("hits", None)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    hit_count = sum(int(value.get("hit_count", 0)) for value in result.values()
                    if isinstance(value, dict))
    return int(args.fail_on_hit and hit_count > 0)


if __name__ == "__main__":
    raise SystemExit(main())
