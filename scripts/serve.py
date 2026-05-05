"""Run the FastAPI server.

Usage:
    python -m scripts.serve            # http://127.0.0.1:8000
    python -m scripts.serve --port 8080 --reload
"""
import argparse

import uvicorn


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true", help="Auto-reload on code changes (dev).")
    args = p.parse_args()

    uvicorn.run(
        "src.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
