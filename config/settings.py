"""Central settings for the collectors.

Everything tunable lives here so you never have to dig through scraper code
to change delays, retry counts or limits.
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

from config.locations import INDIA_SEARCH_LOCATIONS
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = BASE_DIR / "logs"

# --- Politeness: we deliberately go slowly so we never hammer LinkedIn ---
REQUEST_DELAY_MIN = 1.5      # seconds between requests (random between min and max). 0.8-1.8 was refused by LinkedIn (HTTP 429) after ~120 postings; original was 2.0-4.5
REQUEST_DELAY_MAX = 3.0
REQUEST_TIMEOUT = 20         # seconds

# --- Retry behaviour ---
MAX_RETRIES = 3              # attempts per URL
BACKOFF_BASE = 5.0           # seconds; wait grows 5s, 10s, 20s ... (plus jitter)
BACKOFF_MAX = 60.0           # never wait longer than this per retry

# --- Circuit breaker: stop the run if LinkedIn keeps refusing us ---
MAX_CONSECUTIVE_FAILURES = 5

# --- Our own browser failing (page crash, network change) is not the site refusing us ---
BROWSER_RECOVERY_RETRIES = 2            # after a page crash / network change: re-open the page and load the same URL again this many times
BROWSER_RECOVERY_WAIT = 3.0             # seconds before re-trying after a crash (a network change waits 3x and 6x longer)
MAX_CONSECUTIVE_BROWSER_FAILURES = 3    # pages in a row that could not be loaded even after recovery: skip the rest of this place, do NOT report a block

# --- Search defaults ---
DEFAULT_DAYS = 7
DEFAULT_MAX_PAGES = 100      # LinkedIn now returns 10 results per page: 100 pages x 10 = its practical ~1000 cap
DEFAULT_MAX_JOBS_PER_SEARCH = 10   # small cap for test runs; 0 = unlimited

# How the search page offset ("start") advances between result pages.
#   "fixed"    - start = page * 25 (the original behaviour; assumes every page returns 25 listings)
#   "returned" - start advances by the number of listings the previous page actually returned, so no listing
#                is skipped if a page returns fewer than 25 (e.g. 10). Run verify_pagination.py once, then choose.
LINKEDIN_PAGINATION = "returned"   # live runs show 10 listings per page, so "fixed" skipped 15 of every 25

DEFAULT_KEYWORDS = ["GCC OR global capability center OR bank OR financial services OR insurance OR NBFC"]   # GCC (any industry) + BFSI
DEFAULT_LOCATIONS = list(INDIA_SEARCH_LOCATIONS)   # all of India (India-wide + major cities); no single-city default

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# --- Naukri: pages that only exist after JavaScript runs are read with a real browser engine (Playwright) ---
BROWSER_HEADLESS = False                      # Naukri refuses a window-less (headless) browser with HTTP 403. A normal visible window is used
                                              # for collection; do not close it while a run is going. True = no window (expect 403 from those sites)
BROWSER_MINIMIZE_WINDOW = True                # the collection browser is still a normal window (Naukri needs one) but starts minimized so it does not
                                              # cover your screen. False = show it. If Naukri results ever stop loading, set this to False.
BROWSER_SHARED_ACROSS_PLACES = True            # one browser window for the whole collection run instead of one per place (much faster)
BROWSER_SOURCES = ("naukri",)                  # sources that read pages with the browser
BROWSER_PROFILE_DIR = BASE_DIR / "data" / "browser_profile"   # cookies stay here between runs, like a normal browser profile
BROWSER_WAIT_MS = 15000                       # how long to wait for a page's job list / description to appear
BROWSER_SKIP_RESOURCE_TYPES = ()             # resource types the collection browser does not download, e.g. ("image", "media", "font").
                                              # Off: measured on Naukri (24 Oct) it made pages slower, not faster (every request passes through Python)

# --- Phase 3: dashboard & history ---
DATA_DIR = BASE_DIR / "data"                 # job_history.json + recruiter_state.json live here
DEMO_DATA_DIR = BASE_DIR / "data_demo"       # synthetic data for trying the UI (never mixed with real data)
POSTER_ENTRIES_FILE = DATA_DIR / "poster_entries.json"       # job posters added by the team after seeing them on LinkedIn (separate from the vacancy data)
HIRING_CONTACTS_FILE = DATA_DIR / "hiring_contacts.json"   # recruiters from an authorised source (see import_hiring_contacts.py); optional
DASHBOARD_HOST = "127.0.0.1"                 # local only. Do not expose to a network without adding login.
DASHBOARD_PORT = 8000
DASHBOARD_PAGE_SIZE = 50
DISPLAY_UTC_OFFSET_MINUTES = 330             # times are stored in UTC and shown in IST (India has no DST)
DISPLAY_TZ_LABEL = "IST"

# --- Collection started from the dashboard ("Run job collection") ---
# Uses the same scraper as run_collect.py, with the same politeness delays and circuit breaker above.
COLLECTION_KEYWORDS = DEFAULT_KEYWORDS            # change to widen or narrow what is searched
COLLECTION_DAYS = 30                              # LinkedIn "posted within" window (30 days = the dashboard's "Last month")
COLLECTION_MAX_JOBS_PER_SEARCH = 0                # 0 = no cap: take everything LinkedIn returns for each place
COLLECTION_MAX_PAGES = 100                        # 100 pages x 10 = LinkedIn's practical ~1000 results per search
COLLECTION_TIMEOUT_MINUTES = 1440                 # a run that takes longer than this is stopped
COLLECTION_DEFAULT_SCOPE = "india"                # "india" | "both" | "international"
COLLECTION_TARGET_CHOICES = (50, 100, 200)       # quick picks offered next to the "Number of vacancies" box
COLLECTION_WINDOWS = {"24h": (1, "Last 24 hours"), "3d": (3, "Last 3 days"), "7d": (7, "Last 7 days"), "30d": (30, "Last 30 days")}
COLLECTION_DEFAULT_WINDOW = "24h"                 # a "N vacancies" request means the N most recent from the last 24 hours unless changed
COLLECTION_TARGET_MAX = 1000                      # the largest number a recruiter can ask for in one run
# The client's eligibility rule: only GCC / BFSI employers headquartered OUTSIDE India, for vacancies located IN India.
# (Tests switch these off by default because their fake employers carry no headquarters evidence; the tests of the rule switch them on.)
REQUIRE_OVERSEAS_HQ = True
REQUIRE_INDIA_LOCATION = True
COLLECTION_STRICT_WINDOW = True                  # while collecting, drop postings whose own date shows they are older than the 'posted within' choice
COLLECTION_CANDIDATE_POOL_FACTOR = 2                # with a target N, gather up to N x this many newest candidates, then keep the best N (1 = exactly N)
COLLECTION_RECENCY_TOLERANCE_HOURS = 24           # postings within the same window of this many hours count as 'similar recency'
COLLECTION_SKIP_INELIGIBLE_BEFORE_FETCH = True    # do not download the detail page of a posting whose search card already shows a staffing / unnamed employer,
                                                  # or (with REQUIRE_OVERSEAS_HQ) an employer headquartered in India: it can never qualify
NAUKRI_KEYWORD_SHARE_FACTOR = 2                   # with a number of vacancies N, Naukri opens about N / keywords x this many postings per keyword
                                                  # (each keyword is a separate Naukri search), instead of N for every keyword. 0 = N per keyword (old)
NAUKRI_MAX_PAGES_PER_KEYWORD = 5                  # Naukri result pages read per search term (20 listings each); keeps a run with many terms bounded
NAUKRI_SEARCH_LOCATIONS = ("India",)              # where Naukri is searched instead of every Indian city in the list: one India-wide search per term
                                                  # (a city search for an employer mostly repeats the India-wide results). () = every city, as before
COLLECTION_KEEP_AWAKE = True                      # keep the computer from sleeping while a collection runs (the screen may still turn off).
                                                  # A critical battery or a closed lid can still put it to sleep
# What the dashboard searches on Naukri. Naukri does not understand "GCC" the way LinkedIn does (it returned mostly BPO, staffing and
# real-estate jobs), so Naukri searches the employers the client wants by name, plus a few role terms. Each entry is one Naukri search;
# results are merged newest first. Edit freely (fewer terms = faster). Empty list = use COLLECTION_KEYWORDS like LinkedIn.
NAUKRI_SEARCH_TERMS = [
    # global banks, insurers and financial-services groups with large India capability centres
    "JPMorgan Chase", "Wells Fargo", "Citi", "Bank of America", "Goldman Sachs", "Morgan Stanley", "Barclays", "HSBC",
    "Standard Chartered", "Deutsche Bank", "BNP Paribas", "UBS", "NatWest", "Lloyds Technology Centre", "State Street",
    "Northern Trust", "BNY", "American Express", "Synchrony", "Fidelity Investments", "BlackRock", "MetLife", "Chubb",
    "Allianz", "Societe Generale", "DBS Bank", "Mastercard", "Fiserv", "FIS Global", "Nomura", "MUFG", "Macquarie",
    "Swiss Re", "Commonwealth Bank",
    # role terms used by capability centres
    "global capability centre", "global in-house centre",
]
COLLECTION_PARALLEL_SOURCES = True               # search LinkedIn and Naukri at the same time (different sites, each keeps its own pacing)
COLLECTION_ROUNDS_PER_PLACE = 4                   # extra passes over one place when a pass added fewer unique vacancies than it fetched
SUPPORTED_SOURCES = ("LinkedIn", "Naukri")   # shown in the Source filter and the main collection form even before a source has any jobs
COLLECTION_DEFAULT_SOURCE = "LinkedIn"            # source pre-selected in the collection form (one source per run)
COLLECTION_SKIP_KNOWN_IDS = True                  # do not re-fetch detail pages for jobs already in the history

# Shown in the dashboard when a source blocks the tool (source name -> extra advice). Empty: the default message is used.
SOURCE_COOLDOWN_MINUTES = 45                  # after a source refuses us (e.g. LinkedIn HTTP 429) it is rested this long; starting sooner would only extend the block
SOURCE_BLOCK_ADVICE: dict = {"LinkedIn": "LinkedIn limits how quickly one internet connection may read its public pages. "
                             "The dashboard now rests LinkedIn for a while; use Show saved vacancies meanwhile and try again later."}
SOURCE_FORM_NOTES: dict = {}

# Keep only postings whose company/title/description/industry look like GCC or BFSI (the same keyword rules that set the
# "potential GCC / potential BFSI" tags). Others are not added to the history by dashboard collections. False = keep everything.
COLLECTION_ONLY_GCC_BFSI = True

# The dashboard lists only vacancies that pass the strict GCC/BFSI rules (processing/classifier.py), judged again every time the
# page is built - so older history saved under looser rules is hidden, never deleted. False = show everything in the history.
DISPLAY_ONLY_GCC_BFSI = True
