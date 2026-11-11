"""
STORAGE — SQLite database file: shadow_self.db          (PSEUDOCODE.md section 3)

Tables: measurements, baselines, results, alerts, plans, daily_scores
Open shadow_self.db in any SQLite app (e.g. DB Browser for SQLite) to look inside.
"""
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "shadow_self.db")

TABLES = ["measurements", "baselines", "results", "alerts", "plans", "daily_scores"]

SCHEMA = """
CREATE TABLE measurements (
    id INTEGER PRIMARY KEY, astronaut TEXT, time TEXT, day INTEGER,
    domain TEXT, metric TEXT, value REAL, unit TEXT, source TEXT,
    quality TEXT, detail TEXT);
CREATE INDEX idx_meas ON measurements (astronaut, metric, day);

CREATE TABLE baselines (
    astronaut TEXT, metric TEXT, value REAL, PRIMARY KEY (astronaut, metric));

CREATE TABLE results (
    id INTEGER PRIMARY KEY, astronaut TEXT, day INTEGER, domain TEXT, metric TEXT,
    value REAL, baseline REAL, pct_change REAL, mdc REAL, real_change INTEGER,
    bad_direction INTEGER, predicted REAL, residual REAL, resid_sd REAL,
    unexpected INTEGER, flagged INTEGER, persistent INTEGER, status TEXT, reason TEXT);
CREATE INDEX idx_res ON results (astronaut, metric, day);

CREATE TABLE alerts (
    id INTEGER PRIMARY KEY, astronaut TEXT, day INTEGER, time TEXT, tier TEXT,
    domain TEXT, key TEXT, message TEXT, UNIQUE (astronaut, day, key));

CREATE TABLE daily_scores (
    astronaut TEXT, day INTEGER, domain TEXT, score REAL, status TEXT,
    PRIMARY KEY (astronaut, day, domain));

CREATE TABLE plans (
    id INTEGER PRIMARY KEY, astronaut TEXT, made_on_day INTEGER,
    scheduled_day INTEGER, action TEXT, note TEXT);
"""


class DB:
    def __init__(self, path=DB_PATH, fresh=False):
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        # keep the rollback journal in memory (no extra temp files in the folder)
        self.con.execute("PRAGMA journal_mode=MEMORY")
        if fresh:
            for t in TABLES:
                self.con.execute(f"DROP TABLE IF EXISTS {t}")
            self.con.executescript(SCHEMA)
            self.con.commit()

    # ---------- measurements ----------
    def save_readings(self, readings):
        self.con.executemany(
            "INSERT INTO measurements (astronaut,time,day,domain,metric,value,unit,source,quality,detail)"
            " VALUES (:astronaut,:time,:day,:domain,:metric,:value,:unit,:source,:quality,:detail)",
            readings)
        self.con.commit()

    def get_stream(self, astronaut, metric, day):
        return self.con.execute(
            "SELECT time,value,quality,detail FROM measurements"
            " WHERE astronaut=? AND metric=? AND day=? ORDER BY time",
            (astronaut, metric, day)).fetchall()

    def get_value(self, astronaut, metric, day):
        """Latest good value of a metric on one day (None if not measured)."""
        row = self.con.execute(
            "SELECT value FROM measurements WHERE astronaut=? AND metric=? AND day=?"
            " AND quality='good' ORDER BY time DESC LIMIT 1", (astronaut, metric, day)).fetchone()
        return row["value"] if row else None

    def get_history(self, astronaut, metric, from_day, to_day):
        return self.con.execute(
            "SELECT day,value FROM measurements WHERE astronaut=? AND metric=?"
            " AND day BETWEEN ? AND ? AND quality='good' ORDER BY time",
            (astronaut, metric, from_day, to_day)).fetchall()

    def get_latest(self, astronaut, metric, up_to_day):
        row = self.con.execute(
            "SELECT day,value FROM measurements WHERE astronaut=? AND metric=? AND day<=?"
            " AND quality='good' ORDER BY time DESC LIMIT 1", (astronaut, metric, up_to_day)).fetchone()
        return dict(row) if row else None

    # ---------- baselines ----------
    def set_baseline(self, astronaut, metric, value):
        self.con.execute("INSERT OR REPLACE INTO baselines VALUES (?,?,?)", (astronaut, metric, value))
        self.con.commit()

    def get_baseline(self, astronaut, metric):
        row = self.con.execute("SELECT value FROM baselines WHERE astronaut=? AND metric=?",
                               (astronaut, metric)).fetchone()
        return row["value"] if row else None

    def build_baselines_from_preflight(self):
        """Baseline = average of all good pre-mission readings (day <= 0)."""
        rows = self.con.execute(
            "SELECT astronaut, metric, AVG(value) AS v FROM measurements"
            " WHERE day<=0 AND quality='good' GROUP BY astronaut, metric").fetchall()
        for r in rows:
            self.set_baseline(r["astronaut"], r["metric"], round(r["v"], 3))
        return len(rows)

    # ---------- results ----------
    def save_result(self, r):
        cols = ["astronaut", "day", "domain", "metric", "value", "baseline", "pct_change", "mdc",
                "real_change", "bad_direction", "predicted", "residual", "resid_sd", "unexpected",
                "flagged", "persistent", "status", "reason"]
        self.con.execute(f"INSERT INTO results ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                         [r.get(c) for c in cols])
        self.con.commit()

    def get_recent_results(self, astronaut, metric, n, before_day):
        rows = self.con.execute(
            "SELECT * FROM results WHERE astronaut=? AND metric=? AND day<? ORDER BY day DESC LIMIT ?",
            (astronaut, metric, before_day, n)).fetchall()
        return [dict(r) for r in rows]

    def get_latest_result(self, astronaut, metric, up_to_day):
        row = self.con.execute(
            "SELECT * FROM results WHERE astronaut=? AND metric=? AND day<=? ORDER BY day DESC LIMIT 1",
            (astronaut, metric, up_to_day)).fetchone()
        return dict(row) if row else None

    # ---------- alerts + plans ----------
    def save_alert(self, astronaut, day, time, tier, domain, key, message):
        """Same alert key only once per astronaut per day (no alarm fatigue)."""
        cur = self.con.execute(
            "INSERT OR IGNORE INTO alerts (astronaut,day,time,tier,domain,key,message) VALUES (?,?,?,?,?,?,?)",
            (astronaut, day, time, tier, domain, key, message))
        self.con.commit()
        return cur.rowcount == 1

    def get_alerts(self, astronaut, day):
        return [dict(r) for r in self.con.execute(
            "SELECT * FROM alerts WHERE astronaut=? AND day=? ORDER BY time", (astronaut, day))]

    def save_scores(self, astronaut, day, fused, tier):
        rows = [(astronaut, day, d, s, fused["statuses"][d]) for d, s in fused["scores"].items()]
        rows.append((astronaut, day, "overall", fused["overall"], tier))
        self.con.executemany("INSERT OR REPLACE INTO daily_scores VALUES (?,?,?,?,?)", rows)
        self.con.commit()

    def save_plan(self, astronaut, made_on_day, scheduled_day, action, note=""):
        self.con.execute(
            "INSERT INTO plans (astronaut,made_on_day,scheduled_day,action,note) VALUES (?,?,?,?,?)",
            (astronaut, made_on_day, scheduled_day, action, note))
        self.con.commit()


def open_db(path=DB_PATH):
    """Open a fresh database. Fallback: if the file is locked or broken, use memory only."""
    try:
        return DB(path, fresh=True)
    except sqlite3.Error as e:
        print(f"  ! could not open {os.path.basename(path)} ({e}) — running in memory, nothing will be saved")
        return DB(":memory:", fresh=True)
