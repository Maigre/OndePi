from __future__ import annotations

import argparse
import json
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser(description="OndePi CLI")
    parser.add_argument("--host", default="http://127.0.0.1:8090")
    parser.add_argument("command", choices=["status", "start", "stop"])
    args = parser.parse_args()

    if args.command == "status":
        url = f"{args.host}/api/status"
        with urllib.request.urlopen(url) as response:  # nosec - local usage
            payload = json.loads(response.read().decode("utf-8"))
        print(json.dumps(payload, indent=2))
        return

    if args.command == "start":
        url = f"{args.host}/api/stream/start"
    else:
        url = f"{args.host}/api/stream/stop"

    request = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(request) as response:  # nosec - local usage
        print(response.read().decode("utf-8"))


if __name__ == "__main__":
    main()
