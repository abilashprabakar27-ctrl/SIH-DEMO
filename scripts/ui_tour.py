#!/usr/bin/env python3
"""Playwright smoke tour: sign in as each role, open every page at 1360 px and 390 px,
fail on console errors or error banners, save screenshots to docs/screenshots/.

Usage: python scripts/ui_tour.py [--base http://localhost:8000]
Needs a running server with the built frontend and a seeded database.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "docs" / "screenshots"
CHROMIUM = os.environ.get("CHROMIUM_PATH", "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome")

TOUR = {
    "kaveri.admin@demo.local": ["/inst", "/inst/upload", "/records", "/issues", "/corrections", "/seat-check", "/reports"],
    "aicte.admin@demo.local": ["/aicte", "/aicte/priority", "/issues", "/aicte/identity", "/records", "/aicte/rules",
                               "/aicte/integrations", "/audit", "/reports"],
    "aicte.analyst@demo.local": ["/aicte", "/records"],
    "auditor@demo.local": ["/audit", "/issues"],
    "verifier@demo.local": ["/verify", "/verifier/requests"],
    "student.ananya@demo.local": ["/me"],
}
WIDTHS = [(1360, 900), (390, 844)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    args = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    visited = 0
    launch = {"executable_path": CHROMIUM} if Path(CHROMIUM).exists() else {}
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch)
        for w, h in WIDTHS:
            # public pages
            ctx = browser.new_context(viewport={"width": w, "height": h})
            page = ctx.new_page()
            errors: list[str] = []
            page.on("console", lambda m, errors=errors: m.type == "error" and errors.append(m.text))
            page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
            for path in ("/login", "/verify"):
                page.goto(f"{args.base}/#{path}")
                page.wait_for_load_state("networkidle")
                page.screenshot(path=str(SHOTS / f"public{path.replace('/', '_')}_{w}.png"), full_page=True)
                visited += 1
            for email, paths in TOUR.items():
                page.goto(f"{args.base}/#/login")
                page.wait_for_load_state("networkidle")
                page.get_by_text(email, exact=True).click()
                page.wait_for_selector("text=Sign out", timeout=15000)
                for path in paths:
                    errors.clear()
                    page.goto(f"{args.base}/#{path}")
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(300)
                    role = email.split("@")[0].replace(".", "-")
                    shot = SHOTS / f"{role}{path.replace('/', '_')}_{w}.png"
                    page.screenshot(path=str(shot), full_page=True)
                    visited += 1
                    banners = page.locator(".banner.error").all_inner_texts()
                    real_errors = [e for e in errors if "EventSource" not in e]
                    overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
                    if real_errors:
                        problems.append(f"{w}px {email} {path}: console errors {real_errors[:2]}")
                    if banners:
                        problems.append(f"{w}px {email} {path}: error banner {banners[:1]}")
                    if overflow:
                        problems.append(f"{w}px {email} {path}: horizontal page scroll")
                    print(f"  {'ok ' if not (real_errors or banners or overflow) else 'BAD'} {w}px {email:<28} {path}")
                page.get_by_text("Sign out").click()
            ctx.close()
        browser.close()
    print(f"\nVisited {visited} page views; screenshots in {SHOTS.relative_to(ROOT)}")
    if problems:
        print(f"{len(problems)} problem(s):", *problems, sep="\n  ")
        return 1
    print("UI TOUR PASSED: no console errors, no error banners, no horizontal scroll")
    return 0


if __name__ == "__main__":
    sys.exit(main())
