"""Tests. Older fixtures use arbitrary companies, so the dashboard's strict GCC/BFSI view filter is off by default here;
tests/test_strict_gcc_bfsi.py switches it on explicitly."""
from config import settings as _settings

_settings.DISPLAY_ONLY_GCC_BFSI = False
# The older vacancy-target tests assert exactly-N scraping; tests/test_contact_priority.py turns the candidate pool on explicitly.
_settings.COLLECTION_CANDIDATE_POOL_FACTOR = 1

# the fake postings in most tests carry fixed dates, so the strict 'posted within' check is switched on only by the tests of it
_settings.COLLECTION_STRICT_WINDOW = False
