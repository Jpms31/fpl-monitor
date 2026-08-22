# FPL mini-league monitor collector
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE = "https://fantasy.premierleague.com/api"
LEAGUE_ID = 369689
MY_ENTRY_ID = 1766059
OUT_PATH = os.path.join("data", "latest.json")
USER_AGENT = "fpl-monitor/1.0 (+https://github.com/Jpms31/fpl-monitor)"


def fetch_json(url, retries=4, timeout=30):
    last = None
    for attempt in range(retries):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json,text/plain,*/*",
                    "Referer": "https://fantasy.premierleague.com/",
                },
            )
            with urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Failed to fetch {url}: {last}")


def current_event(bootstrap):
    events = bootstrap.get("events", [])
    current = next((e for e in events if e.get("is_current")), None)
    if current:
        return current
    finished = [e for e in events if e.get("finished")]
    if finished:
        return finished[-1]
    nxt = next((e for e in events if e.get("is_next")), None)
    if nxt:
        return nxt
    raise RuntimeError("Could not determine current FPL event")


def get_all_standings():
    page = 1
    rows = []
    league = None
    while True:
        data = fetch_json(
            f"{BASE}/leagues-classic/{LEAGUE_ID}/standings/?page_standings={page}&phase=1"
        )
        league = league or data.get("league", {})
        standings = data.get("standings", {})
        rows.extend(standings.get("results", []))
        if not standings.get("has_next"):
            break
        page += 1
        if page > 100:
            raise RuntimeError("Unexpected standings pagination")
    return league or {}, rows


def safe_fetch(url):
    try:
        return fetch_json(url), None
    except Exception as exc:
        return None, str(exc)


def normalize_live(live_data):
    out = {}
    for row in live_data.get("elements", []):
        stats = row.get("stats", {})
        out[str(row.get("id"))] = {
            "total_points": stats.get("total_points"),
            "minutes": stats.get("minutes"),
            "goals_scored": stats.get("goals_scored"),
            "assists": stats.get("assists"),
            "clean_sheets": stats.get("clean_sheets"),
            "goals_conceded": stats.get("goals_conceded"),
            "saves": stats.get("saves"),
            "bonus": stats.get("bonus"),
            "bps": stats.get("bps"),
            "yellow_cards": stats.get("yellow_cards"),
            "red_cards": stats.get("red_cards"),
            "defensive_contribution": stats.get("defensive_contribution"),
        }
    return out


def main():
    bootstrap = fetch_json(f"{BASE}/bootstrap-static/")
    event = current_event(bootstrap)
    gw = int(event["id"])

    element_map = {
        int(p["id"]): {
            "id": int(p["id"]),
            "web_name": p.get("web_name"),
            "first_name": p.get("first_name"),
            "second_name": p.get("second_name"),
            "team": p.get("team"),
            "element_type": p.get("element_type"),
            "now_cost": p.get("now_cost"),
            "selected_by_percent": p.get("selected_by_percent"),
            "status": p.get("status"),
        }
        for p in bootstrap.get("elements", [])
    }
    team_map = {
        int(t["id"]): {"name": t.get("name"), "short_name": t.get("short_name")}
        for t in bootstrap.get("teams", [])
    }

    league, standings = get_all_standings()
    live_raw, live_error = safe_fetch(f"{BASE}/event/{gw}/live/")
    live = normalize_live(live_raw or {})

    managers = []
    selection_count = Counter()
    captain_count = Counter()
    vice_count = Counter()
    errors = []

    for row in standings:
        entry_id = int(row["entry"])
        picks_data, picks_error = safe_fetch(f"{BASE}/entry/{entry_id}/event/{gw}/picks/")
        transfers_data, transfers_error = safe_fetch(f"{BASE}/entry/{entry_id}/transfers/")

        manager = {
            "entry_id": entry_id,
            "team_name": row.get("entry_name"),
            "manager_name": row.get("player_name"),
            "league_rank": row.get("rank"),
            "league_last_rank": row.get("last_rank"),
            "league_total": row.get("total"),
            "event_points_from_standings": row.get("event_total"),
            "is_me": entry_id == MY_ENTRY_ID,
            "picks_status": "ok" if picks_data else "error",
            "picks_error": picks_error,
            "active_chip": None,
            "entry_history": None,
            "automatic_subs": [],
            "picks": [],
            "current_gw_transfers": [],
        }

        if picks_data:
            manager["active_chip"] = picks_data.get("active_chip")
            manager["entry_history"] = picks_data.get("entry_history")
            manager["automatic_subs"] = picks_data.get("automatic_subs", [])
            for pick in picks_data.get("picks", []):
                pid = int(pick["element"])
                pdata = element_map.get(pid, {"id": pid})
                live_stats = live.get(str(pid), {})
                normalized = {
                    "element": pid,
                    "web_name": pdata.get("web_name"),
                    "team": pdata.get("team"),
                    "team_short": team_map.get(pdata.get("team"), {}).get("short_name"),
                    "position": pick.get("position"),
                    "multiplier": pick.get("multiplier"),
                    "is_captain": pick.get("is_captain"),
                    "is_vice_captain": pick.get("is_vice_captain"),
                    "live_points": live_stats.get("total_points"),
                    "minutes": live_stats.get("minutes"),
                    "bonus": live_stats.get("bonus"),
                    "bps": live_stats.get("bps"),
                }
                manager["picks"].append(normalized)
                selection_count[pid] += 1
                if pick.get("is_captain"):
                    captain_count[pid] += 1
                if pick.get("is_vice_captain"):
                    vice_count[pid] += 1
        else:
            errors.append({"entry_id": entry_id, "kind": "picks", "error": picks_error})

        if transfers_data is not None:
            manager["current_gw_transfers"] = [
                tr for tr in transfers_data if int(tr.get("event", -1)) == gw
            ]
        elif transfers_error:
            errors.append({"entry_id": entry_id, "kind": "transfers", "error": transfers_error})

        managers.append(manager)

    valid_managers = sum(1 for m in managers if m["picks_status"] == "ok")
    denom = valid_managers or 1
    popularity = []
    for pid, count in selection_count.most_common():
        pdata = element_map.get(pid, {"id": pid})
        cap = captain_count.get(pid, 0)
        eo = 100.0 * (count + cap) / denom
        popularity.append(
            {
                "element": pid,
                "web_name": pdata.get("web_name"),
                "team_short": team_map.get(pdata.get("team"), {}).get("short_name"),
                "selected": count,
                "selected_pct": round(100.0 * count / denom, 1),
                "captained": cap,
                "captained_pct": round(100.0 * cap / denom, 1),
                "vice_captained": vice_count.get(pid, 0),
                "approx_internal_eo_pct": round(eo, 1),
                "live_points": live.get(str(pid), {}).get("total_points"),
            }
        )

    output = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Official Fantasy Premier League public API via GitHub Actions",
        "league": {
            "id": LEAGUE_ID,
            "name": league.get("name"),
            "created": league.get("created"),
            "closed": league.get("closed"),
            "ranked_count": league.get("ranked_count"),
            "entries_loaded": len(standings),
        },
        "gameweek": {
            "id": gw,
            "name": event.get("name"),
            "deadline_time": event.get("deadline_time"),
            "finished": event.get("finished"),
            "data_checked": event.get("data_checked"),
            "is_current": event.get("is_current"),
            "is_next": event.get("is_next"),
        },
        "my_entry_id": MY_ENTRY_ID,
        "health": {
            "standings_ok": bool(standings),
            "live_ok": live_raw is not None,
            "live_error": live_error,
            "managers_total": len(managers),
            "managers_with_picks": valid_managers,
            "all_picks_ok": valid_managers == len(managers),
            "error_count": len(errors),
        },
        "league_popularity": popularity,
        "managers": managers,
        "errors": errors,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")

    print(
        f"Wrote {OUT_PATH}: GW{gw}, {len(managers)} managers, "
        f"{valid_managers} picks OK, {len(errors)} non-fatal errors"
    )


if __name__ == "__main__":
    main()
