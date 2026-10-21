#!/usr/bin/env python3
"""careers_check.py -- which companies on your list have a selling role open on their own careers page?

A company that is hiring its first salesperson, SDR or business developer has just decided to grow
revenue and does not yet have the pipeline to feed that hire. That is the buying signal this checks.
Small companies often post the role only on their own site or applicant-tracking page, not on the big
job boards, so this looks there.

PER COMPANY (plain HTTP, no logins, at most 4 requests):
    0. robots.txt; a site that disallows the pages below is skipped;
    1. the home page; a link to a known applicant-tracking host (Workable, Lever, Greenhouse, Ashby,
       Teamtailor, Recruitee, Personio, BambooHR, Breezy, JOIN, SmartRecruiters, Homerun, Pinpoint), or a
       link whose URL or label says careers / jobs / join us / vacancies;
    2. that page (else /careers, then /jobs);
    3. short lines that name a selling title, at most 5 per company.

Input: a CSV with a Company column and a Website column (any case; "domain" or "site" also works).
Output: JSON list of companies WITH a selling role: company, site, careers_url, roles, plus your other
columns untouched.

Usage:
    python careers_check.py --in companies.csv --out hits.json [--workers 4]
    python careers_check.py --in examples/companies.csv --fixtures examples/fixtures --out hits.json   # offline demo
    python careers_check.py --selftest

Standard library only. Every URL is checked before it is fetched: http(s) to a public address only, the
same check on every redirect, so a link on a third-party page cannot reach your own machine or network.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import ipaddress
import json
import re
import socket
import sys
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

UA = "gtm-os-careers-check/0.1 (+https://github.com/MacDelorian/gtm-os-starter)"

# The title itself must name a selling role. English plus the common European forms
# (Czech, Polish, Lithuanian, Ukrainian, German).
SALES_TITLE = re.compile(
    r"business develop|\bbdm?\b|\bbdr\b|\bsdr\b|lead gen|(?<!pre-)(?<!pre)\bsales\b(?!force)|account exec|"
    r"account manager|partnership|new business|growth manager|vertrieb|obchod|prodej|handlow|sprzeda|"
    r"pardavim|продаж|лідген", re.I)
ATS = re.compile(r"(workable\.com|lever\.co|greenhouse\.io|ashbyhq\.com|teamtailor\.com|recruitee\.com|personio\.(de|com)|"
                 r"bamboohr\.com|breezy\.hr|join\.com|smartrecruiters\.com|homerun\.co|pinpointhq\.com)", re.I)
# Strict on purpose: GTM sites are full of "hiring signals" and "job changes" feature links.
# A careers link is a path segment of its own, or a link whose whole label is a careers word.
CAREER_PATH = re.compile(r"/(careers?|jobs|join(-us|-the-team)?|karriere|kariera|vacancies|open-(positions|roles)|"
                         r"work-with-us|hiring)(/|$|\?|\.html?)", re.I)
CAREER_LABEL = re.compile(r"^(careers?|jobs|join us|join the team|work with us|we'?re hiring|we are hiring|now hiring|"
                          r"open (positions|roles)|vacancies|karriere|jobs & karriere|kariera)$", re.I)
# a heading-sized match only: a selling title sits in a short line, not in a paragraph about sales
ROLE_LINE = re.compile(r"(?:^|[>\n|•·])\s*([^<>\n|•·]{0,60}?(?:" + SALES_TITLE.pattern + r")[^<>\n|•·]{0,60})", re.I)
NOT_A_ROLE = re.compile(r"sales@|contact sales|talk to sales|sales team will|book a demo|pricing", re.I)
# marketing copy, not a job title: a sentence, or a line that talks to or about "you"/"we"
COPY = re.compile(r"[.!?]\s|[.!?]$|\b(we|we're|our|us|you|your|you're)\b", re.I)


def looks_like_title(line: str) -> bool:
    # a title starts with a capital: "the GTM brain used in every sales call" (ramp.com, 10-21) is copy
    return len(line.split()) <= 8 and not COPY.search(line) and line[:1].isupper()


# ---------------------------------------------------------------- fetching

def check_public_url(url: str) -> None:
    """Refuse anything but http(s) to a public address. Runs on every URL and every redirect."""
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError(f"refused non-http(s) URL: {url[:80]}")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"cannot resolve {p.hostname}: {e}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
                or ip.is_unspecified or (ip.version == 6 and ip.ipv4_mapped and not ip.ipv4_mapped.is_global)):
            raise ValueError(f"refused non-public address {ip} for {p.hostname}")


class _PublicRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Only http, https and the checked redirect handler: no file://, ftp:// or data: handlers at all.
_OPENER = urllib.request.OpenerDirector()
for _h in (urllib.request.HTTPHandler(), urllib.request.HTTPSHandler(), _PublicRedirects(),
           urllib.request.HTTPErrorProcessor(), urllib.request.HTTPDefaultErrorHandler()):
    _OPENER.add_handler(_h)


def http_get(url: str) -> str:
    check_public_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en;q=0.9,*;q=0.5"})
    with _OPENER.open(req, timeout=20) as r:
        return r.read(3_000_000).decode(r.headers.get_content_charset() or "utf-8", "replace")


def fixture_getter(root: Path):
    """Offline demo: https://acme.example/careers -> <root>/acme.example/careers.html, / -> index.html."""
    def get(url: str) -> str:
        p = urllib.parse.urlsplit(url)
        name = p.path.strip("/") or "index"
        f = root / (p.hostname or "") / (name if "." in name else f"{name}.html")
        if not f.resolve().is_relative_to(root.resolve()) or not f.exists():
            raise FileNotFoundError(url)
        return f.read_text(encoding="utf-8")
    return get


def text(h: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def robots_disallows(robots: str, path: str) -> bool:
    """Minimal robots.txt reading for the * group: is `path` disallowed?"""
    applies, rules = False, []
    for raw in robots.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, val = (s.strip() for s in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            applies = val == "*"
        elif applies and key in ("allow", "disallow") and val:
            rules.append((key, val))
    best = None
    for key, val in rules:  # longest matching rule wins, as in RFC 9309
        if path.startswith(val) and (best is None or len(val) > len(best[1])):
            best = (key, val)
    return bool(best and best[0] == "disallow")


# ---------------------------------------------------------------- applicant-tracking feeds
# Greenhouse, Lever and Ashby publish every open role as public JSON. When a careers link or an embed points
# at one of them, the titles come from the feed: exact, and it works where the page is drawn by JavaScript.
# (Suggested in a reply on X, 2026-10-21.)
FEEDS = [
    (re.compile(r"https?://(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?([A-Za-z0-9_-]+)", re.I),
     lambda m: f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs", "jobs", "title"),
    (re.compile(r"https?://jobs\.(eu\.)?lever\.co/([A-Za-z0-9_-]+)", re.I),
     lambda m: f"https://api.{'eu.' if m.group(1) else ''}lever.co/v0/postings/{m.group(2)}?mode=json&limit=100", None, "text"),
    (re.compile(r"https?://jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)", re.I),
     lambda m: f"https://api.ashbyhq.com/posting-api/job-board/{m.group(1)}", "jobs", "title"),
]


def ats_feed(page_or_url: str):
    """The first Greenhouse/Lever/Ashby board named in a URL or a page, as (feed url, list key, title field)."""
    for rx, make, key, field in FEEDS:
        m = rx.search(page_or_url or "")
        if m and m.group(m.lastindex).lower() not in ("embed", "jobs", "api"):
            return make(m), key, field
    return None


def feed_roles(raw: str, key, field) -> list[str]:
    data = json.loads(raw)
    items = data.get(key, []) if key else data
    out: list[str] = []
    for it in items if isinstance(items, list) else []:
        title = re.sub(r"\s+", " ", str((it or {}).get(field) or "")).strip()
        if title and SALES_TITLE.search(title) and not NOT_A_ROLE.search(title) and title not in out:
            out.append(title)
    return out[:5]


# ---------------------------------------------------------------- reading

def careers_url(site: str, home: str) -> str:
    links = re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', home, re.S | re.I)
    for href, _label in links:
        if ATS.search(href):
            return href if href.startswith("http") else urllib.parse.urljoin(site, href)
    own = (urllib.parse.urlsplit(site).hostname or "").removeprefix("www.")
    for href, label in links:
        full = urllib.parse.urljoin(site + "/", href)
        host = (urllib.parse.urlsplit(full).hostname or "").removeprefix("www.")
        if host != own and not host.endswith("." + own):
            continue  # off-site and not an applicant-tracking host: a community page, a partner, a blog
        if CAREER_PATH.search(urllib.parse.urlsplit(full).path) or CAREER_LABEL.match(text(label).strip(" →›»")):
            return full
    return ""


def roles_in(page: str) -> list[str]:
    body = re.sub(r"<(script|style|nav|footer)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    body = re.sub(r"<(h[1-6]|li|a|p|div|span|td)[^>]*>", "\n", body, flags=re.I)
    out: list[str] = []
    for m in ROLE_LINE.finditer(html.unescape(re.sub(r"<[^>]+>", " ", body))):
        line = re.sub(r"\s+", " ", m.group(1)).strip(" -–:")
        if 4 < len(line) <= 120 and looks_like_title(line) and not NOT_A_ROLE.search(line) and line not in out:
            out.append(line)
    return out[:5]


def check(row: dict, get=http_get, respect_robots: bool = True) -> dict | None:
    site = row["site"] if row["site"].startswith("http") else "https://" + row["site"]
    site = site.rstrip("/")
    robots = ""
    if respect_robots:
        try:
            robots = get(site + "/robots.txt")
        except Exception:
            robots = ""
    if robots_disallows(robots, "/"):
        return None
    try:
        home = get(site + "/")
    except Exception:
        return None
    url = careers_url(site, home)
    feed = ats_feed(url)
    if feed:
        try:
            roles = feed_roles(get(feed[0]), feed[1], feed[2])
            return {**row, "careers_url": url, "roles": roles, "via": "ats feed"} if roles else None
        except Exception:
            pass  # the feed failed; read the page instead
    tries = [url] if url else [site + "/careers", site + "/jobs"]
    for u in tries:
        same_site = urllib.parse.urlsplit(u).hostname == urllib.parse.urlsplit(site).hostname
        if same_site and robots_disallows(robots, urllib.parse.urlsplit(u).path or "/"):
            continue
        try:
            page = get(u)
        except Exception:
            continue
        feed = ats_feed(page)  # an own careers page that embeds or links its ATS board: the feed is exact
        if feed:
            try:
                roles = feed_roles(get(feed[0]), feed[1], feed[2])
                return {**row, "careers_url": u, "roles": roles, "via": "ats feed"} if roles else None
            except Exception:
                pass
        roles = roles_in(page)
        if roles:
            return {**row, "careers_url": u, "roles": roles}
    return None


def read_rows(paths: list[str]) -> list[dict]:
    rows, seen = [], set()
    for f in paths:
        with open(f, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                low = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
                site = low.get("website") or low.get("domain") or low.get("site") or ""
                name = low.get("company") or low.get("name") or site
                if site and site not in seen:
                    seen.add(site)
                    extra = {k: v for k, v in low.items() if k not in ("website", "domain", "site", "company", "name")}
                    rows.append({"company": name, "site": site, **extra})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Find companies with a selling role open on their own careers page.")
    ap.add_argument("--in", dest="inp", action="append", help="CSV with Company and Website columns (repeatable)")
    ap.add_argument("--out", help="where to write the JSON list of hits")
    ap.add_argument("--workers", type=int, default=4, help="parallel companies (default 4; be polite)")
    ap.add_argument("--fixtures", type=Path, help="offline demo: read pages from this folder instead of the web")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.inp or not a.out:
        ap.error("--in and --out are required")
    sys.stdout.reconfigure(encoding="utf-8")
    get = fixture_getter(a.fixtures) if a.fixtures else http_get
    rows = read_rows(a.inp)
    hits, done, lock = [], [0], threading.Lock()

    def work(r):
        h = check(r, get=get)
        with lock:
            done[0] += 1
            if h:
                hits.append(h)
                print(f"  HIT {h['company'][:30]:30} {h['roles'][0][:70]}", file=sys.stderr)
            if done[0] % 25 == 0:
                print(f"  ... {done[0]}/{len(rows)} checked, {len(hits)} with a selling role", file=sys.stderr)

    with ThreadPoolExecutor(max(1, a.workers)) as ex:
        list(ex.map(work, rows))
    hits.sort(key=lambda h: h["company"].lower())
    Path(a.out).write_text(json.dumps(hits, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(rows)} companies checked, {len(hits)} with a selling role -> {a.out}")
    return 0


def selftest() -> int:
    ok = bad = 0

    def t(name, cond):
        nonlocal ok, bad
        ok, bad = (ok + 1, bad) if cond else (ok, bad + 1)
        if not cond:
            print("FAIL", name)

    home = '<a href="/about">About</a><a href="https://apply.workable.com/acme/">Jobs</a>'
    t("an ATS link wins", careers_url("https://acme.example", home) == "https://apply.workable.com/acme/")
    t("a careers link is found by its label", careers_url("https://acme.example", '<a href="/p/42">Join us</a>') == "https://acme.example/p/42")
    t("a 'job changes' feature link is not a careers page", careers_url("https://x.example", '<a href="/signals">Job changes</a>') == "")
    t("an off-site /join/ link is not this company's careers page",
      careers_url("https://x.example", '<a href="https://community.other.example/join/">Join</a>') == "")
    t("a careers subdomain counts", careers_url("https://www.x.example", '<a href="https://jobs.x.example/">Jobs</a>') == "https://jobs.x.example/")
    t("a careers path is found", careers_url("https://x.example", '<a href="/company/careers/">Team</a>') == "https://x.example/company/careers/")
    page = "<ul><li>Senior Backend Engineer</li><li>Business Development Manager (DACH)</li><li>Account Executive</li></ul><p>Talk to sales</p>"
    r = roles_in(page)
    t("selling roles are listed", any("Business Development Manager" in x for x in r) and any("Account Executive" in x for x in r))
    t("an engineer is not a selling role", not any("Backend" in x for x in r))
    t("a contact-sales button is not a role", not any("Talk to sales" in x for x in r))
    t("marketing copy is not a role", roles_in("<h2>Sales is harder than ever. We're here to help.</h2><p>Today, 40,000+ sales teams use it.</p>") == [])
    t("a 'hiring signals' feature link is not a careers page", careers_url("https://x.example", '<a href="/signals">Hiring signals</a>') == "")
    t("a 'we're hiring' link is", careers_url("https://x.example", "<a href=\"/team\">We're hiring</a>") == "https://x.example/team")
    t("a Greenhouse board maps to its feed", ats_feed("https://job-boards.greenhouse.io/acme")[0] == "https://boards-api.greenhouse.io/v1/boards/acme/jobs")
    t("a Greenhouse embed maps to its feed", ats_feed('<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme">')[0].endswith("/boards/acme/jobs"))
    t("a Lever EU board maps to the EU feed", ats_feed("https://jobs.eu.lever.co/acme/")[0].startswith("https://api.eu.lever.co/v0/postings/acme"))
    t("an Ashby board maps to its feed", ats_feed("https://jobs.ashbyhq.com/acme")[0] == "https://api.ashbyhq.com/posting-api/job-board/acme")
    t("feed titles keep only selling roles", feed_roles('{"jobs":[{"title":"Account Executive"},{"title":"Backend Engineer"},{"title":"Salesforce Developer"}]}', "jobs", "title") == ["Account Executive"])
    t("a Lever list feed is read", feed_roles('[{"text":"SDR, DACH"},{"text":"Designer"}]', None, "text") == ["SDR, DACH"])
    fake = {"https://x.example/robots.txt": "", "https://x.example/": '<a href="https://jobs.ashbyhq.com/x">Careers</a>',
            "https://api.ashbyhq.com/posting-api/job-board/x": '{"jobs":[{"title":"Founding Account Executive"}]}'}
    hit = check({"company": "X", "site": "x.example"}, get=lambda u: fake[u])
    t("check() reads the ATS feed", bool(hit) and hit["roles"] == ["Founding Account Executive"] and hit["via"] == "ats feed")
    t("a lowercase line is copy, not a title", roles_in("<p>the GTM brain used in every sales call</p>") == [])
    t("a German selling title", bool(SALES_TITLE.search("Mitarbeiter Vertrieb (m/w/d)")))
    t("Salesforce developer is not a selling role", not SALES_TITLE.search("Salesforce Developer"))
    t("robots: disallow all", robots_disallows("User-agent: *\nDisallow: /", "/careers"))
    t("robots: longer allow wins", not robots_disallows("User-agent: *\nDisallow: /\nAllow: /careers", "/careers"))
    t("robots: other bots' rules ignored", not robots_disallows("User-agent: BadBot\nDisallow: /", "/"))
    for bad_url in ("file:///C:/Windows/win.ini", "http://127.0.0.1:9222/json/version", "http://localhost/",
                    "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data/", "ftp://example.com/x", "http://[::1]/"):
        try:
            check_public_url(bad_url)
            refused = False
        except ValueError:
            refused = True
        t(f"refuses {bad_url[:40]}", refused)
    print(f"careers_check: {ok} passed, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
