"""The collection browser starts minimized (best effort) instead of opening in front of the dashboard."""
from collectors.browser_client import BrowserClient


class Session:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def send(self, method, params=None):
        if self.fail:
            raise RuntimeError("no cdp")
        self.calls.append((method, params))
        return {"windowId": 7}


class Page:
    def __init__(self, session):
        self.context = type("C", (), {"new_cdp_session": lambda _s, _p: session})()


def test_the_window_is_minimized_through_the_browser_protocol():
    s = Session()
    BrowserClient(page_factory=lambda: None)._minimize(Page(s))
    assert s.calls == [("Browser.getWindowForTarget", None),
                       ("Browser.setWindowBounds", {"windowId": 7, "bounds": {"windowState": "minimized"}})]


def test_a_browser_that_refuses_to_minimize_does_not_break_collection():
    BrowserClient(page_factory=lambda: None)._minimize(Page(Session(fail=True)))      # must not raise
