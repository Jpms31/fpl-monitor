# Enrich the FPL snapshot with authoritative per-fixture completion state.
import json
import os
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://fantasy.premierleague.com/api"
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


def has_bonus_stats(fixture):
    return any(stat.get("identifier") == "bonus" for stat in fixture.get("stats", []))


def normalize_fixture(fixture, teams):
    team_h = fixture.get("team_h")
    team_a = fixture.get("team_a")
    started = bool(fixture.get("started"))
    finished = bool(fixture.get("finished"))

    if finished:
        status = "finished"
    elif started:
        status = "in_progress"
    else:
        status = "not_started"

    return {
        "id": fixture.get("id"),
        "event": fixture.get("event"),
        "kickoff_time": fixture.get("kickoff_time"),
        "team_h": team_h,
        "team_h_short": teams.get(team_h, {}).get("short_name"),
        "team_h_score": fixture.get("team_h_score"),
        "team_a": team_a,
        "team_a_short": teams.get(team_a, {}).get("short_name"),
        "team_a_score": fixture.get("team_a_score"),
        "started": started,
        "finished": finished,
        "minutes": fixture.get("minutes"),
        "status": status,
        # Hard guard: a visible score or 90 minutes is not enough to call a match complete.
        "score_final": finished,
        "bonus_stats_present": has_bonus_stats(fixture),
    }


def main():
    with open(OUT_PATH, "r", encoding="utf-8") as fh:
        snapshot = json.load(fh)

    gw = int(snapshot["gameweek"]["id"])
    fixtures_raw = fetch_json(f"{BASE}/fixtures/?event={gw}")
    if not isinstance(fixtures_raw, list) or not fixtures_raw:
        raise RuntimeError(
            f"No official fixtures returned for GW{gw}; refusing to publish unguarded snapshot"
        )

    bootstrap = fetch_json(f"{BASE}/bootstrap-static/")
    teams = {
        int(team["id"]): {"short_name": team.get("short_name"), "name": team.get("name")}
        for team in bootstrap.get("teams", [])
    }

    fixtures = [normalize_fixture(fixture, teams) for fixture in fixtures_raw]
    finished_count = sum(1 for fixture in fixtures if fixture["finished"])
    in_progress_count = sum(1 for fixture in fixtures if fixture["status"] == "in_progress")
    not_started_count = sum(1 for fixture in fixtures if fixture["status"] == "not_started")
    all_fixtures_finished = finished_count == len(fixtures)
    bonus_stats_complete = all_fixtures_finished and all(
        fixture["bonus_stats_present"] for fixture in fixtures
    )
    live_ok = snapshot.get("health", {}).get("live_ok") is True
    final_balance_ready = all_fixtures_finished and bonus_stats_complete and live_ok

    if final_balance_ready:
        final_balance_reason = "all_official_fixtures_finished_bonus_present_live_ok"
    elif not all_fixtures_finished:
        final_balance_reason = "one_or_more_official_fixtures_not_finished"
    elif not bonus_stats_complete:
        final_balance_reason = "official_bonus_stats_not_complete"
    else:
        final_balance_reason = "live_endpoint_not_healthy"

    snapshot["schema_version"] = max(int(snapshot.get("schema_version", 0)), 4)
    snapshot["fixture_status_generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    snapshot["fixtures"] = fixtures
    snapshot["gameweek"]["fixture_status"] = {
        "source": "Official Fantasy Premier League /fixtures endpoint",
        "completion_rule": "A match is final only when its official fixture has finished=true",
        "fixtures_total": len(fixtures),
        "fixtures_finished": finished_count,
        "fixtures_in_progress": in_progress_count,
        "fixtures_not_started": not_started_count,
        "all_fixtures_finished": all_fixtures_finished,
        "any_fixture_in_progress": in_progress_count > 0,
        "bonus_stats_complete": bonus_stats_complete,
        "final_balance_ready": final_balance_ready,
        "final_balance_reason": final_balance_reason,
    }

    snapshot.setdefault("health", {})["fixtures_ok"] = True
    snapshot["health"]["fixtures_error"] = None

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")

    print(
        f"Fixture guard: GW{gw}, {finished_count}/{len(fixtures)} finished, "
        f"{in_progress_count} in progress, final_balance_ready={final_balance_ready}"
    )


if __name__ == "__main__":
    main()
