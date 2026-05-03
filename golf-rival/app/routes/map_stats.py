from flask import Blueprint, jsonify, request
from app.database import get_db
from collections import defaultdict
from datetime import datetime, timezone

map_stats_bp = Blueprint("map_stats", __name__)


@map_stats_bp.route("/map-stats/<map_name>", methods=["GET"])
def map_stats(map_name):
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    def to_timestamp(date_str, end_of_day=False):
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            return int(dt.replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            return None

    ts_from = to_timestamp(date_from) if date_from else None
    ts_to = to_timestamp(date_to, end_of_day=True) if date_to else None

    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT map_id FROM maps WHERE map_name = ?", (map_name,))
    map_row = cursor.fetchone()
    if not map_row:
        return jsonify({"error": f"Mapa '{map_name}' nije pronađena."}), 404

    map_id = map_row["map_id"]


    date_filter = "WHERE m.map_id = ?"
    params = [map_id]

    if ts_from:
        date_filter += " AND m.ended_at >= ?"
        params.append(ts_from)
    if ts_to:
        date_filter += " AND m.ended_at <= ?"
        params.append(ts_to)

    cursor.execute(f"""
        SELECT
            DATE(m.ended_at, 'unixepoch') AS date,
            AVG(m.ended_at - m.started_at)  AS avg_playtime,
            COUNT(m.match_id)               AS match_cnt
        FROM matches m
        {date_filter}
        GROUP BY date
        ORDER BY date DESC
    """, params)
    daily_rows = cursor.fetchall()

    if not daily_rows:
        return jsonify([])

    all_dates = sorted({row["date"] for row in daily_rows})
    

    cum_params = [map_id]
    cum_filter = "WHERE m.map_id = ?"
    if ts_to:
        cum_filter += " AND m.ended_at <= ?"
        cum_params.append(ts_to)

    cursor.execute(f"""
        SELECT
            u.user_id,
            u.username,
            DATE(m.ended_at, 'unixepoch') AS match_date,
            CASE WHEN m.player1_id = u.user_id THEN m.player1_outcome
                 ELSE 1.0 - m.player1_outcome END AS outcome
        FROM matches m
        JOIN users u ON (u.user_id = m.player1_id OR u.user_id = m.player2_id)
        {cum_filter}
        ORDER BY match_date ASC
    """, cum_params)
    all_matches = cursor.fetchall()

    player_stats = defaultdict(lambda: [0, 0])    
    player_names = {}

    match_idx = 0
    total_matches = len(all_matches)
    best_player_by_date = {}

    for date_str in all_dates:
        while match_idx < total_matches and all_matches[match_idx]["match_date"] <= date_str:
            row = all_matches[match_idx]
            uid = row["user_id"]

            player_stats[uid][1] += 1
            if row["outcome"] == 1.0:
                player_stats[uid][0] += 1

            player_names[uid] = row["username"]
            match_idx += 1

        best_uid = None
        best_ratio = -1.0
        best_total = -1
        for uid, (wins, total) in player_stats.items():
            if total == 0:
                continue
            ratio = wins / total
            if ratio > best_ratio or (ratio == best_ratio and total > best_total):
                best_ratio = ratio
                best_total = total
                best_uid = uid

        best_player_by_date[date_str] = player_names.get(best_uid) if best_uid else None

    results = []
    for row in daily_rows:
        date_str = row["date"]
        results.append({
            "date": date_str,
            "avg_playtime": round(row["avg_playtime"], 2) if row["avg_playtime"] else 0,
            "best_player_username": best_player_by_date.get(date_str),
            "match_cnt": row["match_cnt"],
        })

    return jsonify(results)
