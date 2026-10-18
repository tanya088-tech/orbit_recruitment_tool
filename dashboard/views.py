"""HTML for the two dashboard pages. Pure functions: data in, HTML string out.

Every piece of job/recruiter text goes through esc(), and a link is only rendered when
the URL is http(s). No inline scripts or styles (the server sends a strict CSP).
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote

from config import locations as loc_config
from config import settings
from dashboard import branding
from dashboard import viewmodel as vm
from processing import hiring_contacts as hc
from processing.description_sections import clean_description, extract_sections
from dashboard.viewmodel import Filters, Page, Posted, Row
from store.base import STATUSES

_LOGO_URL: Optional[str] = None


def set_logo(url: Optional[str]) -> None:
    """Set (or clear) the local URL of the Groxa AI logo shown in the header."""
    global _LOGO_URL
    _LOGO_URL = url


NOTICES = {
    "started": "Collection started. This page updates while it runs.",
    "already": "A collection is already running. Wait for it to finish before starting another.",
    "bad": "That collection option is not available.",
    "bad_source": "Tick at least one source to collect from.",
    "bad_count": "The number of vacancies must be a whole number from 1 to {max}, or left blank to collect all eligible vacancies.",
    "disabled": "Collection is turned off in demo mode.",
    "saved": "Showing the saved vacancies that match. No new search was run.",
    "restart_blocked": "The app cannot restart while a collection is running.",
}


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def na(text: str = "Not available") -> str:
    return f'<span class="na">{esc(text)}</span>'


def or_na(value: Any) -> str:
    return esc(value) if value not in (None, "") else na()


def list_href(filters: Filters, **overrides: Any) -> str:
    q = filters.to_query(**overrides)
    return "/?" + q if q else "/"


def detail_href(key: str, filters: Optional[Filters] = None) -> str:
    base = f"/job/{quote(key)}"
    q = filters.to_query() if filters else ""
    return f"{base}?q={quote(q)}" if q else base


def ring_html(p: Posted, now: datetime) -> str:
    if p.moment:
        step = round(vm.ring_fraction(p, now) * 12)
        return f'<span class="ring ring-{step}" aria-hidden="true"></span>'
    return f'<span class="ring {"ring-date" if p.day else "ring-none"}" aria-hidden="true"></span>'


def _powered_by() -> str:
    logo = (f'<img src="{esc(_LOGO_URL)}" alt="" height="22">' if _LOGO_URL else "")
    return (f'<a class="powered" href="{branding.SITE_URL}" target="_blank" rel="noopener noreferrer" '
            f'aria-label="Powered by Groxa AI">{logo}<span>Powered by <b>Groxa AI</b></span></a>')


def shell(title: str, body: str, run: Optional[dict], now: datetime, banner: Optional[str] = None) -> str:
    if run:
        when = vm.to_display_tz(vm.parse_iso_datetime(run["ingested_at"]) or now)
        runinfo = (f'Last scraper run added {esc(when.day)} {esc(f"{when:%b, %H:%M}")} {esc(settings.DISPLAY_TZ_LABEL)}: '
                   f'{int(run.get("new", 0))} new, {int(run.get("existing", 0))} already existing')
    else:
        runinfo = "No scraper run has been added yet"
    banner_html = f'<div class="banner">{esc(banner)}</div>' if banner else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} - Ace Talent Consulting Job Radar</title>
<link rel="icon" href="data:,"><link rel="stylesheet" href="/static/style.css"><script src="/static/app.js" defer></script></head>
<body>
<header class="topbar"><div class="topbar-inner">
  <a class="brand" href="/"><span class="logo"></span>Ace Talent Consulting <small>Job Radar</small></a>
  <div class="topbar-right"><div class="runinfo">{runinfo}</div>{_powered_by()}</div>
</div></header>
{banner_html}
<main class="container">
{body}
</main></body></html>"""


# ---------------------------------------------------------------- page 1
def _select(name: str, label: str, options: list[tuple[str, str]], current: str) -> str:
    """The dropdown always shows exactly what is applied: a value that is not in the list (or differs only in case)
    is shown rather than silently falling back to the first option."""
    match = next((v for v, _ in options if v.lower() == current.lower()), None) if current else ""
    if match is None:
        options = options + [(current, current)]
    elif match != current:
        current = match
    opts = "".join(
        f'<option value="{esc(v)}"{" selected" if v == current else ""}>{esc(t)}</option>' for v, t in options)
    return (f'<div class="field"><label for="f-{name}">{esc(label)}</label>'
            f'<select id="f-{name}" name="{name}" data-autosubmit>{opts}</select></div>')


def _filters_form(f: Filters, options: dict[str, list[str]]) -> str:
    scope = _select("scope", "Location scope", [(k, vm.SCOPE_LABELS[k]) for k in vm.SCOPE_OPTIONS], f.scope)
    emp = _select("employment", "Employment type", [(k, vm.EMPLOYMENT_LABELS[k]) for k in vm.EMPLOYMENT_OPTIONS], f.employment)
    state = _select("state", "State", [("", "All states")] + [(x, x) for x in options.get("states", [])], f.state)
    industry = _select("industry", "Industry Type", [("", "All industries")] + [(x, x) for x in options.get("industries", [])], f.industry)
    hq = _select("hq", "Parent Company Headquarters", [(k, vm.HQ_LABELS[k]) for k in vm.HQ_OPTIONS], f.hq)
    source = _select("source", "Source", [("", "All sources")] + [(x, x) for x in options.get("sources", [])], f.source)
    contact = _select("contact", "Contact Details Available", [(k, vm.CONTACT_LABELS[k]) for k in vm.CONTACT_OPTIONS], f.contact)
    mode = _select("work_mode", "Work mode", [(k, vm.WORK_MODE_LABELS[k]) for k in vm.WORK_MODE_OPTIONS], f.work_mode)
    sort = _select("sort", "Sort by", list(vm.SORT_LABELS.items()), f.sort)
    return f"""
<form class="filters" method="get" action="/" autocomplete="off">
  {'<input type="hidden" name="view" value="all">' if f.view == "all" else ""}
  <div class="filter-grid">
    {scope}{state}{emp}
    {mode}{industry}{hq}{source}{contact}{sort}
    <div class="filter-actions"><button class="btn btn-primary" type="submit">Apply filters</button>
      <a class="btn btn-reset" href="/" role="button" data-reset-filters title="Back to the default view: Within India, all states, no sorting or page">Reset filters</a></div>
  </div>
</form>"""


def _ledger(c: dict[str, int]) -> str:
    items = [("Total openings", c["total"]), ("Permanent openings", c["permanent"]), ("Contract openings", c["contract"])]
    return '<section class="ledger" aria-label="Summary">' + "".join(
        f'<div class="fig"><b>{n}</b><span>{esc(label)}</span></div>' for label, n in items) + "</section>"


def _status_chip(status: str) -> str:
    return f'<span class="status status-{esc(status.replace(" ", "-"))}">{esc(status)}</span>'


def _contact_cell(r: Row) -> str:
    """Recruiter contact shown straight in the list: only what the posting itself states (never looked up or guessed)."""
    parts = []
    if r.recruiter_name:
        parts.append(f'<div class="ct-name">{esc(r.recruiter_name)}</div>')
    for e in r.contact_emails:
        parts.append(f'<div><a href="mailto:{esc(e)}">{esc(e)}</a></div>' if _EMAIL.match(e) else f"<div>{esc(e)}</div>")
    for ph in r.contact_phones:
        parts.append(f'<div><a href="tel:{esc(re.sub(r"[^0-9+]", "", ph))}">{esc(ph)}</a></div>')
    li = vm.safe_http_url(r.contact_linkedin)
    if li:
        parts.append(f'<div><a href="{esc(li)}" target="_blank" rel="noopener noreferrer">LinkedIn profile</a></div>')
    if not parts or not r.contact_direct:
        return '<span class="ct-none">Not stated in the posting</span>'
    return "".join(parts)


NOT_STATED = "Not stated in posting"


def _original_link(r: Row) -> str:
    url = vm.safe_http_url(r.job_url)
    return (f'<div><a class="sub" href="{esc(url)}" target="_blank" rel="noopener noreferrer">View original</a></div>' if url else "")


def _row_html(r: Row, f: Filters, now: datetime, here: str) -> str:
    fresh = vm.freshness(r.posted, now)
    h = vm.age_hours(r.posted, now)
    hot = " hot" if fresh in ("just_posted", "fresh") else ""
    precision = vm.format_precision(r.posted)
    chip = _status_chip(r.status) if r.status != "New" else ""
    star_on = " on" if r.saved else ""
    return f"""<tr class="fresh-{fresh}">
<td class="c-flag">{'<span class="badge-new">New</span>' if r.is_new else ''}</td>
<td class="c-title"><a class="job-link" href="{esc(detail_href(r.key, f))}">{esc(r.display_title) if r.title else na("Untitled vacancy")}</a>{('<div>' + chip + '</div>') if chip else ''}</td>
<td>{or_na(r.company)}</td>
<td class="c-contact">{_contact_cell(r)}</td>
<td class="c-reviews">{esc(vm.format_company_reviews(r.company_rating, r.company_reviews))}</td>
<td>{or_na(r.location)}</td>
<td>{_industry_cell(r)}</td>
<td>{or_na(r.employment_type)}</td>
<td class="c-posted">{ring_html(r.posted, now)}<span class="{hot.strip()}">{esc(vm.format_age(r.posted, now))}</span>{f'<div class="sub">{esc(vm.format_posted_on(r.posted))}</div>' if vm.format_posted_on(r.posted) else ''}{f'<div class="sub">{esc(precision)}</div>' if precision else ''}</td>
<td>{or_na(", ".join(r.all_sources))}{_original_link(r)}</td>
<td class="c-act">
  <form class="inline" method="post" action="/job/{esc(quote(r.key))}/save">
    <input type="hidden" name="saved" value="{0 if r.saved else 1}"><input type="hidden" name="next" value="{esc(here)}">
    <button class="star{star_on}" type="submit" aria-label="{'Remove from saved jobs' if r.saved else 'Save job'}" title="{'Saved. Click to remove' if r.saved else 'Save job'}">{'&#9733;' if r.saved else '&#9734;'}</button></form>
  <a class="btn btn-sm" href="{esc(detail_href(r.key, f))}">View details</a></td>
</tr>"""


def _hiring_contact_rows(r: Row) -> list[str]:
    """Job Poster (confirmed: shown on the posting) and Suggested Recruiters (from the team's contact directory, never claimed to be the poster)."""
    def person(c) -> str:
        kind = ('<span class="tag tag-contact">Job Poster</span><span class="sub">Added by your team: ' + esc(c.entered_by or "") + ", " + esc(vm.format_iso_day(c.entered_at))
                + '. Seen on the LinkedIn posting under Meet the hiring team.</span>' if c.kind == hc.TEAM_POSTER else
                '<span class="tag tag-contact">Job Poster</span><span class="sub">Shown on the original job posting</span>' if c.kind == hc.JOB_POSTER
                else '<span class="tag tag-suggested">Suggested Recruiter</span><span class="sub">Not confirmed as the person who posted this job</span>')
        bits = [f"<strong>{esc(c.name)}</strong>" if c.name else ""]
        if c.designation:
            bits.append(esc(c.designation))
        if c.company:
            bits.append(esc(c.company))
        li = vm.safe_http_url(c.linkedin_url)
        if li:
            bits.append(f'<a href="{esc(li)}" target="_blank" rel="noopener noreferrer">LinkedIn profile</a>')
        if c.email and _EMAIL.match(c.email):
            bits.append(f'<a href="mailto:{esc(c.email)}">{esc(c.email)}</a>')
        if c.phone:
            bits.append(esc(c.phone))
        src = f'<span class="sub">Source: {esc(c.source)}</span>' if c.kind == hc.SUGGESTED and c.source else ""
        return kind + "<div>" + " &middot; ".join(b for b in bits if b) + "</div>" + src
    rows = [_group("Hiring contacts")]
    if r.poster is not None:
        rows.append(_row("Job poster", person(r.poster)))
    else:
        rows.append(_row("Job poster", '<span class="na">Not shown on the posting</span><span class="sub">The public page did not name who posted it</span>'))
    for i, c in enumerate(r.suggested_contacts, 1):
        rows.append(_row(f"Suggested recruiter {i}", person(c)))
    if not r.suggested_contacts:
        rows.append(_row("Suggested recruiters", '<span class="na">None on file for this company</span>'
                         '<span class="sub">Add recruiters from an authorised source with import_hiring_contacts.py</span>'))
    search = hc.linkedin_people_search_url(r.company)
    if search:
        rows.append(_row("Find on LinkedIn", f'<a href="{esc(search)}" target="_blank" rel="noopener noreferrer">Search recruiters at this company</a>'
                         '<span class="sub">Opens LinkedIn in your own session. This is a search shortcut, not a contact.</span>'))
    return rows


def _contact_rows(r: Row) -> list[str]:
    """The 'Recruiter and contact' block: only what the posting itself states."""
    phones = ", ".join(esc(p) for p in r.contact_phones) or or_na(None)
    emails = ", ".join(f'<a href="mailto:{esc(e)}">{esc(e)}</a>' if _EMAIL.match(e) else esc(e) for e in r.contact_emails) or or_na(None)
    urls = "<br>".join(f'<a href="{esc(u)}" target="_blank" rel="noopener noreferrer">{esc(u)}</a>' for u in r.contact_urls) or or_na(None)
    li_url = vm.safe_http_url(r.contact_linkedin)
    li = (f'<a href="{esc(li_url)}" target="_blank" rel="noopener noreferrer">{esc(li_url)}</a>'
          '<span class="sub">Written in the posting</span>') if li_url else or_na(None)
    by = (f'<span class="sub">Posted by {esc(r.posted_by)}</span>' if r.posted_by else "")
    if r.contact_direct:
        tag = ('<span class="tag tag-contact">Contact directly available</span>'
               '<span class="sub">Copied from the posting itself, word for word. Nothing was looked up elsewhere.</span>')
    else:
        tag = ('<span class="tag tag-nocontact">Contact not directly fetched</span>'
               '<span class="sub">This posting states no phone number, e-mail address or LinkedIn profile for the poster.</span>')
    rows = [_group("Recruiter and contact"), _row("Contact status", tag),
            _row("Recruiter / contact name", or_na(r.recruiter_name) + by),
            _row("Phone number", phones), _row("Email", emails), _row("LinkedIn profile", li), _row("Contact URL", urls)]
    return rows


def _industry_cell(r: Row) -> str:
    if r.industry == "Unknown":
        return na("Unknown")
    label = f' title="LinkedIn industry: {esc(r.industry_label)}"' if r.industry_label else ""
    return f'<span{label}>{esc(r.industry)}</span>'


def _fmt_time(iso: Optional[str], now: datetime) -> str:
    dt = vm.parse_iso_datetime(iso) if iso else None
    if not dt:
        return "never"
    local = vm.to_display_tz(dt)
    return f"{local.day} {local:%b %Y, %H:%M} {settings.DISPLAY_TZ_LABEL}"


_STOP_LABELS = {"target_reached": "Target reached", "exhausted": "Results exhausted", "incomplete": "Some places could not be searched",
                "blocked": "Finished (a source stopped early)", "interrupted": "Could not continue (interrupted)",
                "time_limit": "Could not continue (time limit)", "error": "Failed"}


def _counts_html(st: dict[str, Any]) -> str:
    """Requested number, unique vacancies collected and the outcome of the run that asked for a number."""
    target = st.get("target")
    state = st.get("state")
    if not target and not (st.get("window") and state in ("running", "succeeded", "partial")):
        return ""
    outcome = "Running" if state == "running" else _STOP_LABELS.get(st.get("stop_reason") or "", "Finished")
    if target:
        first = (f'<span>Requested: <b data-count-requested>{int(target)}</b></span>'
                 f'<span>Collected (unique): <b data-count-collected>{int(st.get("collected_unique") or 0)}</b></span>')
    else:   # no number entered: every eligible vacancy is collected, so there is no target to compare with
        first = ('<span>Mode: <b data-count-mode>All eligible vacancies (within search limits)</b></span>'
                 f'<span>Collected (unique): <b data-count-collected>{int(st.get("collected_unique") or 0)}</b></span>')
    return ('<p class="collect-counts" data-collect-counts>' + first + ''

            f'<span>New to history: <b data-count-new>{int(st.get("new_added") or 0)}</b></span>'
            f'<span>Already collected: <b data-count-had>{int(st.get("already_had") or 0)}</b></span>'
            f'<span>Rejected (not counted): <b data-count-rejected>{int(st.get("skipped_not_relevant") or 0) + int(st.get("skipped_out_of_scope") or 0)}</b></span>'
            f'<span>Status: <b data-count-status>{esc(outcome)}</b></span></p>' + _per_source_html(st))


def _per_source_html(st: dict[str, Any]) -> str:
    """One line per source: what each found, what it contributed to the list, and what the rules turned away."""
    ps = st.get("per_source") or {}
    if len(ps) < 2:
        return ""
    items = []
    for name, c in ps.items():
        got = (f'{int(c.get("in_result") or 0)} in your list, ' if c.get("in_result") is not None
               else f'{int(c.get("new") or 0) + int(c.get("existing") or 0)} collected, ')
        total = int(c.get("found") or 0) + int(c.get("already") or 0)
        known = f" ({int(c['already'])} already in your history)" if c.get("already") else ""
        items.append(f'<li><b>{esc(name)}</b>: {total} found{known}, {got}'
                     f'{int(c.get("not_relevant") or 0)} not GCC/BFSI, {int(c.get("out_of_scope") or 0)} outside the location scope</li>')
    return f'<ul class="collect-persource" data-collect-persource aria-label="Results by source">{"".join(items)}</ul>'


def _collection_panel(cv: Optional[dict[str, Any]], here: str, now: datetime, notice: str = "") -> str:
    """Run / refresh / restart controls plus the status of the last collection."""
    notice_html = (f'<p class="notice" role="status">{esc(NOTICES[notice].replace("{max}", str(settings.COLLECTION_TARGET_MAX)))}</p>'
                   if notice in NOTICES else "")
    if cv is None:
        return ""
    st = cv["status"]
    running = st["state"] == "running"
    enabled = cv["enabled"]
    done, total = int(st.get("search_done") or 0), int(st.get("search_total") or 0)
    labels = {"idle": "Not run yet", "running": "Running", "succeeded": "Last run finished", "partial": "Stopped early",
              "failed": "Last run failed"}
    reached = st["state"] == "succeeded" and st.get("stop_reason") == "target_reached" and bool(st.get("target"))
    if reached:
        labels["succeeded"] = "Target reached"
    success = (f'<p class="success" role="status" data-collect-success>Successfully run: target reached. '
               f'{int(st.get("collected_unique") or 0)} of {int(st["target"])} requested vacancies collected.</p>') if reached else ""
    last = (f'Last successful run: {esc(_fmt_time(st.get("last_success_at"), now))}'
            + (f' - {int(st["last_summary"].get("new", 0))} new, {int(st["last_summary"].get("existing", 0))} already in the history'
               if st.get("last_summary") and st.get("last_success_at") else "")
            if st.get("last_success_at") else "Last successful run: none yet")
    counts = _counts_html(st)
    progress = ""
    if running:
        progress = (f'<progress class="collect-bar" data-collect-bar max="{max(total, 1)}" value="{min(done, max(total, 1))}"></progress>'
                    f'<p class="sub" data-collect-detail>{esc("Place " + str(done + 1 if done < total else total) + " of " + str(total)) if total else ""}'
                    f'{" - " + esc(st["current_search"]) if st.get("current_search") else ""}{", page " + esc(st["current_page"]) if st.get("current_page") else ""}</p>')
    # A source that stopped early (e.g. LinkedIn HTTP 429) is not shown as a red banner; the vacancies collected are shown as usual
    # and the technical reason stays under Details and in the log.
    error = (f'<p class="error" role="alert" data-collect-error>{esc(st["last_error"])}</p>'
             if st.get("last_error") and st.get("stop_reason") != "blocked" else "")
    warnings = ""
    if st.get("warnings") or st.get("log_tail"):
        items = "".join(f"<li>{esc(w)}</li>" for w in st.get("warnings", [])[:8])
        tail = "\n".join(st.get("log_tail", [])[-12:])
        warnings = ("<details class=\"collect-log\"><summary>Details</summary>"
                    + (f"<p class=\"sub\">Problems reported by the collector:</p><ul>{items}</ul>" if items else "")
                    + (f"<pre>{esc(tail)}</pre>" if tail else "") + "</details>")
    # the form shows what the last run used (scope, window, number), so it never disagrees with the status above it
    # the form always opens with the defaults (LinkedIn + Naukri, India, last 24 hours); what the last run used is shown in its status above
    chosen_scope = cv["default_scope"] if cv["default_scope"] in loc_config.SCOPES else "india"
    chosen_window = settings.COLLECTION_DEFAULT_WINDOW
    chosen_sources = [s for s in settings.COLLECTION_DEFAULT_SOURCES if s in settings.SUPPORTED_SOURCES]
    count_value = int(st["target"]) if st.get("target") else ""
    scope_opts = "".join(
        f'<option value="{esc(k)}"{" selected" if k == chosen_scope else ""}>{esc(v)}</option>'
        for k, v in loc_config.SCOPES.items())
    disabled = " disabled" if (running or not enabled) else ""
    disabled_attr = disabled
    source_boxes = "".join(
        f'<label class="check"><input type="checkbox" name="source" value="{esc(s)}"'
        f'{" checked" if s in chosen_sources else ""}{disabled_attr}> {esc(s)}'
        + (f' <span class="sub">({esc(settings.SOURCE_FORM_NOTES[s])})</span>' if s in settings.SOURCE_FORM_NOTES else "")
        + '</label>' for s in settings.SUPPORTED_SOURCES)
    ff = st.get("fetch_filters") or {}
    def _fsel(name: str, label: str, opts: list) -> str:
        default = "yes" if (name == "contact" and not ff) else opts[0][0]       # vacancies with the poster's contact details first choice
        o = "".join(f'<option value="{esc(v)}"{" selected" if v == ff.get(name, default) else ""}>{esc(t)}</option>' for v, t in opts)
        return f'<div class="field"><label for="c-{name}">{esc(label)}</label><select id="c-{name}" name="f_{name}"{disabled}>{o}</select></div>'
    fetch_selects = (_fsel("state", "State", [("", "All states")] + [(x, x) for x in vm.all_indian_states()])
                     + _fsel("employment", "Employment type", [(k, vm.EMPLOYMENT_LABELS[k]) for k in vm.EMPLOYMENT_OPTIONS])
                     + _fsel("work_mode", "Work mode", [(k, vm.WORK_MODE_LABELS[k]) for k in vm.WORK_MODE_OPTIONS])
                     + _fsel("contact", "Contact Details Available", [(k, vm.CONTACT_LABELS[k]) for k in vm.CONTACT_OPTIONS]))
    gate_note = ('<p class="sub">Only openings that look like GCC or BFSI are kept.</p>' if settings.COLLECTION_ONLY_GCC_BFSI else "")
    off = ('<p class="sub">Collection is turned off in demo mode.</p>' if not enabled else "")
    return f"""
<section class="panel collect" aria-label="Job collection" data-collect-poll="{1 if running else 0}">
  <div class="collect-main">
    <h2 class="section">Job collection <span class="state state-{esc(st["state"])}" data-collect-state>{esc(labels.get(st["state"], st["state"]))}</span></h2>
    {notice_html}
    {success}
    <p class="collect-msg" data-collect-text>{esc(st.get("message") or "")}</p>
    {counts}
    {progress}
    <p class="sub" data-collect-last>{last}</p>
    {error}{off}
    {warnings}
  </div>
  <div class="collect-actions">
    <form method="post" action="/collection/run" class="collect-run">
      <label for="collect-scope">Where to collect</label>
      <select id="collect-scope" name="scope"{disabled}>{scope_opts}</select>
      <span class="sub">Where the tool searches, and which job locations it keeps. The Location scope filter below only changes what is shown.</span>
      <input type="hidden" name="sources_sent" value="1">
      <fieldset class="collect-sources"{disabled}><legend>Sources</legend>{source_boxes}</fieldset>
      {gate_note}
      <label for="collect-window">Posted within</label>
      <select id="collect-window" name="window"{disabled}>{"".join(f'<option value="{k}"{" selected" if k == chosen_window else ""}>{esc(v[1])}</option>' for k, v in settings.COLLECTION_WINDOWS.items())}</select>
      <fieldset class="collect-filters"{disabled}><legend>Only collect vacancies that match</legend>
        {fetch_selects}
        <span class="sub">Same filters as the list below, applied while fetching, so the vacancies collected already match them.</span>
      </fieldset>
      <label for="collect-count">Number of vacancies (optional)</label>
      <input id="collect-count" name="count" type="number" inputmode="numeric" min="1" max="{settings.COLLECTION_TARGET_MAX}" step="1"
             list="collect-count-choices" placeholder="Optional - leave blank for all" value="{count_value}"{disabled}>
      <datalist id="collect-count-choices">{"".join(f'<option value="{n}"></option>' for n in settings.COLLECTION_TARGET_CHOICES)}</datalist>
      <span class="sub" data-count-hint><b>With a number</b> ({", ".join(str(n) for n in settings.COLLECTION_TARGET_CHOICES)} or any number up to {settings.COLLECTION_TARGET_MAX}): collects up to that many eligible, unique vacancies. <b>Blank</b>: collects all eligible, unique vacancies from the period, sources and location chosen here, within the dashboard's search limits. Duplicates are not counted.</span>
      <button class="btn btn-primary" type="submit"{disabled}>{'Collection running...' if running else 'Run job collection'}</button>
      <button class="btn" type="submit" formaction="/collection/saved"{disabled} title="Instant: lists the vacancies already collected that match these choices. Nothing is searched.">Show saved vacancies</button>
    </form>
    <div class="collect-row">
      <a class="btn" href="{esc(here)}">Refresh dashboard</a>
      <form method="post" action="/app/restart"><button class="btn" type="submit"{" disabled" if running else ""}>Restart app</button></form>
    </div>
  </div>
</section>"""


def _sort_header(f: Filters, label: str, asc: str, desc: Optional[str] = None) -> str:
    target = asc if f.sort != asc else (desc or asc)
    return f'<a href="{esc(list_href(f, sort=target, page=1))}">{esc(label)}</a>'


def _result_banner(rs: Optional[dict[str, Any]], f: Filters) -> str:
    """Tells the recruiter the list is limited to their last "N vacancies" request, with a link to everything."""
    if not rs:
        return ""
    if f.view == "latest":
        n, want = rs.get("shown"), rs.get("target")
        text = (f"Your request{f' for {want}' if want else ''}"
                + (f" ({settings.COLLECTION_WINDOWS[rs['window']][1].lower()})" if rs.get("window") in settings.COLLECTION_WINDOWS else "")
                + f" collected {rs.get('collected', n)} vacancies. ")
        reasons = []
        if rs.get("hidden_by_rules"):
            k = rs["hidden_by_rules"]
            reasons.append(f"{k} {'is' if k == 1 else 'are'} hidden because {'it does' if k == 1 else 'they do'} not meet the current GCC/BFSI rules")
        if rs.get("hidden_by_scope"):
            k = rs["hidden_by_scope"]
            reasons.append(f"{k} {'is' if k == 1 else 'are'} outside the selected Location scope ({vm.SCOPE_LABELS.get(rs.get('scope'), '')})")
        shown_n = rs.get("in_scope", n)
        text += f"Showing {shown_n}" + (": " + "; ".join(reasons) + "." if reasons else ".")
        text += f" {rs['total']} collected jobs are kept in the history."
        link = f'<a class="btn btn-sm" href="{esc(list_href(f, view="all", page=1))}">Show all collected jobs</a>'
    else:
        text = f"Showing all collected jobs. Your last request for {rs.get('target')} vacancies has {rs.get('available')} of them."
        link = f'<a class="btn btn-sm" href="{esc(list_href(f, view="latest", page=1))}">Show only my last request</a>'
    return f'<p class="notice result-banner" role="status" data-result-banner>{esc(text)} {link}</p>'


def render_summary(rows_all: int, page: Page, cards: dict[str, int], f: Filters, options: dict[str, list[str]],
                   run: Optional[dict], now: datetime, banner: Optional[str] = None,
                   collection: Optional[dict[str, Any]] = None, hidden_by_scope: int = 0, notice: str = "",
                   result_set: Optional[dict[str, Any]] = None) -> str:
    here = list_href(f, page=page.page)
    if rows_all == 0:
        table = """<div class="tablewrap"><div class="empty"><h2>No vacancies yet</h2>
<p>Use <b>Run job collection</b> above to collect the latest jobs.</p></div></div>"""
    elif page.total == 0:
        table = """<div class="tablewrap"><div class="empty"><h2>No vacancies match these filters</h2>
<p>Try a wider posted window or clear a filter.</p><p><a class="btn" href="/" role="button">Reset filters</a></p></div></div>"""
    else:
        body = "\n".join(_row_html(r, f, now, here) for r in page.rows)
        table = f"""<div class="tablewrap"><table class="jobs">
<thead><tr><th></th><th>{_sort_header(f, "Job title", "title")}</th><th>{_sort_header(f, "Company", "company")}</th><th>Recruiter contact</th><th>Company Reviews</th>
<th>Location</th><th>Industry</th><th>Employment type</th><th>{_sort_header(f, "Posted", "recent", "oldest")}</th><th>Source</th><th></th></tr></thead>
<tbody>
{body}
</tbody></table></div>"""

    pager = ""
    if page.pages > 1:
        prev = f'<a class="btn btn-sm" href="{esc(list_href(f, page=page.page - 1))}">Previous</a>' if page.page > 1 else ""
        nxt = f'<a class="btn btn-sm" href="{esc(list_href(f, page=page.page + 1))}">Next</a>' if page.page < page.pages else ""
        pager = f'<nav class="pager" aria-label="Pages">{prev}<span>Page {page.page} of {page.pages}</span>{nxt}</nav>'

    showing = (f"Showing {page.start} to {page.end} of {page.total} vacancies" if page.total else "No matching vacancies")
    if f.active_count:
        showing += f" ({f.active_count} filter{'s' if f.active_count != 1 else ''} applied, {rows_all} in total)"
    if hidden_by_scope:
        showing += (f". {hidden_by_scope} other collected job{'s' if hidden_by_scope != 1 else ''} "
                    f"{'are' if hidden_by_scope != 1 else 'is'} hidden by the location scope")
    body = f"""
<div class="titlebar"><h1 class="page-title">Vacancies</h1>
<span class="btn-row"><a class="btn" href="/export.csv" download title="Download every eligible vacancy with all its details, newest first">Export CSV</a></span></div>
<p class="lede">Jobs collected from public job sites. The numbers below follow your filters.</p>
{_collection_panel(collection, here, now, notice)}
{_result_banner(result_set, f)}
{_ledger(cards)}
{_filters_form(f, options)}
<div class="resultbar"><span>{esc(showing)}</span></div>
{table}
{pager}"""
    return shell("Vacancies", body, run, now, banner)


# ---------------------------------------------------------------- page 2
def _hq_dd(r: Row) -> str:
    if r.hq_status == "outside":
        return f'Outside India ({esc(r.hq_country)})<span class="sub">Evidence: {esc(r.hq_evidence)}</span>'
    if r.hq_status == "india":
        return f'India<span class="sub">Evidence: {esc(r.hq_evidence)}</span>'
    return '<span class="na">Unknown</span><span class="sub">No reliable evidence of where the parent company is headquartered</span>'


def _industry_dd(r: Row) -> str:
    if r.industry == "Unknown":
        return '<span class="na">Unknown</span><span class="sub">The source did not state an industry</span>'
    sub = f'<span class="sub">Source label: {esc(r.industry_label)}</span>' if r.industry_label and r.industry_label != r.industry else ""
    return f"{esc(r.industry)}{sub}"


def _url_dd(url: Optional[str]) -> str:
    safe = vm.safe_http_url(url)
    return f'<a href="{esc(safe)}" target="_blank" rel="noopener noreferrer">{esc(safe)}</a>' if safe else na()


def _bullets(items: list[str], empty: str) -> str:
    if not items:
        return f'<p class="na">{esc(empty)}</p>'
    return "<ul class=\"points\">" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"


_EMAIL = re.compile(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']+$")


def _row(label: str, value_html: str) -> str:
    return f'<tr><th scope="row">{esc(label)}</th><td>{value_html}</td></tr>'


def _group(title: str) -> str:
    return f'<tr class="grp"><th colspan="2">{esc(title)}</th></tr>'


def _posted_html(r: Row, now: datetime) -> str:
    p = r.posted
    if not p.known:
        return na()
    note = {"exact time": "Exact time from the source",
            "estimated time": "Estimated from the source's relative time (for example, \"5 hours ago\")",
            "date only": "The source gave only the date, not a time"}.get(vm.format_precision(p), "")
    return (f'{ring_html(p, now)}{esc(vm.format_age(p, now))}<span class="sub">{esc(vm.format_moment(p))}'
            + (f" - {esc(note)}" if note else "") + "</span>")


def _also_listed_html(r: Row) -> str:
    items = []
    for a in r.also_listed_on:
        url = vm.safe_http_url(a.get("job_url"))
        name = esc(a.get("source") or "Another source")
        items.append(f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{name}</a>' if url else name)
    return "<br>".join(items) + '<span class="sub">The same vacancy, counted once</span>'


def _with_structured(found: list[str], structured: Optional[str]) -> list[str]:
    """The source's own structured value (JSON-LD) first, then what the description states; no repeats."""
    out = [structured] if structured else []
    out += [x for x in found if x.lower() != (structured or "").lower()]
    return out


def _company_link_row(r: Row) -> str:
    """LinkedIn jobs: the company's LinkedIn page. Other sources (Naukri): the company's website. Blank when not reliably known."""
    if (r.source or "").lower() == "linkedin":
        label, url = "Company LinkedIn Page", vm.safe_http_url(r.company_linkedin)
    else:
        label, url = "Company Website", vm.safe_http_url(r.company_website)
    value = ""
    if url:
        value = (f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(url)}</a>'
                 + (f'<span class="sub">{esc(r.company_link_note)}</span>' if r.company_link_note else ""))
    return _row(label, value)


def _details_table(r: Row, now: datetime) -> str:
    sec = extract_sections(r.description or "")
    company = (f'<a href="{esc(r.company_url)}" target="_blank" rel="noopener noreferrer">{esc(r.company)}</a>'
               if r.company and r.company_url else or_na(r.company))
    designation = or_na(r.designation) + {
        "seniority": '<span class="sub">LinkedIn seniority level</span>',
        "description": '<span class="sub">Stated in the job description</span>'}.get(r.designation_source, "") if r.designation else or_na(None)
    work_mode = esc(r.work_mode) if r.work_mode != "Unknown" else '<span class="na">Unknown</span><span class="sub">The posting does not state on-site, hybrid or remote</span>'
    first = vm.parse_iso_datetime(r.first_ingested_at)
    found = (f'{esc(vm.format_moment(vm.Posted(first, None, "x")))}'
             f'<span class="sub">Found in {r.times_seen} scraper run{"s" if r.times_seen != 1 else ""}</span>') if first else na()
    summary = f'<p class="description">{esc(sec.summary)}</p>' if sec.summary else na()
    full = (f'<div class="desc-box"><p class="description">{esc(clean_description(r.description))}</p></div>' if r.description
            else na("LinkedIn did not provide a description for this job. Open the original job to read it."))
    rows = "".join([
        _group("Vacancy"),
        _row("Company name", company),
        _company_link_row(r),
        _row("Job title", esc(r.title) if r.title else na("Untitled vacancy")),
        _row("Designation", designation),
        _row("Industry", _industry_dd(r)),
        _row("Parent company headquarters", _hq_dd(r)),
        _row("Location", or_na(r.location)),
        _row("Work mode", work_mode),
        _group("Posting"),
        _row("Employment type", or_na(r.employment_type) + (f'<span class="sub">Source says: {esc(r.employment_details)}</span>' if r.employment_details else "")),
        *([_row("Role category", esc(r.role_category) + (f'<span class="sub">Role: {esc(r.job_role)}</span>' if r.job_role else ""))] if r.role_category else []),
        *([_row("Openings", esc(r.openings))] if r.openings else []),
        *([_row("Applicants so far", esc(r.applicants))] if r.applicants else []),
        *([_row("Posted by", esc(r.posted_by))] if r.posted_by else []),
        _row("Posting date", _posted_html(r, now)),
        _row("Source", or_na(r.source) + (f'<span class="sub">Job ID {esc(r.job_id)}</span>' if r.job_id else "")),
        _row("Original job URL", _url_dd(r.job_url)),
        *([_row("Also listed on", _also_listed_html(r))] if r.also_listed_on else []),
        _row("First found by the tool", found),
        _group("Description"),
        *([_row("Salary", esc(r.salary))] if r.salary else []),
        _row("Job summary", summary),
        _row("Full job description", full),
        _group("Requirements"),
        _row("Key responsibilities", _bullets(list(sec.responsibilities), "Not available")),
        _row("Required qualifications and skills", _bullets(_with_structured(sec.qualifications, r.education_structured or r.education), "Not available")),
        _row("Experience required", _bullets(_with_structured(sec.experience, r.experience_structured or r.experience_text), "Not available")),
        *([_row("Key skills", esc(", ".join(r.skills)))] if r.skills else []),
        *_contact_rows(r), *_hiring_contact_rows(r),
    ])
    return (f'<table class="details" aria-label="Vacancy details"><tbody>{rows}</tbody></table>'
            '<p class="sub mt14">Summary, responsibilities, qualifications and experience are copied word for word from the posted '
            'description. Contact details are shown only when the job source provided them. Nothing is added or guessed.</p>')


def _workspace(r: Row, back_q: str, notes_when, link: str) -> str:
    key = esc(quote(r.key))
    qf = f'<input type="hidden" name="q" value="{esc(back_q)}">' if back_q else ""
    options = "".join(f'<option value="{esc(s)}"{" selected" if s == r.status else ""}>{esc(s)}</option>' for s in STATUSES)
    notes = "".join(f"""<li><div class="when"><span>{esc(notes_when(n.get("created_at")))}</span>
<form class="flush" method="post" action="/job/{key}/notes/{esc(quote(str(n.get("id", ""))))}/delete">{qf}
<button class="btn btn-quiet btn-sm" type="submit">Delete</button></form></div><p>{esc(n.get("text"))}</p></li>"""
                    for n in reversed(r.notes))
    return f"""<aside class="panel workspace" aria-label="Actions"><h2 class="section">Actions</h2>
<p class="actions">{link}</p>
<form method="post" action="/job/{key}/save">{qf}<input type="hidden" name="saved" value="{0 if r.saved else 1}">
  <button class="btn {'btn-primary' if not r.saved else ''}" type="submit">{'Remove from saved jobs' if r.saved else 'Save job'}</button></form>
<form method="post" action="/job/{key}/status">{qf}<label for="status">Recruitment status</label>
  <select id="status" name="status">{options}</select><div class="mt8"><button class="btn" type="submit">Update status</button></div></form>
<form method="post" action="/job/{key}/notes">{qf}<label for="note">Add a note</label>
  <textarea id="note" name="note" maxlength="2000" placeholder="What did you do, or what should the next recruiter know?" required></textarea>
  <div class="mt8"><button class="btn" type="submit">Add note</button></div></form>
<h3 class="section small">Notes ({len(r.notes)})</h3>
{('<ul class="notes">' + notes + '</ul>') if notes else '<p class="sub">No notes yet.</p>'}
<p class="sub mt14">Saved on this computer only, in data/recruiter_state.json.</p></aside>"""


def render_detail(r: Row, back_q: str, now: datetime, run: Optional[dict], banner: Optional[str] = None) -> str:
    back = "/?" + back_q if back_q else "/"
    back_label = "Back to vacancies"
    link = (f'<a class="btn btn-primary" href="{esc(r.job_url)}" target="_blank" rel="noopener noreferrer">Open Original Job</a>'
            if r.job_url else '<span class="btn" aria-disabled="true">Original link not available</span>')
    notes_when = lambda iso: (lambda dt: f"{dt.day} {dt:%b %Y, %H:%M} {settings.DISPLAY_TZ_LABEL}")(vm.to_display_tz(vm.parse_iso_datetime(iso) or now))
    body = f"""
<nav class="crumbs"><a href="{esc(back)}">{back_label}</a></nav>
<div class="detail-grid">
<div>
  <article class="panel job-head">
    <div>{'<span class="badge-new">New</span> ' if r.is_new else ''}{_status_chip(r.status) if r.status != 'New' else ''}{' <span class="tag tag-saved">&#9733; Saved</span>' if r.saved else ''}</div>
    <h1>{esc(r.title) if r.title else na("Untitled vacancy")}</h1>
    <p class="company">{or_na(r.company)}</p>
  </article>
  <section class="panel table-panel">{_details_table(r, now)}</section>
</div>
{_workspace(r, back_q, notes_when, link)}
</div>"""
    return shell(r.display_title, body, run, now, banner)


def render_restarting(now: datetime, boot_id: str = "") -> str:
    body = (f'<div class="msg" data-restart-poll="1" data-boot="{esc(boot_id)}"><h1>Restarting Ace Talent Consulting Job Radar</h1>'
            '<p data-restart-text>The app is restarting. This page reopens the dashboard as soon as it is ready.</p>'
            '<p><a class="btn" href="/">Open the dashboard now</a></p></div>')
    return shell("Restarting", body, None, now)


def render_message(title: str, message: str, back_href: str, run: Optional[dict], now: datetime,
                   banner: Optional[str] = None) -> str:
    body = (f'<div class="msg"><h1>{esc(title)}</h1><p>{esc(message)}</p>'
            f'<p><a class="btn" href="{esc(back_href)}">Back to vacancies</a></p></div>')
    return shell(title, body, run, now, banner)
