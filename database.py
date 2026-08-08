"""
database.py
Data layer for the Class Routine Builder.
Everything (schema, CRUD, conflict/credit logic) lives here in plain Python + sqlite3
so the app has a single source of truth that both the Streamlit pages and the
embedded React grid component read from / write to.
"""

import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "routine.db")

PROGRAMS = ["B.Tech Computer Science", "BSc Data Science", "BCA"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS teachers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                short_code TEXT
            );

            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                program TEXT NOT NULL,
                semester INTEGER NOT NULL,
                name TEXT NOT NULL,
                code TEXT NOT NULL,
                credit INTEGER NOT NULL,
                teacher_id INTEGER,
                FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE SET NULL,
                UNIQUE(program, semester, code)
            );

            CREATE TABLE IF NOT EXISTS time_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_index INTEGER NOT NULL,
                label TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                is_break INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                program TEXT NOT NULL,
                semester INTEGER NOT NULL,
                day TEXT NOT NULL,
                slot_id INTEGER NOT NULL,
                subject_id INTEGER NOT NULL,
                FOREIGN KEY (slot_id) REFERENCES time_slots(id) ON DELETE CASCADE,
                FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
                UNIQUE(program, semester, day, slot_id)
            );
            """
        )
        # Seed a default set of periods on first run only.
        count = conn.execute("SELECT COUNT(*) AS c FROM time_slots").fetchone()["c"]
        if count == 0:
            defaults = [
                (1, "Period 1", "09:00", "09:55", 0),
                (2, "Period 2", "09:55", "10:50", 0),
                (3, "Period 3", "10:50", "11:45", 0),
                (4, "Lunch Break", "11:45", "12:30", 1),
                (5, "Period 4", "12:30", "13:25", 0),
                (6, "Period 5", "13:25", "14:20", 0),
                (7, "Period 6", "14:20", "15:15", 0),
            ]
            conn.executemany(
                "INSERT INTO time_slots (order_index, label, start_time, end_time, is_break) VALUES (?,?,?,?,?)",
                defaults,
            )


# ---------- Teachers ----------

def add_teacher(name, short_code=""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO teachers (name, short_code) VALUES (?, ?)",
            (name.strip(), short_code.strip()),
        )


def list_teachers():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM teachers ORDER BY name").fetchall()


def delete_teacher(teacher_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM teachers WHERE id = ?", (teacher_id,))


# ---------- Subjects ----------

def add_subject(program, semester, name, code, credit, teacher_id):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO subjects (program, semester, name, code, credit, teacher_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (program, semester, name.strip(), code.strip(), credit, teacher_id),
        )


def list_subjects(program=None, semester=None):
    query = """
        SELECT s.*, t.name AS teacher_name
        FROM subjects s LEFT JOIN teachers t ON s.teacher_id = t.id
    """
    conditions, params = [], []
    if program is not None:
        conditions.append("s.program = ?")
        params.append(program)
    if semester is not None:
        conditions.append("s.semester = ?")
        params.append(semester)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY s.code"
    with get_conn() as conn:
        return conn.execute(query, params).fetchall()


def delete_subject(subject_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))


def assigned_count(subject_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM assignments WHERE subject_id = ?", (subject_id,)
        ).fetchone()
        return row["c"]


# ---------- Time slots ----------

def list_time_slots():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM time_slots ORDER BY order_index").fetchall()


def add_time_slot(label, start_time, end_time, is_break):
    with get_conn() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(order_index), 0) AS m FROM time_slots"
        ).fetchone()["m"]
        conn.execute(
            "INSERT INTO time_slots (order_index, label, start_time, end_time, is_break) VALUES (?,?,?,?,?)",
            (max_order + 1, label.strip(), start_time, end_time, int(is_break)),
        )


def delete_time_slot(slot_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM time_slots WHERE id = ?", (slot_id,))


def move_time_slot(slot_id, direction):
    """direction: -1 to move up, +1 to move down"""
    with get_conn() as conn:
        slots = conn.execute("SELECT * FROM time_slots ORDER BY order_index").fetchall()
        ids = [s["id"] for s in slots]
        idx = ids.index(slot_id)
        swap_idx = idx + direction
        if 0 <= swap_idx < len(ids):
            a, b = slots[idx], slots[swap_idx]
            conn.execute("UPDATE time_slots SET order_index = ? WHERE id = ?", (b["order_index"], a["id"]))
            conn.execute("UPDATE time_slots SET order_index = ? WHERE id = ?", (a["order_index"], b["id"]))


# ---------- Assignments / routine building ----------

def get_assignments(program, semester):
    """Returns dict keyed 'day|slot_id' -> row with subject + teacher info, for one program+semester."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT a.day, a.slot_id, a.subject_id, s.name AS subject_name, s.code AS subject_code,
                   t.name AS teacher_name
            FROM assignments a
            JOIN subjects s ON a.subject_id = s.id
            LEFT JOIN teachers t ON s.teacher_id = t.id
            WHERE a.program = ? AND a.semester = ?
            """,
            (program, semester),
        ).fetchall()
    return {f"{r['day']}|{r['slot_id']}": dict(r) for r in rows}


def find_teacher_conflict(teacher_id, day, slot_id, exclude_program=None, exclude_semester=None):
    """Returns the conflicting assignment row (program/semester/subject) if this teacher
    is already teaching some OTHER subject at this day+slot anywhere, else None."""
    if teacher_id is None:
        return None
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT a.program, a.semester, s.code AS subject_code, s.name AS subject_name
            FROM assignments a
            JOIN subjects s ON a.subject_id = s.id
            WHERE a.day = ? AND a.slot_id = ? AND s.teacher_id = ?
            """,
            (day, slot_id, teacher_id),
        ).fetchall()
    for r in rows:
        if r["program"] == exclude_program and r["semester"] == exclude_semester:
            continue
        return dict(r)
    return None


def assign_slot(program, semester, day, slot_id, subject_id):
    """Assigns a subject to a slot after validating teacher conflicts and credit cap.
    Returns (ok: bool, message: str)."""
    with get_conn() as conn:
        subject = conn.execute("SELECT * FROM subjects WHERE id = ?", (subject_id,)).fetchone()
        if subject is None:
            return False, "Subject not found."

        used = conn.execute(
            "SELECT COUNT(*) AS c FROM assignments WHERE subject_id = ?", (subject_id,)
        ).fetchone()["c"]
        if used >= subject["credit"]:
            return False, f"{subject['code']} already has all {subject['credit']} classes scheduled this week."

        if subject["teacher_id"] is not None:
            conflict_rows = conn.execute(
                """
                SELECT a.program, a.semester, s.code AS subject_code
                FROM assignments a JOIN subjects s ON a.subject_id = s.id
                WHERE a.day = ? AND a.slot_id = ? AND s.teacher_id = ?
                """,
                (day, slot_id, subject["teacher_id"]),
            ).fetchall()
            for r in conflict_rows:
                if not (r["program"] == program and r["semester"] == semester):
                    return False, (
                        f"Teacher conflict: already assigned to {r['subject_code']} "
                        f"({r['program']}, Sem {r['semester']}) at this time slot."
                    )

        try:
            conn.execute(
                """INSERT INTO assignments (program, semester, day, slot_id, subject_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (program, semester, day, slot_id, subject_id),
            )
        except sqlite3.IntegrityError:
            return False, "That slot is already filled."
        return True, "Assigned."


def list_program_semesters():
    """Distinct (program, semester) combos that have at least one subject defined."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT program, semester FROM subjects ORDER BY program, semester"
        ).fetchall()
    return [(r["program"], r["semester"]) for r in rows]


def clear_slot(program, semester, day, slot_id):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM assignments WHERE program = ? AND semester = ? AND day = ? AND slot_id = ?",
            (program, semester, day, slot_id),
        )
