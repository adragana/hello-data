from flask import Blueprint, jsonify, request
from app.database import get_db
from datetime import datetime, timezone

user_stats_bp = Blueprint("user_stats", __name__)


@user_stats_bp.route("/user-stats", methods=["GET"])
def user_stats():
    countries = request.args.getlist("countries")
    oses = request.args.getlist("os")

    db = get_db()
    cursor = db.cursor()

    main_query = """
        SELECT
            u.user_id,
            u.username,
            u.country,
            u.registered_at,
            COALESCE(SUM(s.ended_at - s.started_at), 0) AS total_playtime,
            COALESCE(
                CAST(SUM(CASE WHEN m.player1_id = u.user_id THEN m.player1_outcome
                              ELSE 1.0 - m.player1_outcome END) AS FLOAT)
                / NULLIF(COUNT(DISTINCT m.match_id), 0)
            , 0) AS total_win_ratio,
            COALESCE(
                CAST(COUNT(DISTINCT m.match_id) AS FLOAT)
                / NULLIF(COUNT(DISTINCT s.session_id), 0)
            , 0) AS avg_matches_per_session
        FROM users u
        LEFT JOIN sessions s ON s.user_id = u.user_id
            {os_join}
        LEFT JOIN matches m ON (m.player1_id = u.user_id OR m.player2_id = u.user_id)
            {os_match_join}
        {where_clause}
        GROUP BY u.user_id
        ORDER BY total_playtime DESC
    """

    os_join = ""
    os_match_join = ""
    where_parts = []
    main_params = []

    if oses:
        os_placeholders = ",".join("?" * len(oses))
        os_join = f"AND s.device_os IN ({os_placeholders})"
        main_params += oses

        os_match_join = f"""
            AND EXISTS (
                SELECT 1 FROM sessions s2
                WHERE s2.user_id = u.user_id
                AND s2.device_os IN ({os_placeholders})
                AND m.ended_at BETWEEN s2.started_at AND s2.ended_at + 120
            )
        """
        main_params += oses

    if countries:
        country_placeholders = ",".join("?" * len(countries))
        where_parts.append(f"u.country IN ({country_placeholders})")
        main_params += countries

    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    main_query = main_query.format(
        os_join=os_join,
        os_match_join=os_match_join,
        where_clause=where_clause,
    )

    cursor.execute(main_query, main_params)
    rows = cursor.fetchall()

    if not rows:
        return jsonify([])

    user_ids = [row["user_id"] for row in rows]

    fav_map_lookup = get_fav_maps_bulk(cursor, user_ids, oses)

    results = []
    for row in rows:
        uid = row["user_id"]
        fav_map, fav_map_win_ratio = fav_map_lookup.get(uid, (None, None))
        reg_date = datetime.fromtimestamp(row["registered_at"], tz=timezone.utc).strftime("%Y-%m-%d")

        results.append({
            "username": row["username"],
            "country": row["country"],
            "fav_map": fav_map,
            "fav_map_win_ratio": round(fav_map_win_ratio, 4) if fav_map_win_ratio is not None else None,
            "total_playtime": row["total_playtime"],
            "total_win_ratio": round(row["total_win_ratio"], 4),
            "avg_matches_per_session": round(row["avg_matches_per_session"], 4),
            "registration_date": reg_date,
        })

    return jsonify(results)


def get_fav_maps_bulk(cursor, user_ids, oses=None):
    """
    Vraća {user_id: (map_name, win_ratio)} za sve user_ids u jednom upitu.
    Tie-breaker: više odigranih mečeva → veći prioritet.
    """
    if not user_ids:
        return {}

    uid_placeholders = ",".join("?" * len(user_ids))
    params = list(user_ids)

    os_filter = ""
    if oses:
        os_placeholders = ",".join("?" * len(oses))
        os_filter = f"""
            AND EXISTS (
                SELECT 1 FROM sessions s
                WHERE s.user_id = u.user_id
                AND s.device_os IN ({os_placeholders})
                AND m.ended_at BETWEEN s.started_at AND s.ended_at + 120
            )
        """
        params += oses

    query = f"""
        WITH map_wins AS (
            SELECT
                u.user_id,
                mp.map_name,
                CAST(SUM(CASE WHEN m.player1_id = u.user_id THEN m.player1_outcome
                              ELSE 1.0 - m.player1_outcome END) AS FLOAT)
                    / COUNT(m.match_id) AS win_ratio,
                COUNT(m.match_id) AS match_count
            FROM users u
            JOIN matches m ON (m.player1_id = u.user_id OR m.player2_id = u.user_id)
            JOIN maps mp ON mp.map_id = m.map_id
            WHERE u.user_id IN ({uid_placeholders})
            {os_filter}
            GROUP BY u.user_id, mp.map_id
        ),
        ranked AS (
            SELECT
                user_id,
                map_name,
                win_ratio,
                ROW_NUMBER() OVER (
                    PARTITION BY user_id
                    ORDER BY win_ratio DESC, match_count DESC
                ) AS rn
            FROM map_wins
        )
        SELECT user_id, map_name, win_ratio
        FROM ranked
        WHERE rn = 1
    """

    cursor.execute(query, params)
    return {row["user_id"]: (row["map_name"], row["win_ratio"]) for row in cursor.fetchall()}
