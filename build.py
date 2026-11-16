"""Builds README.md from jobs that companies first published on their own boards in the last 24 hours."""
import concurrent.futures as cf
import csv
import datetime as dt
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
COMPANIES = json.loads((ROOT / "companies.json").read_text(encoding="utf-8"))
WINDOW_H = 24
WAITLIST = "https://rizgarozan.github.io/waitlists/earlyapply/?r=github"
ENTRY = re.compile(r"\b(new ?grad|graduate|entry[- ]level|junior|jr\.?|early[- ]career|apprentice|intern|internship|university|campus)\b", re.I)
NOT_ENTRY = re.compile(r"\b(senior|sr\.?|staff|principal|lead|head|director|manager|vp)\b", re.I)
now = dt.datetime.now(dt.timezone.utc)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "earlyapply-jobs (github.com/RizgarOzan/earlyapply-jobs)"})
    return json.load(urllib.request.urlopen(req, timeout=40))


def greenhouse(slug, name):
    for j in get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")["jobs"]:
        if j.get("first_published"):  # updated_at is not an opening date, skip jobs without it
            yield name, j["title"], (j.get("location") or {}).get("name", ""), j["absolute_url"], j["first_published"]


def lever(slug, name):
    for j in get(f"https://api.lever.co/v0/postings/{slug}?mode=json"):
        t = dt.datetime.fromtimestamp(j["createdAt"] / 1000, dt.timezone.utc).isoformat()
        yield name, j["text"], j["categories"].get("location", ""), j["hostedUrl"], t


def ashby(slug, name):
    for j in get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")["jobs"]:
        if j.get("isListed", True) and j.get("publishedAt"):
            yield name, j["title"], j.get("location", ""), j["jobUrl"], j["publishedAt"]


SOURCES = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}


def load(c):
    out = []
    for co, title, loc, url, opened in SOURCES[c["ats"]](c["slug"], c["name"]):
        t = dt.datetime.fromisoformat(opened)
        hours = (now - t).total_seconds() / 3600
        if 0 <= hours < WINDOW_H:
            sep = "&" if "?" in url else "?"
            out.append(dict(company=co, title=" ".join(title.split()), location=" ".join(loc.split()),
                            url=f"{url}{sep}utm_source=earlyapply", opened=t.astimezone(dt.timezone.utc), hours=hours))
    return out


def row(j):
    cell = lambda s: s.replace("|", "/")
    return f"| {cell(j['company'])} | [{cell(j['title'])}]({j['url']}) | {cell(j['location']) or '-'} | {j['opened']:%b %d, %H:%M} |"


def main():
    jobs, ok, failed = [], [], []
    with cf.ThreadPoolExecutor(16) as ex:
        futures = {ex.submit(load, c): c for c in COMPANIES}
        for f in cf.as_completed(futures):
            try:
                jobs += f.result()
                ok.append(futures[f]["name"])
            except Exception as e:  # one broken board should not stop the list
                failed.append(f"{futures[f]['name']} ({str(e)[:40]})")
    jobs.sort(key=lambda j: j["hours"])
    entry = [j for j in jobs if ENTRY.search(j["title"]) and not NOT_ENTRY.search(j["title"])]
    header = "| Company | Role | Location | Opened (UTC) |\n|---|---|---|---|"

    lines = [
        "# Jobs opened in the last 24 hours",
        "",
        f"Updated **{now:%b %d, %Y, %H:%M} UTC**. {len(jobs)} roles that {len(ok)} companies first published on their own job boards (Greenhouse, Lever, Ashby) in the 24 hours before this update. Newest first.",
        "",
        "These come straight from each company's public board, often before the role shows up on LinkedIn or Indeed. The list refreshes every day. Star the repo to keep it handy.",
        "",
        f"Want it filtered to your role, level and where you can work? **[Join the Earlyapply waitlist]({WAITLIST})**. Earlyapply never applies for you.",
        "",
        f"## Entry-level, new grad and internships ({len(entry)})",
        "",
        "Picked by job title, so some roles land in the wrong place.",
        "",
    ]
    lines += [header] + [row(j) for j in entry] if entry else ["None in the last 24 hours."]
    lines += ["", f"## All roles ({len(jobs)})", "", header] + [row(j) for j in jobs]
    lines += [
        "",
        "## How this list is made",
        "",
        "A small script (`build.py`) reads each company's public job board API once a day and keeps roles whose first published time is under 24 hours old. No AI writes or picks anything here. Greenhouse jobs without a first published date are left out. Companies are in `companies.json`; open an issue to suggest one.",
        "",
        f"Boards read this run: {len(ok)}." + (f" Failed: {', '.join(sorted(failed))}." if failed else ""),
    ]
    (ROOT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    counts = ROOT / "data" / "counts.csv"
    rows = list(csv.reader(counts.open(encoding="utf-8"))) if counts.exists() else [["date_utc", "roles_24h", "entry_24h", "boards_ok"]]
    rows = [r for r in rows if r[0] != f"{now:%Y-%m-%d}"] + [[f"{now:%Y-%m-%d}", len(jobs), len(entry), len(ok)]]
    with counts.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    print(f"{len(jobs)} roles, {len(entry)} entry, {len(ok)} ok, failed: {failed}")


if __name__ == "__main__":
    main()
