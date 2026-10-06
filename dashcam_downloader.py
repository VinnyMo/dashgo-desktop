#!/usr/bin/env python3
"""Read-only downloader for the NEXPOW VSQ10 / DashGo HTTP API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import dashcam_process as subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from dashcam_history import DownloadHistory
from dashcam_paths import DATA_DIR

PAGE_SIZE = 100
CHUNK_SIZE = 1024 * 1024
# Camera traffic is link-local LAN traffic. Do not inherit a system/environment
# HTTP proxy, which can otherwise divert 192.168.169.1 to a localhost proxy.
DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass(frozen=True)
class Recording:
    remote_path: str
    size: int
    created: int

    @property
    def filename(self) -> str:
        return PurePosixPath(self.remote_path).name

    @property
    def is_front(self) -> bool:
        path = self.remote_path.lower()
        return "/video_front/" in path or self.filename.lower().endswith("_f.ts")


def request(url: str, *, headers: dict[str, str] | None = None, timeout: int = 15):
    return DIRECT_OPENER.open(
        urllib.request.Request(url, headers=headers or {}, method="GET"), timeout=timeout
    )


def get_json(url: str, timeout: int = 15) -> dict:
    with request(url, timeout=timeout) as response:
        raw = response.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        preview = raw[:200].decode("utf-8", "replace")
        raise RuntimeError(f"Invalid JSON from {url}: {preview!r}") from exc


def gateway_candidates() -> list[str]:
    """Return IPv4 gateways from Windows' route table, independent of route priority."""
    completed = subprocess.run(
        ["route", "print", "-4"], capture_output=True, text=True, timeout=10,
        encoding="utf-8", errors="replace"
    )
    candidates: list[str] = []
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0] == "0.0.0.0" and fields[1] == "0.0.0.0":
            gateway = fields[2]
            if gateway not in candidates:
                candidates.append(gateway)
    # Known factory default is only a final fallback, not the primary assumption.
    if "192.168.169.1" not in candidates:
        candidates.append("192.168.169.1")
    return candidates


def discover_camera(timeout: int) -> str:
    attempts: list[str] = []
    for gateway in gateway_candidates():
        base_url = f"http://{gateway}"
        attempts.append(base_url)
        try:
            data = get_json(f"{base_url}/app/getdeviceattr", min(timeout, 3))
            info = data.get("info") or {}
            if data.get("result") == 0 and ("softver" in info or "camnum" in info):
                return base_url
        except (OSError, urllib.error.URLError, RuntimeError):
            continue
    raise RuntimeError("DashGo camera not found at gateways: " + ", ".join(attempts))


def list_recordings(base_url: str, folder: str, timeout: int) -> list[Recording]:
    """Page through a changing live index and deduplicate by full remote path."""
    found: dict[str, Recording] = {}
    start = 0
    while True:
        query = urllib.parse.urlencode(
            {"folder": folder, "start": start, "end": start + PAGE_SIZE - 1}
        )
        data = get_json(f"{base_url}/app/getfilelist?{query}", timeout)
        if data.get("result") != 0:
            raise RuntimeError(f"getfilelist failed: {data!r}")
        page: list[dict] = []
        for group in data.get("info") or []:
            page.extend(group.get("files") or [])
        for item in page:
            remote = str(item["name"])
            found[remote] = Recording(
                remote_path=remote,
                size=int(item["size"]) * 1024,  # approximate: API reports whole KiB
                created=int(item.get("createtime", 0)),
            )
        print(f"Indexed {len(found):,} unique files...", file=sys.stderr)
        if len(page) < PAGE_SIZE:
            break
        start += PAGE_SIZE
        if start > 100_000:
            raise RuntimeError("Refusing implausibly large camera index")
    return sorted(found.values(), key=lambda item: (item.created, item.remote_path))


def human_size(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    raise AssertionError("unreachable")


PROGRESS = {"done": 0, "total": 0, "started": 0.0, "last": 0.0}


def show_progress(name: str, current: int, total: int, started: float) -> None:
    now = time.monotonic()
    if now - PROGRESS['last'] < 0.5 and current < total:
        return
    PROGRESS['last'] = now
    done = min(PROGRESS['total'], PROGRESS['done'] + current)
    elapsed = max(now - PROGRESS['started'], 0.001)
    rate = done / elapsed
    remaining = max(0, PROGRESS['total'] - done)
    print('PROGRESS ' + json.dumps({'done': done, 'total': PROGRESS['total'],
          'percent': done * 100 / PROGRESS['total'] if PROGRESS['total'] else 100,
          'eta_seconds': remaining / rate if rate > 0 and elapsed > 2 else None}), flush=True)


def download_one(
    base_url: str,
    recording: Recording,
    destination: Path,
    timeout: int,
    replace_mismatched: bool,
) -> str:
    final_path = destination / recording.filename
    partial_path = final_path.with_name(final_path.name + ".part")
    if final_path.exists():
        actual = final_path.stat().st_size
        # Index sizes are whole-KiB approximations, so allow the final partial KiB.
        if abs(actual - recording.size) < 1024:
            return "existing"
        if not replace_mismatched:
            print(
                f"WARNING: {final_path} is {actual} bytes; expected {recording.size}. "
                "Use --replace-mismatched to replace it.",
                file=sys.stderr,
            )
            return "mismatched"

    url = base_url + urllib.parse.quote(recording.remote_path, safe="/")
    offset = partial_path.stat().st_size if partial_path.exists() else 0
    headers = {"Range": f"bytes={offset}-"} if offset > 0 else {}
    response = request(url, headers=headers, timeout=timeout)
    try:
        status = response.status
        if offset and status != 206:
            # VSQ10 responds 200 and then stalls for Range. Reconnect without it.
            response.close()
            offset = 0
            response = request(url, timeout=timeout)
            status = response.status
        if status not in (200, 206):
            raise RuntimeError(f"Unexpected HTTP {status} for {url}")
        length = response.headers.get("Content-Length")
        expected_total = offset + int(length) if length is not None else recording.size
        downloaded = offset
        started = time.monotonic()
        with partial_path.open("ab" if offset else "wb") as output:
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)
                show_progress(recording.filename, downloaded, expected_total, started)
            output.flush()
            os.fsync(output.fileno())
        print()
    finally:
        response.close()

    actual = partial_path.stat().st_size
    if actual != expected_total:
        raise RuntimeError(
            f"Incomplete {recording.filename}: got {actual}, expected {expected_total}; "
            f"kept {partial_path.name}"
        )
    os.replace(partial_path, final_path)
    return "downloaded"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--camera", help="camera base URL; default discovers it from Windows gateways"
    )
    parser.add_argument("--folder", default="loop", help="camera recording category")
    parser.add_argument(
        "--output", type=Path, default=DATA_DIR / "Transfers",
        help="download directory (default: %(default)s)"
    )
    parser.add_argument("--download", action="store_true", help="download; default is list-only")
    parser.add_argument(
        "--quiet-list", action="store_true",
        help="show only the list summary in list-only mode"
    )
    parser.add_argument(
        "--skip-newest", type=int, default=2,
        help="skip newest front clips which may still be recording (default: 2)"
    )
    parser.add_argument("--timeout", type=int, default=15, help="socket timeout seconds")
    parser.add_argument(
        "--replace-mismatched", action="store_true",
        help="replace a final local file whose size differs from camera metadata"
    )
    parser.add_argument(
        "--history", type=Path,
        help="SQLite history path (default: OUTPUT/.dashcam_history.sqlite3)"
    )
    parser.add_argument(
        "--redownload-missing", action="store_true",
        help="download again when history says complete but the local TS was deleted"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.camera and not args.camera.startswith(("http://", "https://")):
        raise SystemExit("--camera must be an http:// or https:// URL")
    if args.skip_newest < 0:
        raise SystemExit("--skip-newest cannot be negative")
    try:
        base_url = args.camera.rstrip("/") if args.camera else discover_camera(args.timeout)
        print(f"Camera URL: {base_url}")
        device = get_json(f"{base_url}/app/getdeviceattr", args.timeout)
        info = device.get("info") or {}
        print(f"Camera: {info.get('softver', 'unknown')}  SSID: {info.get('ssid', 'unknown')}")
        all_recordings = list_recordings(base_url, args.folder, args.timeout)
        recordings = [item for item in all_recordings if item.is_front]
    except (OSError, urllib.error.URLError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    selected = recordings[:-args.skip_newest] if args.skip_newest else recordings
    total = sum(item.size for item in selected)
    print(
        f"Found {len(recordings):,} front recordings; selected {len(selected):,} "
        f"({human_size(total)}), skipping {len(recordings) - len(selected)} newest."
    )
    if not args.download:
        if not args.quiet_list:
            for item in selected:
                print(f"{item.filename}\t{item.size}\t{item.remote_path}")
        print("List-only mode. Add --download to copy selected files.")
        return 0

    args.output.mkdir(parents=True, exist_ok=True)
    history_path = args.history or args.output / ".dashcam_history.sqlite3"
    counts = {
        "downloaded": 0, "existing": 0, "historical": 0,
        "mismatched": 0, "failed": 0
    }
    with DownloadHistory(history_path) as history:
        history.import_local_sources(args.output)
        history.reconcile(args.output)
        pending = [item for item in selected
                   if (args.redownload_missing or not history.was_downloaded(item.remote_path))
                   and not (args.output / item.filename).exists()]
        pending_names = {item.filename for item in pending}
        PROGRESS.update(done=0, total=sum(item.size for item in pending), started=time.monotonic(), last=0)
        show_progress("", 0, 0, PROGRESS['started'])
        for item in selected:
            final_path = args.output / item.filename
            if (
                not final_path.exists()
                and history.was_downloaded(item.remote_path)
                and not args.redownload_missing
            ):
                counts["historical"] += 1
                continue
            try:
                result = download_one(
                    base_url, item, args.output, args.timeout, args.replace_mismatched
                )
                counts[result] += 1
                if item.filename in pending_names:
                    PROGRESS["done"] += item.size
                show_progress(item.filename, 0, 0, PROGRESS["started"])
                if result in ("downloaded", "existing"):
                    history.record_download(
                        item.remote_path, item.filename, final_path.stat().st_size
                    )
            except (OSError, urllib.error.URLError, RuntimeError) as exc:
                counts["failed"] += 1
                print(f"ERROR: {exc}", file=sys.stderr)
    print("Summary: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
