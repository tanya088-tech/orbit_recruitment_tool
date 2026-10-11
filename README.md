# Groxa AI — GCC/BFSI Job Radar (Phase 1: LinkedIn collection, Phase 2: Python filtering)

Collects publicly visible LinkedIn job postings for India and returns them as normalized
`Job` objects (also saved as JSON in `output/`). **Collection only** — no filtering, AI,
database, scheduler or email yet.

## Setup (macOS, Python 3.10+)
```bash
cd "Groxa AI Solution - Orbit"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run
```bash
python run_collect.py                      # default test run: 6 cities, last 7 days, 10 jobs per search
python run_collect.py --keywords "investment bank" --locations "Pune, India" --days 3
python run_collect.py --locations India --max-jobs-per-search 0   # full India run (no cap)
python -m pytest                           # run the tests
```
Output: `output/jobs_linkedin_<timestamp>.json`; logs: `logs/collect_<timestamp>.log`.
Exit code is 2 if LinkedIn blocked the run.

## How it works
1. `LinkedInSource.search()` calls LinkedIn's public (logged-out) search listing, page by page (25 per page).
2. For each listing it fetches the public job-detail fragment and parses title, company,
   description, location, employment type, posted date, URLs, job ID (+ raw data).
3. Each job is wrapped in its own error handling: a failed job is logged and skipped.
4. If LinkedIn rate-limits or shows a login wall, the run **stops** (we never bypass it).

## Layout
| Path | Purpose |
|---|---|
| `run_collect.py` | command-line entry point |
| `config/settings.py` | delays, retries, defaults |
| `models/job.py` | `Job`, `SearchParams`, `RunStats` |
| `collectors/base.py` | `JobSource` interface every source implements |
| `collectors/registry.py` | source name -> class |
| `collectors/collector.py` | orchestrator, stats, JSON output |
| `collectors/errors.py` | shared error types |
| `collectors/linkedin/` | `client.py` (HTTP), `search_parser.py`, `detail_parser.py`, `source.py` |
| `utils/` | logging, date parsing |
| `tests/` | parser + collector tests with saved sample HTML |

## Adding Naukri / Indeed later
Create `collectors/naukri/source.py` with a `JobSource` subclass (`name = "naukri"`, implement
`search()`), then `register_source(NaukriSource)` in `collectors/registry.py`.

## Known limits
LinkedIn's terms prohibit automated scraping; keep volumes low and run from a normal
(non-cloud) connection. Searches return ~1000 results max, so full-India coverage uses many
keyword x city searches. Selectors may need updating if LinkedIn changes its markup — only
the two parser files would change. The sample HTML in `tests/fixtures/` is hand-written;
replace with real saved pages after the first live run.


---

# Phase 2 — Python filtering (no AI)

```bash
python run_filter.py                                    # filters the newest output/jobs_*.json
python run_filter.py --input output/jobs_linkedin_<ts>.json
python run_filter.py --as-of 2026-10-08T10:00:00+00:00  # pretend "now" is this time (for old files)
python run_filter.py --include-ambiguous-date           # also keep date-only "yesterday" jobs
```
Output: `output/filtered_jobs_linkedin_<ts>.json` containing `summary`, `jobs` (kept) and `excluded`
(with reasons). The summary is also printed and written to `logs/filter_<ts>.log`.

A job is kept only if ALL four filters pass (every job is checked against all four, so each excluded
job lists every reason):
1. **Potential GCC or BFSI** — keyword rules over LinkedIn industry, company, title and description
   (`config/filter_rules.py`). This is *potential* only, never a confirmed classification.
2. **Employment type** — Full-time -> Permanent, Contract -> Contract. Everything else, and a missing
   type, is excluded (a missing type is never assumed Permanent).
3. **India location** — "India", Indian cities/states and common aliases; foreign countries win over
   look-alike names ("Hyderabad, Sindh, Pakistan" is rejected). Bare "Remote" is rejected.
4. **Posted within 24 hours** — see the limitation below.

## 24-hour limitation (important)
LinkedIn's public pages give only a calendar date and a relative age ("17 minutes ago"), never an exact
time, so an exact 24h window is not possible. Each kept job carries `posted_at`, `posted_at_precision`
and `posted_within_24h_certainty`:
- "N minutes/hours ago" -> posted time estimated as `collected_at - N` (+/- 1 unit); passes if <= 24h at filter time.
- "N days ago" (N >= 1) -> fails (LinkedIn rounds relative ages down, so the job is >= 24h old).
- Calendar date only -> same UTC day passes; the previous day is *ambiguous* and excluded unless
  `--include-ambiguous-date`; older fails.
- `collected_at` is only the clock the relative text was read against, never the posting date.
`first_seen_at` = Phase 1 `collected_at` (there is no database yet).

## Phase 1 date fix
Phase 1 used to turn "2 days ago" into a date by subtracting days from the local date, and that guess
overrode LinkedIn's own `<time datetime>` value, producing dates one day late. It now keeps LinkedIn's
date, stores the relative text as `posted_age_text`, and uses UTC. Old Phase 1 files still work: Phase 2
re-reads the date from the saved card HTML.

## New files
`config/filter_rules.py` (editable rule lists) · `processing/` (`classifier`, `employment`, `location`,
`posted`, `pipeline`) · `run_filter.py` · tests `test_classifier/employment/location/posted/pipeline.py`

## Phase 3 - Orbit Recruiter Dashboard

Data flow
```
run_collect.py     Phase 1: scrape LinkedIn            -> output/jobs_*.json
run_normalize.py   Phase 2 rules on EVERY job, no job removed -> output/normalized_jobs_*.json
run_ingest.py      deduplication / job history          -> data/job_history.json
run_dashboard.py   dashboard + dashboard filters        -> http://127.0.0.1:8000/
```
`run_filter.py` (the strict Phase 2 filter: GCC/BFSI + Permanent/Contract + India + last 24h) still works
and still writes `filtered_jobs_*.json`, but the dashboard no longer depends on it.

- `python run_ingest.py` adds the newest `output/normalized_jobs_*.json` to the history
  (`--input FILE` for a specific file - a `filtered_jobs_*.json` also works, `--force` to re-ingest a file).
- `python run_dashboard.py` serves http://127.0.0.1:8000/ (local machine only).
  Options: `--ingest` (ingest newest file first), `--open`, `--port N`,
  `--demo` (made-up vacancies in `data_demo/`, add `--reset-demo` to rebuild them).
- Dashboard scope: jobs Phase 2 placed in India. Jobs outside India or without a location stay in the history
  but are not listed (the page says how many).
- Filters (all use the stored Phase 2 fields): Location (states built from the scraped data), Job posted
  (24 hours / 3 days / 7 days / 15 days / 1 month / All), GCC / BFSI (All / GCC / BFSI),
  Employment type (All / Permanent / Contract), Work mode (All / On-site / Hybrid / Remote), Source (built from
  the sources in the data), plus company, keyword and saved only. Work mode comes from explicit wording only
  (Hybrid, Remote / work from home, On-site); everything else is Unknown and shows under All.
- Summary numbers (total, new, GCC, BFSI, permanent, contract) are counted from the filtered list.
  "New vacancies" = posted inside the selected Job posted range (with All: every job that has a posting date).
- A "New" badge on a row still means first found in the latest scraper run.
- Deduplication key: LinkedIn `job_id` (`linkedin-<id>`), else a hash of the normalized job URL.
  A job seen again is "existing", never "New". "New" = first seen in the latest ingested run.
- Recruiter actions (saved, status, notes) are stored separately in `data/recruiter_state.json`,
  so re-scraping never overwrites them.
- Storage sits behind `store/base.py` interfaces so the JSON files can be swapped for a database.
- Tests: `python -m pytest`.


## Dashboard update - launcher, collection from the dashboard, pan-India and international scope

### Start it without typing commands
Double-click **`Orbit Job Radar.command`** in this folder. A Terminal window opens (leave it open while you work) and the
dashboard opens in your browser. Closing that window stops the app. The first time, macOS may refuse to open it:
right-click the file, choose **Open**, then **Open** again. If the app is already running, double-clicking only opens the browser.

### Buttons on the dashboard
* **Run job collection** - pick *India only*, *India and international* or *International only*. It runs the unchanged
  `run_collect.py` in the background, then normalizes and adds the jobs to the history (duplicates are skipped).
  The panel shows progress (search N of M), the last successful run, and any error. Only one collection can run at a time
  (a second click, a second browser tab or a second Orbit window is refused).
* **Refresh dashboard** - reloads the list. (It also reloads by itself when a collection finishes.)
* **Restart app** - restarts the dashboard process. Refused while a collection is running.
* Demo mode (`--demo`) has collection turned off.

### What is collected
LinkedIn only (public pages, existing politeness delays, stops if LinkedIn refuses). The places searched are listed in
`config/locations.py` (India-wide plus about 37 Indian cities, and 14 countries). Keywords and limits are in `config/settings.py`
(`COLLECTION_*`); the default keyword is the GCC/BFSI one. The dashboard's **Location scope** is *not* that list: it is derived from the
country of each collected job (Within India / Outside India / All locations; jobs with no known country appear only under All).

### Filters, columns, details
Filters: Location scope, Employment type, Source, Job posted, Work mode (Remote shown because the data supports it).
KPI cards: Total, Permanent and Contract openings, following the filters. **Industry** comes only from LinkedIn's own industry label
(Unknown if absent, Other if unmapped). The details page shows summary, responsibilities, qualifications and experience copied
word for word from the description when it has matching headings, otherwise "Not available". Contact fields appear only if the source gave them.

### Logo
"Powered by Groxa AI" shows the logo from https://www.groxaai.com/ when the app can download it (once, at start, cached in
`dashboard/static/groxa-logo.png`); otherwise the text alone is shown.

### Tests
`python -m pytest` (168 tests in this build, run with a stand-in runner; please run the real one on your Mac).

### Collection defaults (updated)
Run job collection now searches **every place in `config/locations.py`** (India-wide plus about 37 Indian cities), with **no cap on jobs**,
up to 40 pages per place and the last 30 days. Each place is collected, saved and added to the history before the next one starts, so
a problem in one place never loses the others. `run_collect.py` with no options also searches all of India now (it used to search 6 cities).
A full run takes hours; the status panel shows which place is being searched.

### Interruptions, recovery and faster collection
* **Recovery:** if the app is closed or interrupted (for example Ctrl+C in the Terminal window) during a collection, the next start
  adds any jobs the run had already saved to `output/jobs_*.json` that were never added to the history (once only, no duplicates,
  recruiter data untouched) and clears the old lock. The panel never stays on "running" after an interruption.
* **Known jobs are skipped:** before each place the dashboard gives the scraper the IDs already in the history, so their detail pages are
  not fetched again (`COLLECTION_SKIP_KNOWN_IDS` in `config/settings.py`). Jobs skipped this way are not re-saved, so their "last seen"
  time is not refreshed by a collection.
* **Progress** shows the place (N of 38) and the result page being read.
* **Pagination:** run `python verify_pagination.py` once (3 requests). If it says pages hold only 10 listings, set
  `LINKEDIN_PAGINATION = "returned"` in `config/settings.py`. The default is unchanged until you do.

## Accuracy of extracted details, and choosing how many vacancies to collect

**Experience, qualifications and designation.** The scraper and the history always kept the full description; the details
page pulls the short "Experience required" / "Required qualifications" / "Designation" rows out of that text. Those
rows were missing for postings that put the value under an `Experience:` heading (for example IDFC FIRST Bank's
"Senior Database Administrator": `Experience:` then `- 10 – 18 years.`) or that give only a range such as `0-2 years`.
`processing/description_sections.py` is shared by every source and now reads:
headings such as *Experience*, *Total experience*, *Required work experience*; lines such as `8+ years in ...`,
`Minimum of 4 years ...`, `5 to 8 yrs`; and `Designation:` / `Role/Job Title:` lines. Company-history sentences
("over 170 years of history") and education lists are not treated as experience. The wording is copied exactly;
a field is "Not available" only when the posting really does not state it. LinkedIn's "Show more / Show less" button
text, which was saved at the end of every description, is removed when pages are parsed and again when shown.
When a page carries structured `experienceRequirements` / `educationRequirements` (JSON-LD), they are kept and shown first.
Nothing stored is rewritten: the rows are derived from the stored description each time a page is shown, so
every earlier vacancy benefits straight away.

**Number of vacancies.** The collection panel asks for *Posted within* (default **Last 24 hours**; also 3, 7 or 30 days) and a *Number of vacancies* (50, 100, 200, or any whole number up to
`COLLECTION_TARGET_MAX`, 1000) and nothing is scraped until it is submitted. N means **the N most recent postings** on
LinkedIn: the search is newest-first and the scraper stops after N unique postings. A posting already in your history counts
as one of the N (it is not fetched or stored twice); a posting repeated in the run counts once. The dashboard then lists
exactly those N vacancies, with a banner and a *Show all collected jobs* link; nothing is ever removed from the history.
Places are searched in the usual order and later places are used only if the earlier ones had fewer than N.
The panel shows Requested, Collected (unique), New to history, Already collected and a status: *Target reached*,
*Results exhausted* (fewer exist than requested; the message gives the real count), or *Could not continue*
(source refusal, interruption, time limit). Requests stay sequential with the same delays. Only LinkedIn is implemented.
