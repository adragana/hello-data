# Data Engineering

## Overview

This project processes raw game events and map metadata, cleans the data, stores it in a **SQLite** database, and exposes a **REST API** for user and map statistics.
Interactive line chart (Plotly) visualises match counts over the last 7 days per map.


## Approach

### 1. Data cleaning

- **Duplicate removal:** events are deduplicated by `id`, keeping the earliest timestamp.
- **Base field validation:** every event must have `id`, `timestamp`, `event_type`, `user_id`, `event_data`.
- **Type-specific validation:**
  - `registration`: valid country code, device OS (`iOS`/`Android`), non-empty username.
  - `session_ping`: valid `state` and `device_os`.
  - `match_start` & `match_finish`: valid `map_id`, `opponent_id` different from `user_id`, valid outcome (`0`, `0.5`, `1`).
- **Common-sense checks:**
  - Reject events where `opponent_id == user_id`.
  - Drop events with non-positive timestamps.
  - Ignore malformed JSON lines.

### 2. Data model (SQLite)

Four tables are created on startup (`models.py`):

| Table      | Purpose                                                   |
|------------|-----------------------------------------------------------|
| `users`    | Registration info (one row per valid user)                |
| `maps`     | Golf courses loaded from `maps.jsonl`                     |
| `sessions` | Continuous play periods built from `session_ping` events  |
| `matches`  | Fully paired matches with outcomes                        |

All foreign keys are enforced via `PRAGMA foreign_keys = ON`.

### 3. Session detection without `state`

- `session_ping` events are grouped by `user_id` and sorted by timestamp.
- A session boundary is inserted whenever the time gap between two consecutive pings exceeds **120 seconds**.
- The `state` column is only used for validation; actual session boundaries are entirely derived from the timeout logic.

### 4. Match pairing

- Events are grouped per **`(sorted(player1, player2), map_id)`** pair.
- A match is considered valid if **at least one start and one finish** exist for the pair (as per the specification).
- For each pair, finish events are aligned with available start events to extract timestamps and outcomes.
- Missing outcomes are inferred from the opponent's result.

### 5. API & filtering

- **`/user-stats`**: supports optional `countries` and `os` query parameters (lists).
  The OS filter restricts statistics (playtime, win ratio, matches, favourite map) to only sessions played on the given OS, using subqueries that tie matches to those sessions.
- **`/map-stats/<map_name>`**: accepts optional `date_from` and `date_to`.
  Computes daily average playtime, cumulative best player (highest win ratio up to that day, ties broken by most matches), and match count.

### 6. Chart

A Plotly line chart is served at `/chart`.
It displays the last 7 days of match counts per map, with each map as a separate trace.
Summary cards show total matches per map for that period.

---

## Project structure

```
golf-rival/
├── app/
│   ├── routes/
│   │   ├── user_stats.py     # GET /user-stats
│   │   └── map_stats.py      # GET /map-stats/<map_name>
│   ├── charts.py             # GET /chart ( visualization)
│   ├── database.py           # SQLite connection management
│   ├── ingest.py             # Data cleaning and ingestion pipeline
│   └── models.py             # Table definitions
├── data/
│   ├── events.jsonl
│   └── maps.jsonl
├── static/
│   ├── css/
│   │   └── chart.css
│   └── images/
├── templates/
│   └── chart.html.j2
├── main.py
├── wsgi.py
└── README.md
```

---

## Installation & Setup

### Requirements

- Python 3.9+
- SQLite ≥ 3.38 (required for the `unixepoch` modifier - included with Python 3.9+ on most systems)
- `pip` for package management

### Steps

1. **Clone the repository** and navigate into the project folder:

   ```bash
   git clone <repo-url>
   cd <repo-folder>
   ```

2. **Create and activate a virtual environment:**

   ```bash
   python -m venv venv
   source venv/bin/activate      # Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**

   ```bash
   pip install flask
   ```

4. **Place the data files** in the `data/` folder:

   ```
   data/
   ├── events.jsonl
   └── maps.jsonl
   ```

5. **Run the application:**

   ```bash
   python main.py
   ```

On first run, the app automatically initialises the database and runs the ingestion pipeline.


On subsequent runs, the existing database is reused and ingestion is skipped.

---

## API Reference

### `GET /user-stats`

Returns a list of players with their cumulative statistics, ordered by `total_playtime` descending.

**Query parameters (all optional):**

| Parameter   | Type | Description                                      | Example                        |
|-------------|------|--------------------------------------------------|--------------------------------|
| `countries` | list | Filter by country code(s)                        | `?countries=SRB&countries=MNE` |
| `os`        | list | Filter stats to sessions played on a specific OS | `?os=iOS`                      |

> The `os` filter applies only to statistics earned during sessions on that OS; the registration device is not considered.

**Example request:**
```
GET /user-stats?countries=SRB&os=iOS
```

**Example response:**
```json
[
  {
    "username": "Nikola",
    "country": "SRB",
    "fav_map": "Lake",
    "fav_map_win_ratio": 0.6,
    "total_playtime": 153226,
    "total_win_ratio": 0.5,
    "avg_matches_per_session": 0.19,
    "registration_date": "2022-04-03"
  }
]
```

| Field                     | Description                                                             |
|---------------------------|-------------------------------------------------------------------------|
| `fav_map`                 | Map with the highest win ratio; tie-broken by number of matches played  |
| `fav_map_win_ratio`       | Win ratio on the favourite map                                          |
| `total_playtime`          | Total seconds spent in sessions                                         |
| `total_win_ratio`         | Overall win ratio across all matches                                    |
| `avg_matches_per_session` | Average number of matches played per session                            |
| `registration_date`       | Account creation date (`YYYY-MM-DD`)                                    |

---

### `GET /map-stats/<map_name>`

Returns daily statistics for a specific map, ordered by date descending.

**Path parameter:** name of the map (`Lake`, `Inferno`...)

**Query parameters (all optional):**

| Parameter   | Format       | Description                     |
|-------------|--------------|---------------------------------|
| `date_from` | `YYYY-MM-DD` | Start of date range (inclusive) |
| `date_to`   | `YYYY-MM-DD` | End of date range (inclusive)   |

If a boundary is omitted, that side is treated as unbounded.

**Example request:**
```
GET /map-stats/Lake?date_from=2026-04-01&date_to=2026-04-03
```

**Example response:**
```json
[
  {
    "date": "2026-04-03",
    "avg_playtime": 130.0,
    "best_player_username": "Nikola",
    "match_cnt": 221
  },
  {
    "date": "2026-04-02",
    "avg_playtime": 180.0,
    "best_player_username": "Nikola",
    "match_cnt": 225
  }
]
```

| Field                  | Description                                                                            |
|------------------------|----------------------------------------------------------------------------------------|
| `date`                 | Date the matches ended on                                                              |
| `avg_playtime`         | Average match duration in seconds for that day                                         |
| `best_player_username` | Player with the highest cumulative win ratio on this map up to and including this date |
| `match_cnt`            | Number of matches that ended on this date                                              |

---

### `GET /chart`

Renders an interactive Plotly line chart showing match count per map over the last 7 days.

Open in browser: `http://127.0.0.1:5000/chart`

---

## Available endpoints

```
http://127.0.0.1:5000/maps
http://127.0.0.1:5000/user-stats
http://127.0.0.1:5000/user-stats?countries=SRB
http://127.0.0.1:5000/user-stats?countries=SRB&countries=MNE
http://127.0.0.1:5000/user-stats?os=iOS
http://127.0.0.1:5000/user-stats?os=Android
http://127.0.0.1:5000/user-stats?countries=SRB&os=iOS
http://127.0.0.1:5000/map-stats/Lake
http://127.0.0.1:5000/map-stats/Lake?date_from=2024-01-01
http://127.0.0.1:5000/map-stats/Lake?date_to=2024-12-31
http://127.0.0.1:5000/map-stats/Lake?date_from=2024-01-01&date_to=2024-12-31
http://127.0.0.1:5000/chart
```

> Use `/maps` first to see which map names are available in the database.
