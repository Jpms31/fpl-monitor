# fpl-monitor

Automated data bridge for Fantasy Premier League mini-league **369689 (Haal of Fame)**.

The repository runs an hourly GitHub Action that collects public data from the official FPL API and writes a stable snapshot to:

`data/latest.json`

Tracked data includes:

- Current Gameweek and deadline
- Mini-league standings and Entry IDs
- Picks, captain, vice-captain and chips for every manager after deadline
- Current Gameweek transfers when publicly available
- Live player points / BPS data
- Internal mini-league selection and captain popularity
- SANTEAM identified by Entry ID `1766059`

The workflow can also be triggered manually from the **Actions** tab.

Public raw snapshot:

`https://raw.githubusercontent.com/Jpms31/fpl-monitor/main/data/latest.json`

This project uses public Fantasy Premier League endpoints and does not require FPL login credentials.
