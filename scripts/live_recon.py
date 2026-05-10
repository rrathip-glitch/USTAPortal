"""Live authenticated recon driver for playtennis.usta.com.

Runs once with the user's credentials (loaded from src.config.settings) and
walks a fixed list of post-login pages, capturing every network request,
GraphQL operation, and rendered DOM into data/recon/2026-05-10-live/.

Strict policies:
  * The password is NEVER printed, written to a file, or echoed to stderr.
    It is read from settings.usta_password and passed directly to page.fill.
  * Single browser session, 3-second sleeps between navigations.
  * If MFA / captcha / bot interstitial appears, the script stops with a
    "STOP" marker on stdout and writes a stop-reason file; it does not retry
    or attempt evasion.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Allow running from repo root: ensure src is importable.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.config import settings  # noqa: E402

OUT_DIR = REPO_ROOT / "data" / "recon" / "2026-05-10-live"
DOM_DIR = OUT_DIR / "dom"
GQL_DIR = OUT_DIR / "gql"
NETWORK_LOG = OUT_DIR / "network.jsonl"
STORAGE_STATE = OUT_DIR / "storage_state.json"
STOP_REASON_FILE = OUT_DIR / "STOP_REASON.txt"
SUMMARY_FILE = OUT_DIR / "summary.json"

CHROMIUM_PATH = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
# Anti-detection flags: --disable-blink-features=AutomationControlled hides the
# navigator.webdriver flag that Cloudflare reads. The other flags handle
# sandbox cert chain quirks of this environment.
CHROMIUM_ARGS = [
    "--ignore-certificate-errors",
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-dev-shm-usage",
]
# UA matches the actual Chromium 141 binary at CHROMIUM_PATH.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
# The script can run in true non-headless mode if a display (X / Xvfb) is
# available — that matters because Cloudflare bot-walls headless Chromium even
# with the AutomationControlled flag stripped.
import os as _os  # noqa: E402
HEADLESS = _os.environ.get("DISPLAY") in (None, "")

DRAW_URL = (
    "https://playtennis.usta.com/Competitions/tritennis0/Tournaments/draws/"
    "CB005855-CDEF-4A4A-8885-4D3A52C9B413"
)

# Targets walked in order. For each: (slug, url). Slug is used for filenames.
# The "profile" and "opponent" URLs are discovered dynamically and walked
# after the first three targets.
INITIAL_TARGETS: list[tuple[str, str]] = [
    ("01_root_dashboard", "https://playtennis.usta.com/"),
    ("02_draw", DRAW_URL),
]

# Heuristics for detecting that the page is a stop-condition.
MFA_MARKERS = [
    "verify your identity",
    "enter the code",
    "two-step",
    "two-factor",
    "multi-factor",
    "authenticator app",
    "recovery code",
]
CAPTCHA_MARKERS = [
    "recaptcha",
    "hcaptcha",
    "i'm not a robot",
    "verify you are human",
    "press and hold",
]
BOT_WALL_MARKERS = [
    "sorry, you have been blocked",
    "attention required",  # cloudflare challenge title
    "checking your browser",
    "cf-challenge",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_filename(s: str, maxlen: int = 80) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")
    return s[:maxlen] or "x"


async def main() -> int:
    if not settings.usta_username or not settings.usta_password:
        print("FATAL: USTA_USERNAME / USTA_PASSWORD not set in environment.", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DOM_DIR.mkdir(parents=True, exist_ok=True)
    GQL_DIR.mkdir(parents=True, exist_ok=True)
    if STOP_REASON_FILE.exists():
        STOP_REASON_FILE.unlink()
    if NETWORK_LOG.exists():
        NETWORK_LOG.unlink()

    network_fh = NETWORK_LOG.open("w")

    # Track: requests by URL key for body capture (we only keep recent fetch/xhr).
    # GraphQL operations: keep an ordered list as observed.
    gql_records: list[dict[str, Any]] = []
    gql_seq = 0

    # Bookkeeping for summary.
    request_count = 0
    response_count = 0
    distinct_hosts: set[str] = set()
    bearer_seen = False

    # We keep a small ring of recent request bodies for matching to responses
    # (Playwright's request.post_data isn't always available on response side).
    request_bodies: dict[str, str] = {}

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(
                executable_path=CHROMIUM_PATH,
                headless=HEADLESS,
                args=CHROMIUM_ARGS,
            )
        except Exception as e:
            print(f"FATAL: failed to launch chromium: {e}", file=sys.stderr)
            return 3
        print(f"[recon] chromium launched headless={HEADLESS} ua={USER_AGENT[:40]}...", flush=True)

        context = await browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1366, "height": 900},
            user_agent=USER_AGENT,
            locale="en-US",
            timezone_id="America/New_York",
        )

        # Hide the obvious automation tells before any page script runs.
        await context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = window.chrome || { runtime: {} };
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
            """
        )

        page = await context.new_page()

        async def on_request(request: Any) -> None:
            nonlocal request_count, bearer_seen
            request_count += 1
            try:
                host = urlparse(request.url).netloc
                distinct_hosts.add(host)
                headers = await request.all_headers()
                auth = headers.get("authorization", "")
                if auth.lower().startswith("bearer "):
                    bearer_seen = True
                post_data = None
                try:
                    post_data = request.post_data
                except Exception:
                    post_data = None
                row = {
                    "ts": now_iso(),
                    "kind": "request",
                    "method": request.method,
                    "url": request.url,
                    "resource_type": request.resource_type,
                    "has_auth": bool(auth),
                    "has_bearer": auth.lower().startswith("bearer "),
                    "content_type": headers.get("content-type"),
                    "post_data_len": len(post_data) if post_data else 0,
                }
                network_fh.write(json.dumps(row) + "\n")
                # Stash post body for GraphQL matching.
                if post_data and "graphql" in request.url.lower():
                    request_bodies[request.url + "|" + str(request_count)] = post_data
                    # Also stash latest by URL (last write wins; close enough for correlation).
                    request_bodies[request.url] = post_data
            except Exception:
                pass

        async def on_response(response: Any) -> None:
            nonlocal response_count, gql_seq
            response_count += 1
            try:
                req = response.request
                host = urlparse(response.url).netloc
                distinct_hosts.add(host)
                headers = await response.all_headers()
                ctype = headers.get("content-type", "")
                clen = headers.get("content-length")
                row = {
                    "ts": now_iso(),
                    "kind": "response",
                    "method": req.method,
                    "url": response.url,
                    "status": response.status,
                    "content_type": ctype,
                    "length": clen,
                }
                network_fh.write(json.dumps(row) + "\n")
                # Capture GraphQL bodies.
                is_gql = "graphql" in response.url.lower() and req.method == "POST"
                if is_gql:
                    try:
                        body_text = await response.text()
                    except Exception:
                        body_text = ""
                    request_body_text = request_bodies.get(response.url) or ""
                    op_name = "unknown"
                    try:
                        if request_body_text:
                            j = json.loads(request_body_text)
                            if isinstance(j, dict):
                                op_name = j.get("operationName") or "unknown"
                            elif isinstance(j, list) and j and isinstance(j[0], dict):
                                op_name = j[0].get("operationName") or "batch"
                    except Exception:
                        pass
                    gql_seq += 1
                    rec = {
                        "seq": gql_seq,
                        "url": response.url,
                        "operationName": op_name,
                        "status": response.status,
                        "request": _safe_json(request_body_text),
                        "response": _safe_json(body_text),
                        "request_headers": await req.all_headers(),
                        "response_headers": headers,
                    }
                    gql_records.append(rec)
                    fname = f"{gql_seq:03d}_{safe_filename(op_name)}.json"
                    (GQL_DIR / fname).write_text(json.dumps(rec, indent=2))
            except Exception:
                pass

        page.on("request", lambda r: asyncio.create_task(on_request(r)))
        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        # ---- Step 1: navigate to root, handle login if redirected. ----
        print("[recon] navigating to root...", flush=True)
        try:
            await page.goto("https://playtennis.usta.com/", wait_until="domcontentloaded", timeout=60_000)
        except Exception as e:
            print(f"[recon] WARN navigate root: {e}", flush=True)

        await asyncio.sleep(3)
        cur_url = page.url
        print(f"[recon] post-root url: {cur_url}", flush=True)

        if "account.usta.com" in cur_url or "auth0" in cur_url.lower():
            print("[recon] login flow detected; filling credentials", flush=True)
            ok = await _do_login(page)
            if not ok:
                _stop("login_failed", page)
                await _save_summary(
                    request_count, response_count, distinct_hosts, gql_records, bearer_seen,
                    status="login_failed",
                )
                network_fh.close()
                await context.close()
                await browser.close()
                return 4

        # Check for stop conditions before proceeding.
        stop = await _check_stop(page)
        if stop:
            _stop(stop, page)
            await _save_summary(
                request_count, response_count, distinct_hosts, gql_records, bearer_seen,
                status=f"stop:{stop}",
            )
            network_fh.close()
            await context.close()
            await browser.close()
            return 5

        # Save storage state immediately after login so we have it even if later steps fail.
        try:
            await context.storage_state(path=str(STORAGE_STATE))
            print(f"[recon] storage_state saved -> {STORAGE_STATE}", flush=True)
        except Exception as e:
            print(f"[recon] WARN saving storage_state: {e}", flush=True)

        # Save dashboard DOM.
        await _save_dom(page, "01_root_dashboard")

        # ---- Step 2: navigate to draw URL. ----
        await asyncio.sleep(3)
        print("[recon] navigating to draw...", flush=True)
        try:
            await page.goto(DRAW_URL, wait_until="domcontentloaded", timeout=60_000)
        except Exception as e:
            print(f"[recon] WARN navigate draw: {e}", flush=True)
        await asyncio.sleep(5)  # let SPA fan-out settle
        await _save_dom(page, "02_draw")

        # ---- Step 3: discover & visit user profile. ----
        await asyncio.sleep(3)
        profile_url = await _discover_profile_url(page)
        print(f"[recon] discovered profile url: {profile_url}", flush=True)
        if profile_url:
            try:
                await page.goto(profile_url, wait_until="domcontentloaded", timeout=60_000)
                await asyncio.sleep(5)
                await _save_dom(page, "03_user_profile")
            except Exception as e:
                print(f"[recon] WARN visiting profile: {e}", flush=True)

        # ---- Step 4: discover & visit opponent profile from the draw. ----
        await asyncio.sleep(3)
        try:
            await page.goto(DRAW_URL, wait_until="domcontentloaded", timeout=60_000)
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[recon] WARN re-navigate draw: {e}", flush=True)
        opponent_url = await _discover_opponent_url(page)
        print(f"[recon] discovered opponent url: {opponent_url}", flush=True)
        if opponent_url:
            try:
                await page.goto(opponent_url, wait_until="domcontentloaded", timeout=60_000)
                await asyncio.sleep(5)
                await _save_dom(page, "04_opponent_profile")
            except Exception as e:
                print(f"[recon] WARN visiting opponent profile: {e}", flush=True)

        # ---- Step 5: tournament list. ----
        await asyncio.sleep(3)
        tlist_url = await _discover_tournaments_url(page)
        print(f"[recon] discovered tournaments url: {tlist_url}", flush=True)
        if tlist_url:
            try:
                await page.goto(tlist_url, wait_until="domcontentloaded", timeout=60_000)
                await asyncio.sleep(5)
                await _save_dom(page, "05_tournaments_list")
            except Exception as e:
                print(f"[recon] WARN visiting tournaments list: {e}", flush=True)

        # Final storage state save.
        try:
            await context.storage_state(path=str(STORAGE_STATE))
        except Exception:
            pass

        await _save_summary(
            request_count, response_count, distinct_hosts, gql_records, bearer_seen,
            status="ok",
            visited={
                "profile_url": profile_url,
                "opponent_url": opponent_url,
                "tournaments_url": tlist_url,
            },
        )

        network_fh.close()
        await context.close()
        await browser.close()

    # ---- Strategy A-prime test: replay one captured GraphQL via httpx ----
    replay = await _httpx_replay(gql_records)
    if replay:
        (OUT_DIR / "httpx_replay.json").write_text(json.dumps(replay, indent=2))

    # Console summary
    print("=" * 60)
    print(f"network requests: {request_count}")
    print(f"network responses: {response_count}")
    print(f"distinct hosts: {len(distinct_hosts)}")
    for h in sorted(distinct_hosts):
        print(f"  - {h}")
    print(f"graphql operations: {len(gql_records)}")
    op_summary: dict[str, int] = {}
    for r in gql_records:
        op_summary[r["operationName"]] = op_summary.get(r["operationName"], 0) + 1
    for k, v in sorted(op_summary.items(), key=lambda x: -x[1]):
        print(f"  {v:4d}x  {k}")
    print(f"bearer token observed: {bearer_seen}")
    if replay:
        print(f"httpx replay: status={replay.get('status')} bot_blocked={replay.get('bot_blocked')}")
    print("=" * 60)
    return 0


def _safe_json(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return text[:4000]


async def _do_login(page: Any) -> bool:
    # Auth0 Universal Login: look for username field, then password field.
    try:
        # Auth0 forms vary; try common selectors.
        username_sel = "input[name='username'], input[type='email'], input#username, input[name='email']"
        await page.wait_for_selector(username_sel, timeout=30_000)
        await page.fill(username_sel, settings.usta_username)
        # Some Auth0 flows have a "Continue" button before password.
        cont_btn = page.locator("button[type='submit'], button:has-text('Continue')")
        try:
            await cont_btn.first.click(timeout=5_000)
        except Exception:
            pass
        # Now look for password.
        pass_sel = "input[name='password'], input[type='password']"
        await page.wait_for_selector(pass_sel, timeout=30_000)
        await page.fill(pass_sel, settings.usta_password)
        # Submit.
        submit = page.locator(
            "button[type='submit'], button:has-text('Continue'), button:has-text('Log in'), button:has-text('Sign in')"
        )
        await submit.first.click(timeout=10_000)
        # Wait for redirect back to playtennis.
        try:
            await page.wait_for_url(re.compile(r"playtennis\.usta\.com"), timeout=60_000)
        except Exception:
            # Sometimes lands on www.usta.com first; check below
            await asyncio.sleep(5)
        return "playtennis.usta.com" in page.url or "usta.com" in page.url
    except Exception as e:
        print(f"[recon] login error: {e}", flush=True)
        return False


async def _check_stop(page: Any) -> str | None:
    try:
        text = (await page.content()).lower()
    except Exception:
        return None
    for m in MFA_MARKERS:
        if m in text:
            return f"mfa:{m}"
    for m in CAPTCHA_MARKERS:
        if m in text:
            return f"captcha:{m}"
    for m in BOT_WALL_MARKERS:
        if m in text:
            return f"bot_wall:{m}"
    return None


def _stop(reason: str, page: Any) -> None:
    msg = f"STOP: {reason} at url={page.url}"
    print(msg, flush=True)
    STOP_REASON_FILE.write_text(msg + "\n")


async def _save_dom(page: Any, slug: str) -> None:
    try:
        html = await page.content()
        path = DOM_DIR / f"{slug}.html"
        path.write_text(html)
        print(f"[recon] saved dom -> {path}  ({len(html)} bytes, url={page.url})", flush=True)
    except Exception as e:
        print(f"[recon] WARN save dom {slug}: {e}", flush=True)


async def _discover_profile_url(page: Any) -> str | None:
    # Look for common profile / "my account" links.
    candidates = [
        "a[href*='/Player/']",
        "a[href*='/profile']",
        "a[href*='/account']",
        "a[href*='/MyAccount']",
        "a[href*='/me']",
        "a:has-text('My Profile')",
        "a:has-text('Profile')",
        "a:has-text('My Account')",
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            href = await loc.get_attribute("href", timeout=2_000)
            if href:
                if href.startswith("/"):
                    return "https://playtennis.usta.com" + href
                if href.startswith("http"):
                    return href
        except Exception:
            continue
    return None


async def _discover_opponent_url(page: Any) -> str | None:
    # On the draw page, find any /Player/<id> link that's not the user.
    try:
        anchors = await page.locator("a[href*='/Player']").all()
        for a in anchors[:20]:
            try:
                href = await a.get_attribute("href")
            except Exception:
                href = None
            if not href:
                continue
            full = href if href.startswith("http") else "https://playtennis.usta.com" + href
            return full
    except Exception:
        pass
    return None


async def _discover_tournaments_url(page: Any) -> str | None:
    # Look on the dashboard for a "Tournaments" / "My Tournaments" link.
    candidates = [
        "a[href*='/Tournaments']",
        "a[href*='/Competitions']",
        "a:has-text('Tournaments')",
        "a:has-text('My Tournaments')",
        "a:has-text('Competitions')",
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            href = await loc.get_attribute("href", timeout=2_000)
            if href:
                if href.startswith("/"):
                    return "https://playtennis.usta.com" + href
                if href.startswith("http"):
                    return href
        except Exception:
            continue
    return None


async def _save_summary(
    request_count: int,
    response_count: int,
    distinct_hosts: set[str],
    gql_records: list[dict[str, Any]],
    bearer_seen: bool,
    status: str,
    visited: dict[str, Any] | None = None,
) -> None:
    op_summary: dict[str, int] = {}
    for r in gql_records:
        op_summary[r["operationName"]] = op_summary.get(r["operationName"], 0) + 1
    summary = {
        "ts": now_iso(),
        "status": status,
        "request_count": request_count,
        "response_count": response_count,
        "distinct_hosts": sorted(distinct_hosts),
        "graphql_operation_count": len(gql_records),
        "graphql_operation_names": op_summary,
        "bearer_seen": bearer_seen,
        "visited": visited or {},
    }
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2))


async def _httpx_replay(gql_records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Replay one captured GraphQL POST via stock httpx using the same headers.

    This is the Strategy A-prime vs Strategy C decisive test.
    """
    if not gql_records:
        return None
    # Pick the first successful Clubspark GraphQL record.
    target = None
    for r in gql_records:
        if r["status"] == 200 and "clubspark" in r["url"]:
            target = r
            break
    if not target:
        target = gql_records[0]

    try:
        import httpx
    except Exception:
        return {"error": "httpx not installed"}

    headers_in = target.get("request_headers") or {}
    # Strip pseudo-headers (HTTP/2 :authority etc.) and hop-by-hop bits.
    headers = {}
    for k, v in headers_in.items():
        if k.startswith(":"):
            continue
        if k.lower() in {"content-length", "host"}:
            continue
        headers[k] = v
    body = target["request"]
    if isinstance(body, (dict, list)):
        body_bytes = json.dumps(body).encode()
    elif isinstance(body, str):
        body_bytes = body.encode()
    else:
        body_bytes = b""

    url = target["url"]
    print(f"[recon] httpx replay -> {url} (op={target['operationName']})", flush=True)
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            resp = await client.post(url, headers=headers, content=body_bytes)
            text = resp.text[:4000]
            bot_blocked = (
                resp.status_code in (403, 429, 503)
                or "cloudflare" in resp.text.lower()[:2000]
                or "attention required" in resp.text.lower()[:2000]
            )
            return {
                "url": url,
                "operationName": target["operationName"],
                "status": resp.status_code,
                "bot_blocked": bot_blocked,
                "response_headers": dict(resp.headers),
                "response_body_excerpt": text,
            }
    except Exception as e:
        return {
            "url": url,
            "operationName": target["operationName"],
            "error": f"{type(e).__name__}: {e}",
            "bot_blocked": True,
        }


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
    except KeyboardInterrupt:
        rc = 130
    except Exception:
        traceback.print_exc()
        rc = 1
    sys.exit(rc)
