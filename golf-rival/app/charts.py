from flask import Blueprint, render_template
from app.database import get_db
from collections import defaultdict
from datetime import datetime, timedelta, timezone

chart_bp = Blueprint("chart", __name__)


def get_last_7_days(cursor):
    cursor.execute("SELECT DATE(MAX(ended_at), 'unixepoch') AS last_date FROM matches")
    row = cursor.fetchone()

    if row and row["last_date"]:
        last_date = datetime.strptime(row["last_date"], "%Y-%m-%d").date()
    else:
        last_date = datetime.now(timezone.utc).date()

    return [(last_date - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]


@chart_bp.route("/chart")
def chart():
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT map_id, map_name FROM maps")
    maps = cursor.fetchall()

    dates = get_last_7_days(cursor)

    cursor.execute("""
        SELECT
            map_id,
            DATE(ended_at, 'unixepoch') AS date,
            COUNT(*)                    AS match_cnt
        FROM matches
        WHERE DATE(ended_at, 'unixepoch') BETWEEN ? AND ?
        GROUP BY map_id, date
    """, (dates[0], dates[-1]))

    counts = defaultdict(dict)
    for row in cursor.fetchall():
        counts[row["map_id"]][row["date"]] = row["match_cnt"]

    colors = ["#5427C6", "#f59e0b", "#10b981", "#ef4444", "#8eb9ff"]
    traces = []
    stats = []

    for i, m in enumerate(maps):
        color = colors[i % len(colors)]
        map_counts = counts[m["map_id"]]
        data = [map_counts.get(d, 0) for d in dates]
        total = sum(data)

        traces.append({
            "x": dates,
            "y": data,
            "name": m["map_name"],
            "type": "scatter",
            "mode": "lines+markers",
            "line": {"color": color, "width": 3, "shape": "spline"},
            "marker": {"size": 8, "color": color},
            "hovertemplate": "<b>%{fullData.name}</b><br>Date: %{x}<br>Matches: %{y}<extra></extra>",
        })

        stats.append({
            "name": m["map_name"],
            "total": total,
            "color": color,
        })

    return render_template("chart.html.j2", traces=traces, stats=stats)
