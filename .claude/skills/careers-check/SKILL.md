---
name: careers-check
description: Find which companies on a list have a selling role open (AE, SDR, BDR, business development, head of sales) on their own careers or applicant-tracking page, then review each hit by hand and return a short table of real buying signals. Triggers on "run the careers check", "who on this list is hiring sales", "check careers pages", or a CSV of companies with websites and a question about hiring.
version: 0.1.0
tags: [gtm, signals, sourcing]
tools: ["Read", "Write", "Bash", "WebFetch"]
---

# careers-check

A company hiring its first seller has decided to grow revenue and does not have the pipeline to feed
that hire yet. This skill finds those companies on a list you already have. It reads public pages only:
no logins, no LinkedIn, no personal data.

## Steps

1. **Get the list.** A CSV with a `Company` column and a `Website` column (`domain` or `site` also work;
   extra columns are carried through). If the user has none, offer the demo:
   `examples/companies.csv` with `--fixtures examples/fixtures` runs offline on 20 fictional companies.
2. **Self-test once per session.**
   `python -I .claude/skills/careers-check/scripts/careers_check.py --selftest` must print `0 failed`.
   If it does not, stop and report the failing line.
3. **Run.**
   `python -I .claude/skills/careers-check/scripts/careers_check.py --in <list.csv> --out out/careers-<YYYY-MM-DD>.json`
   Keep `--workers` at 4 or below. The script honours robots.txt and makes at most 4 requests per company.
4. **Review every hit by hand.** The script reads titles from HTML; it is a filter, not a verdict. For each
   hit, look at the `roles` lines and open `careers_url` when a line is ambiguous. Drop a hit when:
   - the role is customer success or support dressed as "account manager";
   - "partnership" means channel partners for a non-software business you would not sell to;
   - the page is stale (a dated posting older than 60 days, or "no open roles" elsewhere on the page);
   - the company is plainly outside the user's market (size, country, industry from their notes).
   Write one reason per kept or dropped row. Never keep a row "to be safe".
5. **Report.** A table, kept rows first:
   `Company | Role | Why it is a signal (one line) | Careers link`
   then one line: `N checked, H hits, K kept`. Save it next to the JSON as `out/careers-<date>.md`.

## Limits to tell the user

- Careers pages rendered only by JavaScript come back empty. A company the script misses is not proof
  that it is not hiring; check a few big names by hand.
- Titles are matched in English, German, Czech, Polish, Lithuanian and Ukrainian. Other languages need a
  line added to `SALES_TITLE`.
- This skill finds a signal. It never contacts anyone; what to say to whom is a separate step.
