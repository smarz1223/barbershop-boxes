#!/usr/bin/env python3
"""
Barbershop Boxes — site rebuild script.

Fetches the published Google Sheet CSV (weekly scores), combines it with
static_data.json (box <-> combo mapping + taken boxes + historical odds,
which only change when Marz re-enters a new season's PDF grids or box
ownership), recomputes everything derived from actual results, and
re-injects the result into template.html to produce index.html.

Run manually:  python3 build_site.py
Run in CI:     see .github/workflows/update.yml
"""
import csv
import io
import json
import sys
import urllib.request

CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSSqnOreovEnyrN3yYrEmT3C0o3feAnqYWhwT4Y9a31ScUn1bghN-6bzMoRLuqt3_ozFAErCLp8xBsS/pub?gid=1438455700&single=true&output=csv"

DAYS = ["THU", "SUN", "MON"]
STRAIGHT_BASE = 700
REVERSE_BASE = 200


def fetch_csv(url):
    with urllib.request.urlopen(url, timeout=30) as resp:
        text = resp.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def load_static(path="static_data.json"):
    with open(path) as f:
        return json.load(f)


def find_box(entries_by_week_day, week, day, home_digit, away_digit):
    for e in entries_by_week_day.get((week, day), []):
        if e["home"] == home_digit and e["away"] == away_digit:
            return e["box"]
    return None


def build(static_data, csv_rows):
    entries = static_data["entries"]
    taken = static_data["taken"]  # {"1": "TAKEN"/"NOT TAKEN", ...}
    pivot = static_data["pivot"]

    entries_by_week_day = {}
    for e in entries:
        entries_by_week_day.setdefault((e["week"], e["day"]), []).append(e)

    # index CSV rows by (week, day)
    scores = {}
    for row in csv_rows:
        wk = row.get("WEEK")
        day = row.get("DAY")
        if not wk or not day:
            continue
        scores[(int(wk), day)] = row

    weekly = {d: [] for d in DAYS}
    leaderboard = {str(e["box"]): {"box": e["box"], "status": taken.get(str(e["box"]), "NOT TAKEN"),
                                    "times_hit": 0, "winnings": 0}
                   for e in entries if e["day"] == "THU" and e["week"] == 1}  # one row per unique box (100)

    running_rollover = {d: {"straight": 0, "reverse": 0} for d in DAYS}
    current_week = None

    for wk in range(1, 19):
        week_complete = True
        for day in DAYS:
            row = scores.get((wk, day))
            home_score = row.get("HOME TEAM SCORE") if row else None
            away_score = row.get("AWAY TEAM SCORE") if row else None
            played = bool(home_score) and bool(away_score)

            if not played:
                week_complete = False
                weekly[day].append({"week": wk, "score": "-", "straight_box": None,
                                     "straight_pay": 0, "reverse_box": None, "reverse_pay": 0})
                continue

            home_last = int(float(home_score)) % 10
            away_last = int(float(away_score)) % 10
            score_label = f"{home_last}-{away_last}"

            straight_box = find_box(entries_by_week_day, wk, day, home_last, away_last)
            reverse_box = find_box(entries_by_week_day, wk, day, away_last, home_last)

            straight_pay = 0
            if straight_box is not None:
                if taken.get(str(straight_box)) == "TAKEN":
                    straight_pay = STRAIGHT_BASE + running_rollover[day]["straight"]
                    running_rollover[day]["straight"] = 0
                    lb = leaderboard[str(straight_box)]
                    lb["times_hit"] += 1
                    lb["winnings"] += straight_pay
                else:
                    running_rollover[day]["straight"] += STRAIGHT_BASE

            reverse_pay = 0
            if reverse_box is not None:
                if taken.get(str(reverse_box)) == "TAKEN":
                    reverse_pay = REVERSE_BASE + running_rollover[day]["reverse"]
                    running_rollover[day]["reverse"] = 0
                    lb = leaderboard[str(reverse_box)]
                    lb["times_hit"] += 1
                    lb["winnings"] += reverse_pay
                else:
                    running_rollover[day]["reverse"] += REVERSE_BASE

            weekly[day].append({"week": wk, "score": score_label, "straight_box": straight_box,
                                 "straight_pay": straight_pay, "reverse_box": reverse_box,
                                 "reverse_pay": reverse_pay})

        if current_week is None and not week_complete:
            current_week = wk

    if current_week is None:
        current_week = 18

    leaderboard_list = list(leaderboard.values())
    leaderboard_list.sort(key=lambda x: (-x["winnings"], -x["times_hit"]))
    top_dollar_box = max(leaderboard_list, key=lambda x: x["winnings"])
    top_hit_box = max(leaderboard_list, key=lambda x: x["times_hit"])

    return {
        "entries": entries,
        "taken": leaderboard,
        "pivot": pivot,
        "weekly": weekly,
        "rollover": running_rollover,
        "leaderboard": leaderboard_list,
        "top_dollar_box": top_dollar_box,
        "top_hit_box": top_hit_box,
        "current_week": current_week,
    }


def main():
    static_data = load_static()
    try:
        csv_rows = fetch_csv(CSV_URL)
    except Exception as exc:
        print(f"ERROR fetching CSV: {exc}", file=sys.stderr)
        sys.exit(1)

    site_data = build(static_data, csv_rows)

    with open("template.html") as f:
        template = f.read()

    out = template.replace("__DATA__", json.dumps(site_data))

    with open("index.html", "w") as f:
        f.write(out)

    print(f"Built index.html — current_week={site_data['current_week']}, "
          f"rollover={site_data['rollover']}")


if __name__ == "__main__":
    main()
