"""Naukri speed-up: the collection browser does not download images, video or fonts (the tool reads only text)."""
from collectors.browser_client import BrowserClient
from config import settings


class _Request:
    def __init__(self, kind):
        self.resource_type = kind


class _Route:
    def __init__(self, kind):
        self.request, self.done = _Request(kind), None

    def abort(self):
        self.done = "abort"

    def fallback(self):
        self.done = "load"


class _Page:
    def __init__(self):
        self.routes = []

    def route(self, pattern, handler):
        self.routes.append((pattern, handler))


def test_images_fonts_and_media_are_not_downloaded_but_pages_scripts_and_css_are(monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_SKIP_RESOURCE_TYPES", ("image", "media", "font"))
    page = _Page()
    BrowserClient._skip_heavy(page)
    [(pattern, handler)] = page.routes
    assert pattern == "**/*"
    for kind, expect in (("image", "abort"), ("font", "abort"), ("media", "abort"), ("document", "load"),
                         ("script", "load"), ("stylesheet", "load"), ("xhr", "load"), ("fetch", "load")):
        r = _Route(kind)
        handler(r)
        assert r.done == expect, kind


def test_switched_off_or_unsupported_page_changes_nothing(monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_SKIP_RESOURCE_TYPES", ())
    page = _Page()
    BrowserClient._skip_heavy(page)
    assert page.routes == []
    monkeypatch.setattr(settings, "BROWSER_SKIP_RESOURCE_TYPES", ("image",))
    BrowserClient._skip_heavy(object())              # a page without route(): no error


def test_a_failing_route_never_stops_the_collection(monkeypatch):
    class Broken:
        def route(self, *a):
            raise RuntimeError("closed")
    monkeypatch.setattr(settings, "BROWSER_SKIP_RESOURCE_TYPES", ("image",))
    BrowserClient._skip_heavy(Broken())
