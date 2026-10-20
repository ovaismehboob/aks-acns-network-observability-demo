"""Capture Grafana screenshots with Playwright using an Entra bearer token.

Usage: python capture.py <output.png> <dashboard-path-and-query> [width] [height] [wait_seconds]
Example: python capture.py out.png "/d/acns-incident-investigation/acns-incident-investigation?from=now-30m&to=now&kiosk"
"""
import sys
import time
from urllib.parse import urlsplit

from demo_config import endpoint_from_env, run_command

GRAFANA_RESOURCE = "ce34e7e5-485f-4d76-964f-b3d2b16d1e4f"


def get_token():
    token = run_command(
        ["az", "account", "get-access-token", "--resource", GRAFANA_RESOURCE, "--query", "accessToken", "-o", "tsv"],
    ).strip()
    if not token:
        raise RuntimeError("Azure CLI returned no Grafana token.")
    return token


def capture(shots, token=None, width=1700, height=1500, settle=25):
    """shots: list of (output_path, path_and_query)."""
    endpoint = endpoint_from_env("ACNS_GRAFANA_ENDPOINT", ".grafana.azure.com")
    if any(not path.startswith("/d/") or "\\" in path for _, path in shots):
        raise ValueError("Screenshot targets must be dashboard paths beginning with /d/.")
    from playwright.sync_api import sync_playwright

    token = token or get_token()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=1,
        )
        def authorize(route):
            target = urlsplit(route.request.url)
            if (target.scheme, target.netloc) != ("https", urlsplit(endpoint).netloc):
                route.abort()
                return
            headers = {k: v for k, v in route.request.headers.items() if k.lower() != "authorization"}
            headers["Authorization"] = "Bearer " + token
            response = route.fetch(headers=headers, max_redirects=0, timeout=60000)
            if 300 <= response.status < 400:
                route.abort()
                raise RuntimeError("Grafana redirect refused; use the canonical dashboard path. Target omitted.")
            route.fulfill(response=response)

        context.route("**/*", authorize)
        page = context.new_page()
        for out, path in shots:
            response = page.goto(endpoint + path, wait_until="domcontentloaded", timeout=120000)
            if response is None or response.status >= 400:
                raise RuntimeError("Grafana dashboard navigation failed; response omitted.")
            time.sleep(settle)
            page.screenshot(path=out)
            print("saved", out)
        browser.close()


if __name__ == "__main__":
    out, path = sys.argv[1], sys.argv[2]
    w = int(sys.argv[3]) if len(sys.argv) > 3 else 1700
    h = int(sys.argv[4]) if len(sys.argv) > 4 else 1500
    s = int(sys.argv[5]) if len(sys.argv) > 5 else 25
    capture([(out, path)], width=w, height=h, settle=s)
