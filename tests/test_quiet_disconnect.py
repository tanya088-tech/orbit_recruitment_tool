"""The dashboard ignores a browser that closes the connection early (reload / the 3-second poll) instead of printing
"BrokenPipeError: [Errno 32]" and a dashed line; real errors are still reported."""
import io

import run_dashboard
from dashboard.server import CLIENT_GONE, DashboardApp, make_handler
from store.json_store import JsonJobHistory, JsonRecruiterState
from tests.factories import NOW


class _GoneSocketFile(io.BytesIO):
    def __init__(self, exc):
        super().__init__()
        self.exc = exc

    def write(self, data):
        raise self.exc


def _handler(tmp_path, exc):
    app = DashboardApp(JsonJobHistory(tmp_path / "h.json"), JsonRecruiterState(tmp_path / "s.json", now_fn=lambda: NOW), now_fn=lambda: NOW)
    cls = make_handler(app)
    h = cls.__new__(cls)
    h.wfile, h.command, h.path = _GoneSocketFile(exc), "GET", "/collection/status"
    h.request_version, h.requestline, h.client_address = "HTTP/1.1", "GET /collection/status HTTP/1.1", ("127.0.0.1", 5)
    h.close_connection = False
    return h


def test_send_ignores_a_browser_that_went_away(tmp_path):
    for exc in (BrokenPipeError(32, "Broken pipe"), ConnectionResetError(), ConnectionAbortedError()):
        _handler(tmp_path, exc)._send(200, b"{}", "application/json")          # must not raise


def test_send_still_raises_other_errors(tmp_path):
    try:
        _handler(tmp_path, ValueError("boom"))._send(200, b"x")
    except ValueError:
        return
    raise AssertionError("a real error must not be swallowed")


def _error_output(capsys, exc):
    srv = run_dashboard.DashboardHTTPServer.__new__(run_dashboard.DashboardHTTPServer)
    try:
        raise exc
    except Exception:
        srv.handle_error(None, ("127.0.0.1", 5))
    return capsys.readouterr().err


def test_server_is_quiet_when_the_browser_drops_the_connection(capsys):
    assert issubclass(run_dashboard.DashboardHTTPServer, run_dashboard.ThreadingHTTPServer)
    assert run_dashboard.DashboardHTTPServer.daemon_threads
    for exc in CLIENT_GONE:
        assert _error_output(capsys, exc()) == ""


def test_server_still_reports_real_errors(capsys):
    out = _error_output(capsys, RuntimeError("real problem"))
    assert "RuntimeError" in out and "-----" in out
