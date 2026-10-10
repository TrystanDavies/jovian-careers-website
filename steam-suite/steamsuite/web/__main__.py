"""Start the Steam Suite web app:  python -m steamsuite.web  [--port 8000] [--no-browser]"""

from __future__ import annotations

import argparse
import threading
import webbrowser


def main() -> None:
    parser = argparse.ArgumentParser(description="Steam Suite — P&ID designer and steam system simulator")
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="port (default 8000)")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser window")
    args = parser.parse_args()

    import uvicorn

    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"Steam Suite is running at {url}  (press Ctrl+C to stop)")
    uvicorn.run("steamsuite.web.server:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
