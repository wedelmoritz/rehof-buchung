"""Gemeinsame Fixtures für die End-to-End-Smoke-Tests (Playwright).

Diese Tests laufen gegen einen LAUFENDEN Stack (nicht gegen die Django-Test-DB):
lokal gegen den Dev-Server oder – wie in der CI – gegen den prod-nahen
Docker-Stack (gunicorn + PostgreSQL). Die Basis-URL kommt über `--base-url`.

    pytest tests_e2e/ --base-url http://localhost:8000

Erwartet die Konten aus `seed_demo --testdata` (test/test12345, admin, verwaltung).
"""
from __future__ import annotations

import os

import pytest

TEST_USER = "test"
TEST_PW = "test12345"


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """Startargumente für den Browser. `--no-sandbox` für Container/CI; optional
    ein vorinstalliertes Chromium über `PW_EXECUTABLE_PATH` (z.B. lokal)."""
    args = dict(browser_type_launch_args)
    args["args"] = [*args.get("args", []), "--no-sandbox"]
    exe = os.environ.get("PW_EXECUTABLE_PATH")
    if exe:
        args["executable_path"] = exe
    return args


@pytest.fixture
def login(page, base_url):
    """Meldet einen Nutzer an (Default: das Mitglied `test`)."""
    def _login(username: str = TEST_USER, password: str = TEST_PW):
        page.goto(f"{base_url}/login/")
        page.fill("input[name=username]", username)
        page.fill("input[name=password]", password)
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")
        return page
    return _login
