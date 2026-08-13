"""Entry point — start the Artificial Society server.

    python run.py [--host 127.0.0.1] [--port 8765] [--config configs/default.yaml]

Then open http://127.0.0.1:8765 in a browser.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> None:
    parser = argparse.ArgumentParser(description="Artificial Society server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    import uvicorn
    from api.main import app
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
