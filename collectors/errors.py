"""Error types shared by every source (LinkedIn now, Naukri/Indeed later).

The collector reacts differently to each, which is why they are separate:
  * NotFoundError  -> this one job/page is gone; skip it and carry on.
  * FetchError     -> a request failed; log it, skip this item, carry on.
  * BlockedError   -> the site is refusing us (rate limit / login wall).
                      We STOP that source. We never try to get around it.
  * LocalBrowserError -> our own browser crashed or lost its network. Not the site's doing: the page is re-opened
                      and the load retried a couple of times; it is never reported as a block.
  * ParseError     -> page loaded but did not look like we expected.
  * SetupError     -> this source cannot run on this computer yet (for example the browser add-on it needs is
                      not installed). The run for that source stops with a clear instruction.
"""


class CollectorError(Exception):
    pass


class FetchError(CollectorError):
    pass


class NotFoundError(FetchError):
    pass


class BlockedError(FetchError):
    pass


class LocalBrowserError(FetchError):
    """The browser on THIS computer failed (the page crashed, the browser closed, the network changed).
    The site refused nothing, so this is never treated as a block and never starts a cooldown."""


class ParseError(CollectorError):
    pass


class SetupError(CollectorError):
    pass
