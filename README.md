# gtm-os-starter

A Claude Code skill that finds which companies on your list are hiring a salesperson right now.

A company that opens its first AE, SDR or business-development role has decided to grow revenue and
has no pipeline to feed the new hire yet. That makes it a strong buying signal for anyone who sells to
software companies. Small companies often post the role only on their own careers page, which the big
job boards miss. This skill reads those pages.

It is one piece of **GTM OS**, the Claude Code setup I run my go-to-market agency
[Vurell](https://vurell.com) on. The full template and a 4-week course on making it yours are
coming: **[join the waitlist](https://vurell.com/gtm-os)**. I post what I build, with the numbers, on X: [@msabelnykov](https://x.com/msabelnykov).

## Try it in a minute (offline, fictional data)

```bash
git clone https://github.com/MacDelorian/gtm-os-starter
cd gtm-os-starter
claude
```

Then ask Claude: *"Run the careers check on the example list."* Or run the script directly:

```bash
python .claude/skills/careers-check/scripts/careers_check.py \
  --in .claude/skills/careers-check/examples/companies.csv \
  --fixtures .claude/skills/careers-check/examples/fixtures \
  --out hits.json
```

```
  HIT Brightloop                     Head of Sales (Poland & CEE)
  HIT Northwind Ledger               Founding Account Executive (EU, remote)
  HIT Quillbase                      SDR, French market
  HIT Verdigris Labs                 Mitarbeiter Vertrieb (m/w/d), Wien
20 companies checked, 4 with a selling role -> hits.json
```

The other 16 show what it skips on purpose: an engineering-only careers page, a "Salesforce Developer"
title, a "Talk to sales" button, a site whose robots.txt says no, and companies with no reachable site.

## On your own list

Any CSV with `Company` and `Website` columns:

```bash
python .claude/skills/careers-check/scripts/careers_check.py --in my-list.csv --out out/hits.json
```

Through Claude, the skill also reviews every hit by hand and gives you a table of the ones worth
acting on, with one reason each. Run on a real list, the script is a filter, not a verdict. When I ran
it over 2,668 startup sites from accelerator lists, it returned 125 hits. After review against my market
(European B2B software, a real selling role), 12 stayed.

## What it does and does not do

- Plain HTTP, standard-library Python, no API keys, no logins, no LinkedIn.
- At most 4 requests per company, robots.txt honoured, an identifying user agent.
- Every URL is checked before it is fetched: http(s) to a public address only, re-checked on each
  redirect. A link on someone else's page cannot reach your machine or your network.
- When a careers page links or embeds Greenhouse, Lever or Ashby, the roles come from that board's public
  JSON feed: exact titles, and it works where the page itself is drawn by JavaScript.
- Other careers pages rendered only by JavaScript still come back empty. Missing a company is not proof it
  isn't hiring.
- It finds the signal. It never contacts anyone.

## Requirements

Python 3.10+ and [Claude Code](https://claude.com/claude-code) if you want the review step.

## License

MIT. By Myroslav Sabelnykov, [Vurell](https://vurell.com).
