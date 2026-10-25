#!/usr/bin/env python3
"""Batocera Portal entry point.

    python3 app.py --port 5000 [--host 0.0.0.0]

Author: Dan Lee. MIT licensed. Standard library only.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from portal import APP_NAME, __version__  # noqa: E402
from portal.config import load_settings  # noqa: E402
from portal.metrics import local_ip  # noqa: E402
from portal.server import serve  # noqa: E402
from portal.themes import HAS_PIL  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--port", type=int, default=None, help="TCP port (default: settings or 5000)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: all interfaces)")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    args = parser.parse_args(argv)

    settings = load_settings()
    port = args.port or int(settings.get("server_port", 5000))
    try:
        httpd = serve(args.host, port)
    except OSError as e:
        print(f"ERROR: cannot listen on port {port}: {e}")
        print("       Another program is probably using it. Start with --port <other>, "
              "e.g. --port 5001, or stop the other program.")
        return 1
    print("=" * 56)
    print(f"  {APP_NAME} v{__version__}")
    print(f"  Pillow: {'available' if HAS_PIL else 'not installed (placeholder logos disabled)'}")
    print(f"  -> http://localhost:{port}")
    print(f"  -> http://{local_ip()}:{port}  (from your network)")
    print("=" * 56)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    sys.exit(main() or 0)
