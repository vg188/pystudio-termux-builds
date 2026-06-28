from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


URL_TIMEOUT = 120
USER_AGENT = "pystudio-transfer"


def format_bytes(value: float) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(value)
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{size:.0f} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PiB"


def format_speed(bytes_per_second: float) -> str:
    return f"{format_bytes(bytes_per_second)}/s"


def first_env_value(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


class TransferProgress:
    def __init__(
        self,
        action: str,
        name: str,
        total: int | None,
        initial: int = 0,
        interval: float = 0.5,
    ) -> None:
        self.action = action
        self.name = name
        self.total = total
        self.initial = initial
        self.current = initial
        self.interval = interval
        self.started_at = time.monotonic()
        self.last_render_at = 0.0
        self.last_line_length = 0
        self.is_tty = sys.stderr.isatty()
        self.render(force=True)

    def update(self, amount: int) -> None:
        self.current += amount
        now = time.monotonic()
        if now - self.last_render_at >= self.interval:
            self.render()

    def render(self, force: bool = False, done: bool = False) -> None:
        now = time.monotonic()
        if not force and not done and now - self.last_render_at < self.interval:
            return
        self.last_render_at = now
        elapsed = max(now - self.started_at, 0.001)
        transferred = max(self.current - self.initial, 0)
        speed = transferred / elapsed

        if self.total:
            percent = min(self.current / self.total * 100, 100.0)
            progress = f"{percent:6.2f}% {format_bytes(self.current)}/{format_bytes(self.total)}"
        else:
            progress = f"{format_bytes(self.current)}"

        line = f"{self.action}: {self.name} {progress} {format_speed(speed)}"
        if done:
            line += f" in {elapsed:.1f}s"

        if self.is_tty:
            padding = " " * max(0, self.last_line_length - len(line))
            print("\r" + line + padding, end="" if not done else "\n", file=sys.stderr, flush=True)
            self.last_line_length = len(line)
        else:
            print(line, file=sys.stderr, flush=True)

    def finish(self) -> None:
        self.render(force=True, done=True)


def safe_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._+-]+", "_", value).strip("_")


def read_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def download_asset(
    url: str,
    destination: Path,
    github_token: str | None,
    retries: int,
    force: bool,
    progress_interval: float,
) -> None:
    if destination.exists() and not force:
        print(f"Download exists, skipping: {destination.name} ({format_bytes(destination.stat().st_size)})")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    resume_from = partial.stat().st_size if partial.exists() and not force else 0
    if force and partial.exists():
        partial.unlink()
        resume_from = 0

    for attempt in range(1, retries + 1):
        headers = {"User-Agent": USER_AGENT}
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"
        if resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"

        request = urllib.request.Request(url, headers=headers)
        progress: TransferProgress | None = None
        try:
            with urllib.request.urlopen(request, timeout=URL_TIMEOUT) as response:
                if resume_from > 0 and getattr(response, "status", 200) != 206:
                    print(f"Server ignored resume for {destination.name}; restarting download.")
                    partial.unlink(missing_ok=True)
                    resume_from = 0
                    mode = "wb"
                else:
                    mode = "ab" if resume_from > 0 else "wb"
                content_length = response.headers.get("Content-Length")
                remaining = int(content_length) if content_length and content_length.isdigit() else None
                total = resume_from + remaining if remaining is not None else None
                progress = TransferProgress(
                    "Downloading",
                    destination.name,
                    total=total,
                    initial=resume_from,
                    interval=progress_interval,
                )
                with partial.open(mode) as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        progress.update(len(chunk))
            partial.replace(destination)
            if progress:
                progress.finish()
            print(f"Downloaded: {destination.name} ({format_bytes(destination.stat().st_size)})")
            return
        except Exception as exc:
            if progress:
                progress.finish()
            if attempt >= retries:
                raise
            wait = min(60, 5 * attempt)
            print(f"Download failed ({attempt}/{retries}) for {destination.name}: {exc}; retrying in {wait}s")
            time.sleep(wait)
            resume_from = partial.stat().st_size if partial.exists() else 0
