from flask import Flask
from app.database import init_db, get_connection, get_db, close_db
from app.ingest import run_ingestion

app = Flask(__name__)
app.teardown_appcontext(close_db)


def is_db_empty():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM matches")
    count = cursor.fetchone()[0]
    conn.close()
    return count == 0


from app.routes.user_stats import user_stats_bp
from app.routes.map_stats import map_stats_bp
from app.charts import chart_bp

app.register_blueprint(user_stats_bp)
app.register_blueprint(map_stats_bp)
app.register_blueprint(chart_bp)


@app.route("/test")
def test():
    return "test route works"


@app.route("/maps")
def maps():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM maps")
    rows = cursor.fetchall()
    return {"maps": [{"map_id": r["map_id"], "map_name": r["map_name"]} for r in rows]}


if __name__ == "__main__":
    init_db()

    if is_db_empty():
        print("Empty database -> ingestion in progrress...")
        run_ingestion()
    else:
        print("Database already exists. No need for ingestion.")

    app.run(debug=True)
