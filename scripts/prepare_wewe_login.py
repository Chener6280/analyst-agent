#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE = "http://localhost:4001"
DEFAULT_CONTAINER = "wewe-rss-ir"
DEFAULT_AUTH_CODE = "irsearch"
DEFAULT_ACCOUNTS = os.environ.get("WECHAT_ACCOUNTS_PATH", "/Users/chen/Documents/ir_search/accounts.json")


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    result: dict[str, Any] = {
        "base_url": base_url,
        "container": args.container,
        "dash_url": f"{base_url}/dash",
        "colima_started": False,
        "container_started": False,
        "dash_ready": False,
        "login_ready": None,
        "login_needed": False,
        "messages": [],
    }

    if args.start_colima:
        result["colima_started"] = ensure_colima(result)
    if args.start_container:
        result["container_started"] = ensure_container(args.container, result)

    result["dash_ready"] = wait_for_dash(base_url, args.service_timeout, result)
    if not result["dash_ready"]:
        emit(result)
        return 2

    probe_mp_id = args.probe_mp_id or first_mp_id(Path(args.accounts))
    if probe_mp_id:
        result["probe_mp_id"] = probe_mp_id
        result["login_ready"] = probe_refresh(base_url, args.auth_code, probe_mp_id, result)
        result["login_needed"] = result["login_ready"] is False
    else:
        result["messages"].append("no wewe mp_id found; skipped login refresh probe")

    if result["login_needed"] and args.open_dash:
        open_dash(result["dash_url"], result)

    if result["login_needed"] and args.wait_seconds:
        result["messages"].append(f"waiting up to {args.wait_seconds}s for wewe login")
        result["login_ready"] = wait_for_login(base_url, args.auth_code, probe_mp_id, args.wait_seconds, result)
        result["login_needed"] = result["login_ready"] is False

    emit(result)
    return 2 if result["login_needed"] else 0


def ensure_colima(result: dict[str, Any]) -> bool:
    status = run(["colima", "status"])
    if status.returncode == 0:
        result["messages"].append("colima already running")
        return False
    started = run(["colima", "start"])
    if started.returncode != 0:
        result["messages"].append(f"colima start failed: {started.stderr.strip() or started.stdout.strip()}")
        return False
    result["messages"].append("colima started")
    return True


def ensure_container(container: str, result: dict[str, Any]) -> bool:
    started = run(["docker", "start", container])
    if started.returncode != 0:
        result["messages"].append(f"docker start {container} failed: {started.stderr.strip() or started.stdout.strip()}")
        return False
    result["messages"].append(f"docker container ready: {container}")
    return True


def wait_for_dash(base_url: str, timeout: int, result: dict[str, Any]) -> bool:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() <= deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/dash", timeout=5) as resp:
                if resp.status == 200:
                    return True
                last_error = f"HTTP {resp.status}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    result["messages"].append(f"wewe dash not ready at {base_url}/dash: {last_error}")
    return False


def first_mp_id(accounts: Path) -> str | None:
    if not accounts.exists():
        return None
    data = json.loads(accounts.read_text(encoding="utf-8"))
    for value in data.values():
        if isinstance(value, dict):
            mp_id = ((value.get("wewe") or {}).get("mp_id") or "").strip()
            if mp_id:
                return mp_id
    return None


def probe_refresh(base_url: str, auth_code: str, mp_id: str, result: dict[str, Any]) -> bool:
    body = json.dumps({"mpId": mp_id}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/trpc/feed.refreshArticles",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": auth_code},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            _ = resp.read()
            result["messages"].append("wewe refresh probe passed")
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        result["messages"].append(f"wewe refresh probe failed: HTTP {exc.code}: {detail[:300]}")
        return False
    except Exception as exc:
        result["messages"].append(f"wewe refresh probe failed: {exc}")
        return False


def wait_for_login(base_url: str, auth_code: str, mp_id: str, seconds: int, result: dict[str, Any]) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() <= deadline:
        if probe_refresh(base_url, auth_code, mp_id, result):
            return True
        time.sleep(5)
    return False


def open_dash(url: str, result: dict[str, Any]) -> None:
    completed = run(["open", url])
    if completed.returncode == 0:
        result["messages"].append(f"opened wewe dash for login: {url}")
    else:
        result["messages"].append(f"failed to open wewe dash: {completed.stderr.strip() or completed.stdout.strip()}")


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True)


def emit(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("login_needed"):
        print("wewe_login_needed=true")
        print(f"open_dash={result.get('dash_url')}")
        print("auth_code=irsearch")
    elif result.get("dash_ready"):
        print("wewe_ready=true")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start local wewe-rss and open login page when WeRead token is expired.")
    parser.add_argument("--base-url", default=os.environ.get("WEWE_RSS_BASE", DEFAULT_BASE))
    parser.add_argument("--container", default=os.environ.get("WEWE_RSS_CONTAINER", DEFAULT_CONTAINER))
    parser.add_argument("--auth-code", default=os.environ.get("WEWE_AUTH_CODE", DEFAULT_AUTH_CODE))
    parser.add_argument("--accounts", default=DEFAULT_ACCOUNTS)
    parser.add_argument("--probe-mp-id")
    parser.add_argument("--service-timeout", type=int, default=20)
    parser.add_argument("--wait-seconds", type=int, default=0)
    parser.add_argument("--open-dash", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--start-colima", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--start-container", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
