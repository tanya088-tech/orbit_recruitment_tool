"""Tiny local web server for the Ace Talent Consulting recruiter dashboard (standard library only).

Routes
  GET  /                              Page 1: recruiter summary (filters in the query string)
  GET  /job/<key>                     Page 2: vacancy details
  POST /job/<key>/save                save / unsave            (field: saved=1|0)
  POST /job/<key>/status              set recruitment status   (field: status)
  POST /job/<key>/notes               add a note               (field: note)
  POST /job/<key>/notes/<id>/delete   delete a note
  POST /collection/saved              show the saved vacancies that match the form (no search)
  POST /collection/run                start a background job collection (fields: scope, count)
  POST /collection/stop               stop the running collection (what was found so far is kept)
  GET  /collection/status             collection status as JSON
  POST /app/restart                   restart the dashboard process (refused while collecting)
  GET  /static/<file>                 stylesheet / script / Groxa AI logo (if downloaded)
  GET  /healthz                       "ok"

Safety: binds to localhost by default, strict Content-Security-Policy, cross-site form
posts are rejected (Origin/Referer must match Host), redirect targets are validated,
request bodies are size-limited, and all page text is HTML-escaped in views.py.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, quote, urlsplit, unquote

from config import locations as loc_config
from config import settings
from dashboard import branding
from dashboard import viewmodel as vm
from dashboard import export, views
from dashboard.collection import parse_target
from store.base import JobHistoryStore, RecruiterStateStore, StoreError
from store.json_store import MemoryPosterEntries

log = logging.getLogger(__name__)

# The browser dropped the connection before the answer was written (a page reload, or app.js's poll every 3 seconds being
# replaced). Harmless, so it is not reported as an error.
CLIENT_GONE = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)
STATIC_DIR = Path(__file__).parent / "static"
STATIC_TYPES = {"style.css": "text/css; charset=utf-8", "app.js": "text/javascript; charset=utf-8",
                branding.LOGO_FILE: "image/png"}
MAX_BODY = 20_000
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
       "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")

_JOB = re.compile(r"^/job/([A-Za-z0-9_-]{1,80})$")
_ACTION = re.compile(r"^/job/([A-Za-z0-9_-]{1,80})/(save|status|notes)$")
_NOTE_DELETE = re.compile(r"^/job/([A-Za-z0-9_-]{1,80})/notes/([A-Za-z0-9]{1,32})/delete$")
_SAFE_Q = re.compile(r"^[A-Za-z0-9_=&%.+~-]*$")


class DashboardApp:
    def __init__(self, history: JobHistoryStore, state: RecruiterStateStore,
                 now_fn: Optional[Callable[[], datetime]] = None, banner: Optional[str] = None,
                 collection=None, restart_fn: Optional[Callable[[], None]] = None,
                 static_dir: Optional[Path] = None, posters: Any = None) -> None:
        self.history, self.state, self.banner = history, state, banner
        self.collection, self.restart_fn = collection, restart_fn
        self.posters = posters if posters is not None else MemoryPosterEntries()
        self.boot_id = uuid.uuid4().hex          # changes with every process start: the restart page waits for a different one
        self.static_dir = Path(static_dir) if static_dir else STATIC_DIR
        self._now = now_fn or (lambda: datetime.now(timezone.utc))
        views.set_logo(f"/static/{branding.LOGO_FILE}" if branding.logo_available(self.static_dir) else None)

    def collection_view(self) -> Optional[dict]:
        """What the collection panel shows. Always present so the panel can explain why it is off."""
        if self.collection is None:
            return {"status": {"state": "idle", "message": "", "last_success_at": None, "last_error": None},
                    "enabled": False, "default_scope": settings.COLLECTION_DEFAULT_SCOPE}
        return {"status": self.collection.status(), "enabled": True, "default_scope": settings.COLLECTION_DEFAULT_SCOPE}

    def now(self) -> datetime:
        return self._now()

    def rows(self) -> list[vm.Row]:
        """The Vacancies list."""
        run = self.history.latest_run()
        return vm.build_rows(self.history.list_jobs(), self.state.get_all(), run["run_id"] if run else None, team_posters=self.posters.get_all())

    def find_row(self, key: str) -> Optional[vm.Row]:
        return next((r for r in self.rows() if r.key == key), None)


def safe_next(value: str, fallback: str = "/") -> str:
    """Only allow same-site relative redirects like '/?posted=24h&page=2'."""
    v = (value or "").strip()
    if (not v.startswith("/") or v.startswith("//") or "\\" in v or len(v) > 500
            or any(ord(c) < 32 or ord(c) > 126 for c in v)):
        return fallback
    return v


def safe_q(value: str) -> str:
    v = (value or "").strip()
    return v if len(v) <= 400 and _SAFE_Q.match(v) else ""


def make_handler(app: DashboardApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AceTalentDashboard/1.0"

        def log_message(self, fmt, *args):      # keep the terminal quiet; use -v style logging if needed
            log.debug("%s - %s", self.address_string(), fmt % args)

        # ------------------------------------------------------ helpers
        def _send(self, status: int, body: bytes, ctype: str = "text/html; charset=utf-8", extra: Optional[dict] = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("Referrer-Policy", "same-origin")   # not no-referrer: that makes browsers send "Origin: null" on form posts
            try:
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
            except CLIENT_GONE as exc:       # the browser closed the connection first (reload, 3-second poll): nothing to answer
                log.debug("browser left before the answer was sent (%s %s): %s", self.command, self.path, type(exc).__name__)

        def _html(self, status: int, html_text: str):
            self._send(status, html_text.encode("utf-8"))

        def _redirect(self, location: str):
            self._send(303, b"", extra={"Location": location})

        def _message(self, status: int, title: str, message: str):
            run = app.history.latest_run()
            self._html(status, views.render_message(title, message, "/", run, app.now(), app.banner))

        def _same_origin(self) -> bool:
            """CSRF guard for POSTs: only this dashboard's own pages may submit forms.

            1. Sec-Fetch-Site (sent by every current browser, whatever the referrer policy): only
               "same-origin" (or "none", a user-typed navigation) is accepted.
            2. Otherwise Origin, then Referer, must match the Host the request was sent to.
               An Origin of "null" is NOT accepted (sandboxed frames and data: pages send it).
            3. No browser headers at all means a non-browser client (curl, tests): allowed, because
               CSRF needs a browser; the server only listens on localhost.
            """
            site = self.headers.get("Sec-Fetch-Site")
            if site:
                ok = site.lower() in ("same-origin", "none")
                reason = f"Sec-Fetch-Site={site}"
            else:
                host = self.headers.get("Host", "")
                ok, reason = True, "no Origin/Referer (non-browser client)"
                for header in ("Origin", "Referer"):
                    value = self.headers.get(header)
                    if value:
                        ok = urlsplit(value).netloc == host
                        reason = f"{header}={value!r} Host={host!r}"
                        break
            if not ok:
                log.warning("blocked cross-site POST %s (%s)", self.path, reason)
            return ok

        def _form(self) -> dict[str, str]:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length > MAX_BODY:
                raise StoreError("request too large")
            raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
            lists = parse_qs(raw, keep_blank_values=True)
            self.form_lists = lists                       # every value of a repeated field (the Source tick-boxes)
            return {k: v[0] for k, v in lists.items()}

        # ------------------------------------------------------ GET
        def do_GET(self):
            try:
                self._get()
            except StoreError as exc:
                log.error("store error: %s", exc)
                self._message(500, "Could not read saved data", str(exc))
            except Exception:
                log.exception("unhandled error on GET %s", self.path)
                self._message(500, "Something went wrong", "The page could not be shown. Check the terminal for details.")

        do_HEAD = do_GET

        def _get(self):
            url = urlsplit(self.path)
            path, params = url.path, parse_qs(url.query, keep_blank_values=True)

            if path == "/healthz":
                return self._send(200, b"ok", "text/plain; charset=utf-8")
            if path == "/app/boot":
                return self._send(200, json.dumps({"boot": app.boot_id}).encode("utf-8"), "application/json; charset=utf-8")
            if path.startswith("/static/"):
                name = unquote(path[len("/static/"):])
                if name not in STATIC_TYPES:
                    return self._message(404, "Not found", "That file does not exist.")
                file = (app.static_dir if name == branding.LOGO_FILE else STATIC_DIR) / name
                if not file.is_file():
                    return self._message(404, "Not found", "That file does not exist.")
                return self._send(200, file.read_bytes(), STATIC_TYPES[name])
            if path == "/collection/status":
                view = app.collection_view()
                body = {k: v for k, v in view["status"].items() if k != "result_keys"}      # the key list can be long; the page does not poll it
                return self._send(200, json.dumps(body).encode("utf-8"), "application/json; charset=utf-8")
            if path == "/export.csv":
                body = export.build_csv(app.rows())
                stamp = app.now().strftime("%Y%m%d_%H%M")
                return self._send(200, body, "text/csv; charset=utf-8",
                                  {"Content-Disposition": f'attachment; filename="vacancies_{stamp}.csv"'})
            if path == "/":
                return self._summary(params)
            m = _JOB.match(path)
            if m:
                return self._detail(m.group(1), params)
            self._message(404, "Page not found", "There is nothing at this address.")

        def _summary(self, params):
            now = app.now()
            rows = app.rows()
            all_rows = rows                      # the State list is built from everything stored, not just the latest request
            f = vm.Filters.from_query(params)
            result_set = None
            cv = app.collection_view()
            keys = list((cv or {}).get("status", {}).get("result_keys") or [])
            if keys and f.view == "latest":
                # the last "N vacancies" request: show exactly those vacancies (nothing is removed from the history)
                keep = set(keys)
                result_set = {"shown": 0, "target": cv["status"].get("target"), "total": len(rows), "at": cv["status"].get("result_at"), "window": cv["status"].get("window")}
                collected = int(cv["status"].get("collected_unique") or len(keys))
                rows = [r for r in rows if r.key in keep]
                result_set["shown"] = len(rows)
                # Why the page can show fewer than the request says: jobs counted when the collection ran that today's GCC/BFSI
                # rules no longer accept (dropped before this point), and jobs outside the chosen Location scope.
                in_scope = len(vm.apply_filters(rows, vm.Filters(scope=f.scope), app.now()))
                result_set.update(collected=collected, hidden_by_rules=max(len(keys) - len(rows), 0),
                                  hidden_by_scope=len(rows) - in_scope, scope=f.scope, in_scope=in_scope)
            elif keys:
                result_set = {"shown": None, "target": cv["status"].get("target"), "total": len(rows), "at": cv["status"].get("result_at"),
                              "available": len(keys)}
            matched = vm.sort_rows(vm.apply_filters(rows, f, now), f.sort)
            page = vm.paginate(matched, f.page)
            scope_only = vm.Filters(scope=f.scope)
            hidden_by_scope = len(rows) - len(vm.apply_filters(rows, scope_only, now)) if f.scope != "all" else 0
            notice = (params.get("notice") or [""])[0]
            notice = notice if notice in views.NOTICES else ""
            html_text = views.render_summary(len(rows), page, vm.summary_cards(matched), f, vm.filter_options(all_rows),
                                             app.history.latest_run(), now, app.banner, cv,
                                             hidden_by_scope, notice, result_set)
            self._html(200, html_text)

        def _detail(self, key: str, params):
            row = app.find_row(key)
            if row is None:
                return self._message(404, "Vacancy not found", "This vacancy is not in the history. It may have been removed.")
            back_q = safe_q((params.get("q") or [""])[0])
            self._html(200, views.render_detail(row, back_q, app.now(), app.history.latest_run(), app.banner))

        # ------------------------------------------------------ POST
        def do_POST(self):
            try:
                self._post()
            except StoreError as exc:
                self._message(400, "That could not be saved", str(exc))
            except Exception:
                log.exception("unhandled error on POST %s", self.path)
                self._message(500, "Something went wrong", "Your change was not saved. Check the terminal for details.")

        def _post(self):
            if not self._same_origin():
                return self._message(403, "Request blocked", "This form was submitted from a different site.")
            path = urlsplit(self.path).path
            if path == "/collection/run":
                return self._collection_run()
            if path == "/collection/saved":
                return self._collection_run(saved=True)
            if path == "/collection/stop":
                if app.collection is None:
                    return self._redirect("/?notice=disabled")
                return self._redirect("/?notice=stopping" if app.collection.stop() else "/?notice=not_running")
            if path == "/app/restart":
                return self._restart()
            note_del = _NOTE_DELETE.match(path)
            act = _ACTION.match(path)
            if not (note_del or act):
                return self._message(404, "Page not found", "There is nothing at this address.")
            key = (note_del or act).group(1)
            if app.history.get_job(key) is None:
                return self._message(404, "Vacancy not found", "This vacancy is not in the history.")

            form = self._form()
            if note_del:
                app.state.delete_note(key, note_del.group(2))
            else:
                action = act.group(2)
                if action == "save":
                    app.state.set_saved(key, form.get("saved") == "1")
                elif action == "status":
                    app.state.set_status(key, form.get("status", ""))
                else:
                    app.state.add_note(key, form.get("note", ""))

            q = safe_q(form.get("q", ""))
            default = f"/job/{quote(key)}" + (f"?q={quote(q)}" if q else "")
            # the star on the summary table sends 'next' (the list URL); detail-page forms send 'q'
            target = safe_next(form["next"], default) if "next" in form else default
            self._redirect(target)

        def _collection_run(self, saved: bool = False):
            form = self._form()
            if app.collection is None:
                return self._redirect("/?notice=disabled")
            scope = form.get("scope", "")
            if scope not in loc_config.SCOPES:
                return self._redirect("/?notice=bad")
            raw_count = (form.get("count", "") or "").strip()
            target = parse_target(raw_count) if raw_count else None       # blank = collect every eligible vacancy (within the limits)
            if raw_count and target is None:
                return self._redirect("/?notice=bad_count")
            window = form.get("window") or settings.COLLECTION_DEFAULT_WINDOW
            if window not in settings.COLLECTION_WINDOWS:
                return self._redirect("/?notice=bad")
            picked = [x for x in self.form_lists.get("source", []) if x in settings.SUPPORTED_SOURCES]
            if "sources_sent" in form and not picked:
                return self._redirect("/?notice=bad_source")
            fetch_filters = vm.clean_fetch_filters({k: form.get("f_" + k, "") for k in vm.FETCH_FILTER_KEYS})
            if saved:
                ok, _msg = app.collection.show_saved(scope, target, window, sources=picked or None, filters=fetch_filters)
                return self._redirect("/?notice=saved" if ok else "/?notice=already")
            ok, _msg = app.collection.start(scope, target, window, sources=picked or None, filters=fetch_filters)
            self._redirect("/?notice=started" if ok else "/?notice=already")

        def _restart(self):
            if app.restart_fn is None:
                return self._message(400, "Restart not available", "This dashboard was not started in a way that allows restarting.")
            if app.collection is not None and app.collection.running:
                return self._redirect("/?notice=restart_blocked")
            threading.Timer(0.8, app.restart_fn).start()
            self._html(200, views.render_restarting(app.now(), app.boot_id))

    return Handler
