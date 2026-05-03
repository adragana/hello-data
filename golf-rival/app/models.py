CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    user_id     TEXT PRIMARY KEY,
    username    TEXT NOT NULL,
    country     TEXT NOT NULL,
    device_os   TEXT NOT NULL,
    registered_at INTEGER NOT NULL
);
"""

CREATE_MAPS_TABLE = """
CREATE TABLE IF NOT EXISTS maps (
    map_id      TEXT PRIMARY KEY,
    map_name    TEXT NOT NULL
);
"""

CREATE_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       TEXT NOT NULL,
    device_os     TEXT NOT NULL,
    started_at    INTEGER NOT NULL,
    ended_at      INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
"""

CREATE_MATCHES_TABLE = """
CREATE TABLE IF NOT EXISTS matches (
    match_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    map_id        TEXT NOT NULL,
    player1_id    TEXT NOT NULL,
    player2_id    TEXT NOT NULL,
    player1_outcome FLOAT NOT NULL,
    started_at    INTEGER NOT NULL,
    ended_at      INTEGER NOT NULL,
    FOREIGN KEY (map_id)     REFERENCES maps(map_id),
    FOREIGN KEY (player1_id) REFERENCES users(user_id),
    FOREIGN KEY (player2_id) REFERENCES users(user_id)
);
"""

ALL_TABLES = [
    CREATE_USERS_TABLE,
    CREATE_MAPS_TABLE,
    CREATE_SESSIONS_TABLE,
    CREATE_MATCHES_TABLE,
]
