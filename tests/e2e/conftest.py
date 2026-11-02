"""Shared fixtures for real-browser Streamlit end-to-end tests."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Playwright, sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(url: str, process: subprocess.Popen[str], timeout_seconds: float = 30) -> None:
    deadline = time.monotonic() + timeout_seconds
    health_url = f"{url}/_stcore/health"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            pytest.fail(f"Streamlit exited before becoming healthy:\n{output}")
        try:
            with urllib.request.urlopen(health_url, timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)
    pytest.fail(f"Streamlit did not become healthy within {timeout_seconds} seconds.")


@pytest.fixture(scope="session")
def app_url() -> Iterator[str]:
    """Start one headless Streamlit server for the E2E session."""
    port = _unused_local_port()
    url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update(
        {
            "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
            "STREAMLIT_SERVER_HEADLESS": "true",
        }
    )
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "src/emporio/ui.py",
            f"--server.port={port}",
            "--server.address=127.0.0.1",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=creation_flags,
    )
    try:
        _wait_for_health(url, process)
        yield url
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.fixture(scope="session")
def playwright_runtime() -> Iterator[Playwright]:
    """Own the Playwright runtime for the complete E2E session."""
    with sync_playwright() as runtime:
        yield runtime


@pytest.fixture(scope="session")
def browser(playwright_runtime: Playwright) -> Iterator[Browser]:
    """Launch the installed Playwright Chromium build once."""
    launched = playwright_runtime.chromium.launch(headless=True)
    try:
        yield launched
    finally:
        launched.close()
