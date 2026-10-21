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

## Phase 3 - Ace Talent Consulting Recruiter Dashboard

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
Double-click **`Ace Talent Consulting Job Radar.command`** in this folder. A Terminal window opens (leave it open while you work) and the
dashboard opens in your browser. Closing that window stops the app. The first time, macOS may refuse to open it:
right-click the file, choose **Open**, then **Open** again. If the app is already running, double-clicking only opens the browser.

### Buttons on the dashboard
* **Run job collection** - pick *India only*, *India and international* or *International only*. It runs the unchanged
  `run_collect.py` in the background, then normalizes and adds the jobs to the history (duplicates are skipped).
  The panel shows progress (search N of M), the last successful run, and any error. Only one collection can run at a time
  (a second click, a second browser tab or a second Ace Talent Consulting window is refused).
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
(source refusal, interruption, time limit). Requests stay sequential with the same delays. LinkedIn, Naukri and Indeed are implemented (next section).

## Sources: LinkedIn and Naukri (Indeed was removed)

The collection panel has a **Sources** tick-box per source (LinkedIn is ticked by default). Each ticked source is collected on its own,
place by place, with the same delays, then normalized and added to the history. With a vacancy count N, every ticked source is asked
for its N most recent postings, the lists are merged (an opening listed twice counts once) and the N most recently posted are shown.
The **Source** filter lists LinkedIn, Naukri and Indeed (one at a time, as before); a vacancy that is on several sources appears under each,
and its **Source** column and details page list every source with its link ("Also listed on").

**One-time setup for Naukri and Indeed.** Both build their pages with JavaScript, so they are read through a real browser engine:
`pip install -r requirements.txt` then `playwright install chromium`. Until then those sources report "could not run: browser support is
not installed" and LinkedIn is unaffected. Check them on your Mac before relying on them: `python verify_sources.py` (add `--visible`
to watch the browser). It reads one search page and one job page per source and prints every field it found or could not find.

**Duplicates across sources.** The same real URL, or the same company + title + city appearing on a *different* source, is stored as one
vacancy; the first-collected record stays the primary one, missing fields are filled from the other source, and the other source's id and
link are kept. Two postings from the *same* source are never merged by this rule. It is a heuristic: if two different openings share
company, title and city on different sites they will show as one row (both links are kept).

**Limits you should know about** (nothing here is bypassed):
* The tool never solves CAPTCHAs, logs in, or works around a security check. If Naukri or Indeed shows one, that source stops, what was
  collected is kept, and the panel says so. Indeed in particular shows a "Security Check" to automated visitors; its job pages may
  not be retrievable from your network, in which case Indeed returns nothing rather than partial data. Both sites' terms restrict automated access.
* Indeed's result cards carry no posting date; The tool shows the date only when the job page states one, otherwise "Not available".
  Indeed's date filter supports 1, 3, 7 and 14 days (longer windows are capped at 14).
* Naukri's visible experience (e.g. "0 - 2 years") is used; the machine-readable `monthsOfExperience` in its page data is ignored because it is
  wrong for most postings. "Not disclosed" salaries are stored as missing, not as a salary.
* "Show more / View more" buttons are clicked before a Naukri or Indeed page is read. LinkedIn's public page already contains the
  whole description, so no click is needed there.
* The Indeed job-page selectors could not be checked against a live page from the build environment (the security check appeared), so
  they are covered by tests on a fixture of Indeed's markup only. Run `verify_sources.py` to confirm on your machine.

**Naukri/Indeed browser window.** These sources run in a normal, visible browser window (`BROWSER_HEADLESS = False` in
`config/settings.py`) because they answer a window-less browser with HTTP 403 "Access Denied". A window opens during
collection; leave it alone until the run ends, and do not run `verify_sources.py` at the same time (they share one
browser profile). Naukri is searched one keyword at a time ("GCC OR bank OR financial services" = three searches):
a comma list makes Naukri drop the freshness filter. If a source answers 403 or shows a security check, the dashboard
says which source, the status and what the page said, does not retry, and continues with the other ticked sources.

## Indeed removed; company website; posted-time wording

* **Indeed** is no longer a source (its security check refuses automated browsers). Its code is parked, unused, in `retired/`.
  Existing history is untouched. LinkedIn and Naukri are the only sources in the collection form, filter and Source column.
* **Company website** (details page, Vacancy group). Shown only when a source states it: Naukri's "About the company" website link.
  LinkedIn's public pages never give one, so a LinkedIn job shows the website only if another listing of the exact same company
  name stated one and all such listings agree (it says "Taken from another listing of this company"). Otherwise the cell is blank.
  Confidential employers never borrow a website. Websites are stored from the next Naukri collection onward.
* **Posted time** reads the same for both sources: "Just now" or "N hours ago" inside 24 hours, then "1 day ago", "2 days ago"...
  It is worked out from the posting time when there is one (exact, or estimated from the source's "5 hours ago"). When a source gives only
  a date, whole days are counted and today's date shows "Today", because no hour can be known.

## GCC / BFSI only

Dashboard collections now keep only postings that look like GCC or BFSI openings (the same keyword rules that set the
"potential GCC / BFSI" tags: company, title, description and industry). Postings that match neither are fetched, judged and
**not added** to the history; the status message says how many were skipped. With a vacancy count N the collector keeps searching
(up to the usual rounds per place) until it has N relevant postings or runs out, and a rejected posting is not fetched twice in a run.
This is a keyword indication, not a confirmed classification, so an opening with unusual wording can be missed. Existing history is not
touched. To keep everything again set `COLLECTION_ONLY_GCC_BFSI = False` in `config/settings.py`.


## Strict GCC / BFSI filtering (LinkedIn and Naukri)

Only GCC or BFSI vacancies are collected and shown. The same rules (`processing/classifier.py`, word lists in `config/filter_rules.py`) run for every source:

* **BFSI** - the employer's industry (LinkedIn "Industries" / Naukri "Industry Type") is banking, financial services, insurance, lending, payments, capital markets, investment, wealth etc.; or the company name says so (and no different industry is stated); or the job title is specific BFSI work (underwriter, actuary, KYC/AML, credit risk, investment banking ...) at an employer not stated to be in another industry.
* **GCC** - the company name or the posting describes the employer as a Global Capability / Global In-house / captive / shared-services / Global Business Services centre, or a technology/delivery centre of a multinational group.
* **Never enough on their own:** words such as HR, recruiter, talent acquisition, manager, analyst, operations, technology, finance - in the title or description. An HR role at a confirmed GCC/BFSI employer is kept; the same role elsewhere is not.
* **Never eligible:** recruitment/staffing employers, agency postings ("hiring for our client"), unnamed ("Confidential") employers, and anything without clear evidence.

The check runs when a job is collected (before it is saved) and again whenever the dashboard is built, so older history saved under looser rules is hidden without being deleted (`DISPLAY_ONLY_GCC_BFSI` in `config/settings.py`; `python check_history.py` shows what is hidden and why - it changes nothing).

## October 2026 fixes

* **Every LinkedIn listing is read.** LinkedIn's public search now returns 10 listings per page, so paging advances by the number
  of listings actually returned (`LINKEDIN_PAGINATION = "returned"`); the old 25-per-page step skipped 15 of every 25. The page
  cap was raised from 40 to 100 (`DEFAULT_MAX_PAGES`, `COLLECTION_MAX_PAGES`) so a search can still reach LinkedIn's ~1000 results.
* **Overseas headquarters rule is on** (`REQUIRE_OVERSEAS_HQ = True`): only GCC / BFSI employers headquartered outside India are
  kept. Indian employers (Axis Bank, AU Small Finance Bank, Bajaj Finserv ...) are hidden from the dashboard, never deleted.
* **Known GCC employers.** `KNOWN_GCC_EMPLOYERS` in `config/filter_rules.py` lists multinationals whose India presence is a
  capability centre (global banks, insurers, tech companies ...); a vacancy there is tagged GCC even when the posting never says
  "GCC". `KNOWN_GCC_MIXED_EMPLOYERS` lists groups that also run an ordinary Indian business (factories, shops, field sales): they
  count only for capability-centre titles (software, data, finance operations ...). Branch, retail-banking, store and field-sales
  roles are never GCC from the name alone (they can still be BFSI). Both lists also give the headquarters country. Edit freely.
* **One source per run.** The collection form now has a Source dropdown (LinkedIn or Naukri) instead of tick boxes, so a
  quick source never fills the requested number on its own while the other is still searching. Run the other source separately.
* **Stop search button.** While a collection runs, *Stop search* ends it: the vacancies found so far are saved and added as usual,
  and no further place is searched (Mac and Windows).
* **Faster Naukri.** Cards from employers that can never qualify (staffing firms, and India-headquartered employers while the
  overseas rule is on) are no longer opened, and each Naukri keyword search opens only its share of the requested number
  (`NAUKRI_KEYWORD_SHARE_FACTOR`) instead of the full number for every keyword.
* **Naukri searches by employer.** Naukri does not understand "GCC" the way LinkedIn does, so it now searches the employers the
  client wants by name (`NAUKRI_SEARCH_TERMS` in `config/settings.py`: global banks, insurers and capability-centre terms), each
  term reading at most `NAUKRI_MAX_PAGES_PER_KEYWORD` result pages. LinkedIn keeps `COLLECTION_KEYWORDS`.
* **Naukri locations.** Indian towns Naukri writes without the country ("Kotputli, Bhiwadi", "Sonipat( Kundli )") are read as
  India; foreign places ("Saudi Arabia", "Doha", "Qatar, GCC, Gulf") stay foreign.
* **Cards not worth opening.** A Naukri card whose title is clearly not GCC / BFSI work (telecaller, voice process, property
  advisor, restaurant ...; `CARD_TITLE_SKIP_PATTERNS` in `config/filter_rules.py`) is not opened, unless the employer is a known
  GCC / overseas-headquartered group.
