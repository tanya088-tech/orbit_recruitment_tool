"""Tests. Older fixtures use arbitrary companies, so the dashboard's strict GCC/BFSI view filter is off by default here;
tests/test_strict_gcc_bfsi.py switches it on explicitly."""
from config import settings as _settings

_settings.DISPLAY_ONLY_GCC_BFSI = False
# The older vacancy-target tests assert exactly-N scraping; tests/test_contact_priority.py turns the candidate pool on explicitly.
_settings.COLLECTION_CANDIDATE_POOL_FACTOR = 1

# the fake postings in most tests carry fixed dates, so the strict 'posted within' check is switched on only by the tests of it
_settings.COLLECTION_STRICT_WINDOW = False
_settings.COLLECTION_SKIP_INELIGIBLE_BEFORE_FETCH = False

# Older fixtures use invented employers (Acme Bank ...) with no headquarters evidence and some use Indian employers; the client's
# overseas-headquarters / India-location rule is switched on explicitly by tests/test_overseas_hq.py.
_settings.REQUIRE_OVERSEAS_HQ = False
_settings.REQUIRE_INDIA_LOCATION = False
