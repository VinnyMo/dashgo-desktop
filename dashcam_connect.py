"""User-initiated, bounded camera connection. No startup probing."""
import ipaddress
import dashcam_process as subprocess
import threading
import time
from urllib.parse import urlsplit

from dashcam_downloader import gateway_candidates, get_json
from dashcam_live import inspect_stream, read_capabilities, validate_stream

FIRMWARE = "NEXPOW-VSQ10-20250418"


class ConnectionCancelled(Exception):
    pass


class CameraConnection:
    def __init__(self, progress=lambda message: None):
        self.progress = progress
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    def check(self):
        if self.cancelled.is_set():
            raise ConnectionCancelled()

    def request(self, url):
        self.check()
        result = get_json(url, timeout=3)
        self.check()
        return result

    def discover(self):
        self.progress("Looking for cameras on available gateways.")
        self.check()
        candidates = gateway_candidates()
        self.check()
        found = []
        seen = set()
        for host in candidates:
            try:
                address = ipaddress.IPv4Address(host)
            except ValueError:
                continue
            if address.is_unspecified or address.is_loopback or address.is_multicast or host in seen:
                continue
            seen.add(host)
            base = "http://" + host
            try:
                response = self.request(base + "/app/getdeviceattr")
            except (OSError, RuntimeError, ValueError):
                continue
            info = response.get("info")
            if response.get("result") == 0 and isinstance(info, dict) and info.get("softver") and info.get("camnum"):
                found.append({"address": base, "firmware": str(info["softver"])})
        self.check()
        return found

    def run(self, base=None):
        if base is None:
            found = self.discover()
            if not found:
                raise RuntimeError("No camera found. Join the camera Wi-Fi, then retry. Manual addresses are under Advanced.")
            if len(found) > 1:
                return {"candidates": found}
            base = found[0]["address"]
        self.check()
        self.progress("Identifying camera and reading its stream address.")
        capabilities = read_capabilities(base, check=self.check)
        if capabilities["firmware"] != FIRMWARE:
            raise RuntimeError("This firmware is not supported for automatic live activation. No activation command was sent.")
        media = capabilities.get("media") or {}
        url = validate_stream(media.get("rtsp", ""))
        if urlsplit(url).hostname != urlsplit(base).hostname:
            raise RuntimeError("The advertised stream belongs to a different host. Automatic connection stopped.")
        self.progress("Opening the camera live stream.")
        if self.request(base.rstrip("/") + "/app/enterrecorder").get("result") != 0:
            raise RuntimeError("Camera did not open its live stream. Retry after checking the connection.")
        self.progress("Measuring video and audio. This may take up to 50 seconds.")
        report = inspect_stream(url, runner=self.run_process)
        self.check()
        return {"address": base, "url": url, "capabilities": capabilities, "report": report}

    def run_process(self, command, *, capture_output, timeout, **kwargs):
        self.check()
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        deadline = time.monotonic() + timeout
        try:
            while True:
                self.check()
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    stdout, stderr = process.communicate(timeout=0.1)
                    self.check()
                    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
