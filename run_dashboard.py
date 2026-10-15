#!/usr/bin/env python3
"""Phase 3: start the Ace Talent Consulting recruiter dashboard (open the printed address in your browser).

Examples
  python run_dashboard.py                  # your real vacancy history (data/)
  python run_dashboard.py --ingest         # add the newest normalized file first, then start
  python run_dashboard.py --demo           # made-up vacancies in data_demo/ to try the filters
  python run_dashboard.py --port 8080 --open
"""
import argparse
import logging
import os
import sys
import threading
import urllib.request
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

from config import settings
from dashboard import branding, views
from dashboard.collection import CollectionManager
from dashboard.demo import DEMO_BANNER, build_demo
from dashboard.server import STATIC_DIR, DashboardApp, make_handler
from store.ingest import ingest_filtered_file, newest_normalized_file
from store.json_store import JsonJobHistory, JsonRecruiterState


def _already_running(host: str, port: int) -> bool:
    """True when a dashboard already answers on this address (so a second launch just opens it)."""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/healthz", timeout=1.5) as r:
            return r.read() == b"ok"
    except Exception:
        return False


def _fetch_logo_in_background() -> None:
    def work() -> None:
        if branding.ensure_logo(STATIC_DIR):
            views.set_logo(f"/static/{branding.LOGO_FILE}")
    threading.Thread(target=work, name="orbit-logo", daemon=True).start()


def _restart_process() -> None:
    """Start this same command again in place (without --open, the browser tab is already open). Called from the main
    thread after the web server has been shut down and its port released, so the new process can bind straight away."""
    args = [a for a in sys.argv if a != "--open"]
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(sys.executable, [sys.executable] + args)


def main() -> int:
    p = argparse.ArgumentParser(description="Ace Talent Consulting recruiter dashboard.")
    p.add_argument("--data-dir", default=str(settings.DATA_DIR))
    p.add_argument("--host", default=settings.DASHBOARD_HOST)
    p.add_argument("--port", type=int, default=settings.DASHBOARD_PORT)
    p.add_argument("--ingest", action="store_true", help="Ingest the newest output/normalized_jobs_*.json before starting")
    p.add_argument("--demo", action="store_true", help="Use made-up demo vacancies (data_demo/), not your real data")
    p.add_argument("--reset-demo", action="store_true", help="Rebuild the demo data from scratch")
    p.add_argument("--open", action="store_true", help="Open the dashboard in your browser")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    banner = None
    data_dir = Path(args.data_dir)
    if args.demo:
        data_dir, banner = settings.DEMO_DATA_DIR, DEMO_BANNER
        if args.reset_demo or not (data_dir / "job_history.json").exists():
            for name in ("job_history.json", "recruiter_state.json"):
                (data_dir / name).unlink(missing_ok=True)
            build_demo(data_dir)
            print(f"Built demo data in {data_dir}")

    history = JsonJobHistory(data_dir / "job_history.json")
    state = JsonRecruiterState(data_dir / "recruiter_state.json")

    if args.ingest and not args.demo:
        latest = newest_normalized_file(settings.OUTPUT_DIR)
        if latest:
            r = ingest_filtered_file(latest, history)
            print("Ingest:", "already ingested, no change" if r.skipped_already_ingested
                  else f"{r.new} new, {r.existing} already existing ({latest.name})")
        else:
            print("Ingest: no normalized_jobs_*.json found in output/ (run python run_normalize.py)")

    url = f"http://{args.host}:{args.port}/"
    if _already_running(args.host, args.port):
        print(f"Ace Talent Consulting Job Radar is already running at {url}. Opening it in your browser.")
        if args.open:
            webbrowser.open(url)
        return 0

    collection = None if args.demo else CollectionManager(history, data_dir)
    _fetch_logo_in_background()
    restart_requested = threading.Event()
    holder: dict = {}

    def request_restart() -> None:
        """Called by the Restart button: stop serving; main() then replaces this process with a fresh one."""
        restart_requested.set()
        if holder.get("server") is not None:
            holder["server"].shutdown()

    app = DashboardApp(history, state, banner=banner, collection=collection, restart_fn=request_restart)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    server.daemon_threads = True              # an open connection must never keep the old process alive during a restart
    holder["server"] = server
    print(f"\nAce Talent Consulting dashboard running at {url}\n  vacancies in history: {len(history.list_jobs())}"
          f"\n  data folder: {data_dir}\n  Press Ctrl+C to stop.\n")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if collection is not None:
            collection.mark_interrupted()
        server.server_close()
    if restart_requested.is_set():
        print("\nRestarting Ace Talent Consulting Job Radar ...", flush=True)
        _restart_process()                    # does not return
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
