import json
from collections import defaultdict
from app.database import get_connection

EVENTS_FILE = "data/events.jsonl"
MAPS_FILE = "data/maps.jsonl"

VALID_OS = {"iOS", "Android"}
VALID_STATES = {"started", "in_progress", "ended"}
VALID_OUTCOMES = {0.0, 0.5, 1.0}
SESSION_TIMEOUT = 120 


def load_jsonl(filepath):
    records = []
    with open(filepath, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"  [SKIP] incorrect json: {line_num}")
    return records


def has_base_fields(event):
    for field in ["id", "timestamp", "event_type", "user_id", "event_data"]:
        if field not in event:
            return False
    if not isinstance(event["id"], int):
        return False
    if not isinstance(event["timestamp"], int) or event["timestamp"] <= 0:
        return False
    if not isinstance(event["user_id"], str) or not event["user_id"].strip():
        return False
    if not isinstance(event["event_data"], dict):
        return False
    return True


def is_valid_registration(event):
    data = event["event_data"]
    country = data.get("country")
    device_os = data.get("device_os")
    username = data.get("username")
    if not country or not isinstance(country, str):
        return False
    if device_os not in VALID_OS:
        return False
    if not username or not isinstance(username, str) or not username.strip():
        return False
    return True


def is_valid_session_ping(event):
    data = event["event_data"]
    if data.get("state") not in VALID_STATES:
        return False
    if data.get("device_os") not in VALID_OS:
        return False
    return True


def is_valid_match_start(event):
    data = event["event_data"]
    map_id = data.get("map_id")
    opponent_id = data.get("opponent_id")
    if not map_id or not isinstance(map_id, str):
        return False
    if not opponent_id or not isinstance(opponent_id, str):
        return False
    if opponent_id == event["user_id"]: 
        return False
    return True


def is_valid_match_finish(event):
    data = event["event_data"]
    map_id = data.get("map_id")
    opponent_id = data.get("opponent_id")
    outcome = data.get("outcome")
    if not map_id or not isinstance(map_id, str):
        return False
    if not opponent_id or not isinstance(opponent_id, str):
        return False
    if opponent_id == event["user_id"]:
        return False
    if outcome not in VALID_OUTCOMES:
        return False
    return True


VALIDATORS = {
    "registration": is_valid_registration,
    "session_ping": is_valid_session_ping,
    "match_start": is_valid_match_start,
    "match_finish": is_valid_match_finish,
}


def validate_event(event):
    if not has_base_fields(event):
        return False
    validator = VALIDATORS.get(event.get("event_type"))
    if validator is None:
        return False
    return validator(event)


def remove_duplicates(events):
    seen = {}
    for event in events:
        eid = event["id"]
        if eid not in seen or event["timestamp"] < seen[eid]["timestamp"]:
            seen[eid] = event
    return list(seen.values())


def process_maps(conn, maps_data):
    cursor = conn.cursor()
    count = 0
    for m in maps_data:
        map_id = m.get("map_id") or m.get("id")
        map_name = m.get("map_name") or m.get("name")
        if not map_id or not map_name:
            continue
        cursor.execute(
            "INSERT OR IGNORE INTO maps (map_id, map_name) VALUES (?, ?)",
            (map_id, map_name)
        )
        count += 1
    conn.commit()
    print(f"  Maps: {count}")
    return {(m.get("map_id") or m.get("id")) for m in maps_data if (m.get("map_id") or m.get("id"))}


def process_users(conn, registration_events):
    users = {}
    for event in registration_events:
        uid = event["user_id"]
        if uid not in users or event["timestamp"] < users[uid]["timestamp"]:
            users[uid] = event

    cursor = conn.cursor()
    for uid, event in users.items():
        d = event["event_data"]
        cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, username, country, device_os, registered_at) VALUES (?, ?, ?, ?, ?)",
            (uid, d["username"], d["country"], d["device_os"], event["timestamp"])
        )
    conn.commit()
    print(f"  Users: {len(users)}")
    return set(users.keys())


def process_sessions(conn, session_events, valid_user_ids):
    pings = [e for e in session_events if e["user_id"] in valid_user_ids]

    user_pings = defaultdict(list)
    for ping in pings:
        user_pings[ping["user_id"]].append(ping)

    cursor = conn.cursor()
    session_count = 0

    for user_id, user_ping_list in user_pings.items():
        user_ping_list.sort(key=lambda x: x["timestamp"])

        session_start = user_ping_list[0]
        session_end = user_ping_list[0]

        for ping in user_ping_list[1:]:
            if ping["timestamp"] - session_end["timestamp"] <= SESSION_TIMEOUT:
                session_end = ping
            else:
                cursor.execute(
                    "INSERT INTO sessions (user_id, device_os, started_at, ended_at) VALUES (?, ?, ?, ?)",
                    (user_id, session_start["event_data"]["device_os"],
                     session_start["timestamp"], session_end["timestamp"])
                )
                session_count += 1
                session_start = ping
                session_end = ping

        cursor.execute(
            "INSERT INTO sessions (user_id, device_os, started_at, ended_at) VALUES (?, ?, ?, ?)",
            (user_id, session_start["event_data"]["device_os"],
             session_start["timestamp"], session_end["timestamp"])
        )
        session_count += 1

    conn.commit()
    print(f"  Sessions: {session_count}")


def process_matches(conn, starts, finishes, valid_user_ids, valid_map_ids):
    def is_valid_match_event(e):
        return (
            e["user_id"] in valid_user_ids
            and e["event_data"]["opponent_id"] in valid_user_ids
            and e["event_data"]["map_id"] in valid_map_ids
        )

    starts = [e for e in starts if is_valid_match_event(e)]
    finishes = [e for e in finishes if is_valid_match_event(e)]

    def match_key(event):
        uid = event["user_id"]
        oid = event["event_data"]["opponent_id"]
        mid = event["event_data"]["map_id"]
        return (tuple(sorted([uid, oid])), mid)

    starts_by_key = defaultdict(list)
    for e in starts:
        starts_by_key[match_key(e)].append(e)

    finishes_by_key = defaultdict(list)
    for e in finishes:
        finishes_by_key[match_key(e)].append(e)

    all_keys = set(starts_by_key.keys()) | set(finishes_by_key.keys())

    cursor = conn.cursor()
    match_count = 0

    for key in all_keys:
        if key not in starts_by_key or key not in finishes_by_key:
            continue

        player_pair, map_id = key
        p1, p2 = player_pair

        p1_starts = sorted([e for e in starts_by_key[key] if e["user_id"] == p1], key=lambda x: x["timestamp"])
        p2_starts = sorted([e for e in starts_by_key[key] if e["user_id"] == p2], key=lambda x: x["timestamp"])
        p1_finishes = sorted([e for e in finishes_by_key[key] if e["user_id"] == p1], key=lambda x: x["timestamp"])
        p2_finishes = sorted([e for e in finishes_by_key[key] if e["user_id"] == p2], key=lambda x: x["timestamp"])

        num_matches = max(len(p1_finishes), len(p2_finishes))
        if num_matches == 0:
            continue

        for i in range(num_matches):
            start_event = (p1_starts[i] if i < len(p1_starts) else
                           p2_starts[i] if i < len(p2_starts) else None)

            p1_finish = p1_finishes[i] if i < len(p1_finishes) else None
            p2_finish = p2_finishes[i] if i < len(p2_finishes) else None
            finish_event = p1_finish or p2_finish

            if not finish_event:
                continue

            started_at = start_event["timestamp"] if start_event else finish_event["timestamp"]
            ended_at = finish_event["timestamp"]

            if ended_at < started_at:
                started_at = ended_at

            if p1_finish:
                p1_outcome = p1_finish["event_data"]["outcome"]
            else:
                p2_outcome = p2_finish["event_data"]["outcome"]
                p1_outcome = 1.0 - p2_outcome if p2_outcome != 0.5 else 0.5

            cursor.execute(
                "INSERT INTO matches (map_id, player1_id, player2_id, player1_outcome, started_at, ended_at) VALUES (?, ?, ?, ?, ?, ?)",
                (map_id, p1, p2, p1_outcome, started_at, ended_at)
            )
            match_count += 1

    conn.commit()
    print(f"  Matches: {match_count}")


def run_ingestion():
    conn = get_connection()

    maps_raw = load_jsonl(MAPS_FILE)
    valid_map_ids = process_maps(conn, maps_raw)

    events_raw = load_jsonl(EVENTS_FILE)
    print(f"  Raw data events: {len(events_raw)}")

    events_raw = remove_duplicates(events_raw)
    print(f" After deleting duplicates: {len(events_raw)}")

    events_valid = [e for e in events_raw if validate_event(e)]
    print(f"  After validation: {len(events_valid)}")

    by_type = defaultdict(list)
    for e in events_valid:
        by_type[e["event_type"]].append(e)

    valid_user_ids = process_users(conn, by_type["registration"])
    process_sessions(conn, by_type["session_ping"], valid_user_ids)
    process_matches(conn, by_type["match_start"], by_type["match_finish"], valid_user_ids, valid_map_ids)

    conn.close()
    print("*** Ingestion done ***")
