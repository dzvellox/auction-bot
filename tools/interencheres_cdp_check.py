from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

URL = "http://127.0.0.1:9222/json/version"


def main() -> int:
    print(f"Test CDP : {URL}")
    try:
        with urllib.request.urlopen(URL, timeout=3) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        print(f"ECHEC : aucun endpoint CDP accessible ({exc}).")
        print("Lance d'abord tools\\start_interencheres_browser.bat et vérifie qu'il affiche 'CDP OK'.")
        return 2
    except Exception as exc:
        print(f"ECHEC : {type(exc).__name__}: {exc}")
        return 2

    ws = payload.get("webSocketDebuggerUrl")
    browser = payload.get("Browser", "?")
    protocol = payload.get("Protocol-Version", "?")
    print("OK")
    print(f"Browser  : {browser}")
    print(f"Protocol : {protocol}")
    print(f"WebSocket: {ws or 'absent'}")
    return 0 if ws else 3


if __name__ == "__main__":
    raise SystemExit(main())
