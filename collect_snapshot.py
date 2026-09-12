# Deadline-aware, atomic entrypoint for FPL mini-league snapshots.
#
# The upstream bootstrap flags can lag around a Gameweek deadline. This wrapper
# selects the latest GW whose deadline has passed, collects into a staging file,
# validates the health checks, and only then replaces data/latest.json.
import json
import os
from datetime import datetime, timezone

import collector

FINAL_PATH = os.path.join("data", "latest.json")
PENDING_PATH = os.path.join("data", "latest.pending.json")


def parse_deadline(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def deadline_aware_event(bootstrap):
    events = bootstrap.get("events", [])
    now = datetime.now(timezone.utc)

    passed = []
    for event in events:
        deadline = parse_deadline(event.get("deadline_time"))
        if deadline is not None and deadline <= now:
            passed.append(event)

    if passed:
        return max(passed, key=lambda event: int(event["id"]))

    current = next((event for event in events if event.get("is_current")), None)
    if current:
        return current

    nxt = next((event for event in events if event.get("is_next")), None)
    if nxt:
        return nxt

    raise RuntimeError("Could not determine FPL event")


def validate_snapshot(path):
    with open(path, "r", encoding="utf-8") as fh:
        snapshot = json.load(fh)

    health = snapshot.get("health", {})
    total = int(health.get("managers_total") or 0)
    with_picks = int(health.get("managers_with_picks") or 0)

    if health.get("standings_ok") is not True:
        raise RuntimeError("Refusing to publish snapshot: standings are not healthy")
    if health.get("live_ok") is not True:
        raise RuntimeError("Refusing to publish snapshot: live endpoint is not healthy")
    if total <= 0 or with_picks != total:
        raise RuntimeError(
            f"Refusing to publish snapshot: picks incomplete ({with_picks}/{total})"
        )

    monthly = snapshot.get("private_competition", {}).get("monthly")
    if monthly is not None and health.get("monthly_standings_ok") is not True:
        raise RuntimeError("Refusing to publish snapshot: monthly standings are not healthy")

    return snapshot


def main():
    os.makedirs(os.path.dirname(FINAL_PATH), exist_ok=True)

    # Override only event selection; keep the established collector logic intact.
    collector.current_event = deadline_aware_event
    collector.OUT_PATH = PENDING_PATH

    try:
        collector.main()
        snapshot = validate_snapshot(PENDING_PATH)
        os.replace(PENDING_PATH, FINAL_PATH)
        print(
            "Published atomic snapshot: "
            f"GW{snapshot['gameweek']['id']} at {snapshot['generated_at_utc']}"
        )
    finally:
        if os.path.exists(PENDING_PATH):
            os.remove(PENDING_PATH)


if __name__ == "__main__":
    main()
