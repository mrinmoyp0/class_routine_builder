"""
database.py
Data layer for the Class Routine Builder.
Uses MongoDB Atlas for persistent cloud storage so data survives app restarts.

Collections (all inside the "Routine" database):
  teachers, subjects, time_slots, assignments, counters

Integer IDs are preserved via a "counters" collection so the rest of the
codebase (app.py, export_excel.py, the React grid) keeps working unchanged.
"""

from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError

MONGO_URI = (
    "mongodb+srv://MongoDB:S5eEJADM1mh5zUzt@cluster0.sy74t.mongodb.net/"
    "?retryWrites=true&w=majority&appName=Cluster0"
)
DB_NAME = "Routine"

PROGRAMS = ["B.Tech Computer Science", "BSc Data Science", "BCA"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

# ---------------------------------------------------------------------------
# Connection (single pooled client, created once at import time)
# ---------------------------------------------------------------------------
_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
_db = _client[DB_NAME]

_teachers = _db["teachers"]
_subjects = _db["subjects"]
_time_slots = _db["time_slots"]
_assignments = _db["assignments"]
_counters = _db["counters"]


def _next_id(collection_name):
    """Return the next auto-incrementing integer id for *collection_name*."""
    doc = _counters.find_one_and_update(
        {"_id": collection_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return doc["seq"]


# ---------------------------------------------------------------------------
# Initialisation — indexes + default seed data
# ---------------------------------------------------------------------------

def init_db():
    """Create indexes and seed default time slots if the collection is empty."""
    _teachers.create_index("id", unique=True)
    _teachers.create_index("name", unique=True)

    _subjects.create_index("id", unique=True)
    _subjects.create_index(
        [("program", 1), ("semester", 1), ("code", 1)], unique=True
    )

    _time_slots.create_index("id", unique=True)
    _time_slots.create_index("order_index")

    _assignments.create_index("id", unique=True)
    _assignments.create_index(
        [("program", 1), ("semester", 1), ("day", 1), ("slot_id", 1)],
        unique=True,
    )

    # Seed a default set of periods on first run only.
    if _time_slots.count_documents({}) == 0:
        defaults = [
            (1, "Period 1", "09:00", "09:55", 0),
            (2, "Period 2", "09:55", "10:50", 0),
            (3, "Period 3", "10:50", "11:45", 0),
            (4, "Lunch Break", "11:45", "12:30", 1),
            (5, "Period 4", "12:30", "13:25", 0),
            (6, "Period 5", "13:25", "14:20", 0),
            (7, "Period 6", "14:20", "15:15", 0),
        ]
        for order_index, label, start_time, end_time, is_break in defaults:
            _time_slots.insert_one(
                {
                    "id": _next_id("time_slots"),
                    "order_index": order_index,
                    "label": label,
                    "start_time": start_time,
                    "end_time": end_time,
                    "is_break": is_break,
                }
            )


# ---------- Teachers ----------

def add_teacher(name, short_code=""):
    _teachers.insert_one(
        {
            "id": _next_id("teachers"),
            "name": name.strip(),
            "short_code": short_code.strip(),
        }
    )


def list_teachers():
    return list(_teachers.find({}, {"_id": 0}).sort("name", 1))


def delete_teacher(teacher_id):
    _teachers.delete_one({"id": teacher_id})
    # Replicate ON DELETE SET NULL: un-link this teacher from all subjects.
    _subjects.update_many(
        {"teacher_id": teacher_id}, {"$set": {"teacher_id": None}}
    )


# ---------- Subjects ----------

def add_subject(program, semester, name, code, credit, teacher_id):
    _subjects.insert_one(
        {
            "id": _next_id("subjects"),
            "program": program,
            "semester": semester,
            "name": name.strip(),
            "code": code.strip(),
            "credit": credit,
            "teacher_id": teacher_id,
        }
    )


def list_subjects(program=None, semester=None):
    match = {}
    if program is not None:
        match["program"] = program
    if semester is not None:
        match["semester"] = semester

    pipeline = [
        {"$match": match},
        {
            "$lookup": {
                "from": "teachers",
                "localField": "teacher_id",
                "foreignField": "id",
                "as": "_teacher",
            }
        },
        {
            "$addFields": {
                "teacher_name": {
                    "$ifNull": [{"$arrayElemAt": ["$_teacher.name", 0]}, None]
                }
            }
        },
        {"$project": {"_id": 0, "_teacher": 0}},
        {"$sort": {"code": 1}},
    ]
    return list(_subjects.aggregate(pipeline))


def delete_subject(subject_id):
    _subjects.delete_one({"id": subject_id})
    # Replicate ON DELETE CASCADE: remove all assignments for this subject.
    _assignments.delete_many({"subject_id": subject_id})


def assigned_count(subject_id):
    return _assignments.count_documents({"subject_id": subject_id})


def update_subject_teacher(subject_id, teacher_id):
    """Assign or change the teacher for a subject (used when a teacher is
    recruited after the subject was already created)."""
    _subjects.update_one(
        {"id": subject_id}, {"$set": {"teacher_id": teacher_id}}
    )


# ---------- Time slots ----------

def list_time_slots():
    return list(_time_slots.find({}, {"_id": 0}).sort("order_index", 1))


def add_time_slot(label, start_time, end_time, is_break):
    last = _time_slots.find_one({}, sort=[("order_index", -1)])
    max_order = last["order_index"] if last else 0
    _time_slots.insert_one(
        {
            "id": _next_id("time_slots"),
            "order_index": max_order + 1,
            "label": label.strip(),
            "start_time": start_time,
            "end_time": end_time,
            "is_break": int(is_break),
        }
    )


def delete_time_slot(slot_id):
    _time_slots.delete_one({"id": slot_id})
    # Replicate ON DELETE CASCADE: remove assignments that reference this slot.
    _assignments.delete_many({"slot_id": slot_id})


def move_time_slot(slot_id, direction):
    """direction: -1 to move up, +1 to move down."""
    slots = list(_time_slots.find({}, {"_id": 0}).sort("order_index", 1))
    ids = [s["id"] for s in slots]
    idx = ids.index(slot_id)
    swap_idx = idx + direction
    if 0 <= swap_idx < len(ids):
        a, b = slots[idx], slots[swap_idx]
        _time_slots.update_one(
            {"id": a["id"]}, {"$set": {"order_index": b["order_index"]}}
        )
        _time_slots.update_one(
            {"id": b["id"]}, {"$set": {"order_index": a["order_index"]}}
        )


# ---------- Assignments / routine building ----------

def get_assignments(program, semester):
    """Return dict keyed ``'day|slot_id'`` → row with subject + teacher info."""
    pipeline = [
        {"$match": {"program": program, "semester": semester}},
        {
            "$lookup": {
                "from": "subjects",
                "localField": "subject_id",
                "foreignField": "id",
                "as": "_subj",
            }
        },
        {"$unwind": "$_subj"},
        {
            "$lookup": {
                "from": "teachers",
                "localField": "_subj.teacher_id",
                "foreignField": "id",
                "as": "_teacher",
            }
        },
        {
            "$addFields": {
                "subject_name": "$_subj.name",
                "subject_code": "$_subj.code",
                "teacher_name": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$_teacher.name", 0]},
                        None,
                    ]
                },
            }
        },
        {"$project": {"_id": 0, "_subj": 0, "_teacher": 0}},
    ]
    rows = list(_assignments.aggregate(pipeline))
    return {f"{r['day']}|{r['slot_id']}": r for r in rows}


def assign_slot(program, semester, day, slot_id, subject_id):
    """Assign a subject to a slot after validating teacher conflicts and the
    credit cap.  Returns ``(ok: bool, message: str)``."""
    subject = _subjects.find_one({"id": subject_id}, {"_id": 0})
    if subject is None:
        return False, "Subject not found."

    used = _assignments.count_documents({"subject_id": subject_id})
    if used >= subject["credit"]:
        return (
            False,
            f"{subject['code']} already has all {subject['credit']} classes scheduled this week.",
        )

    # Teacher-conflict check across all programs / semesters.
    if subject.get("teacher_id") is not None:
        conflict_pipeline = [
            {"$match": {"day": day, "slot_id": slot_id}},
            {
                "$lookup": {
                    "from": "subjects",
                    "localField": "subject_id",
                    "foreignField": "id",
                    "as": "_subj",
                }
            },
            {"$unwind": "$_subj"},
            {"$match": {"_subj.teacher_id": subject["teacher_id"]}},
            {
                "$project": {
                    "_id": 0,
                    "program": 1,
                    "semester": 1,
                    "subject_code": "$_subj.code",
                }
            },
        ]
        for r in _assignments.aggregate(conflict_pipeline):
            if not (r["program"] == program and r["semester"] == semester):
                return (
                    False,
                    f"Teacher conflict: already assigned to {r['subject_code']} "
                    f"({r['program']}, Sem {r['semester']}) at this time slot.",
                )

    try:
        _assignments.insert_one(
            {
                "id": _next_id("assignments"),
                "program": program,
                "semester": semester,
                "day": day,
                "slot_id": slot_id,
                "subject_id": subject_id,
            }
        )
    except DuplicateKeyError:
        return False, "That slot is already filled."
    return True, "Assigned."


def list_program_semesters():
    """Distinct (program, semester) combos that have at least one subject."""
    pipeline = [
        {
            "$group": {
                "_id": {"program": "$program", "semester": "$semester"}
            }
        },
        {"$sort": {"_id.program": 1, "_id.semester": 1}},
    ]
    rows = list(_subjects.aggregate(pipeline))
    return [(r["_id"]["program"], r["_id"]["semester"]) for r in rows]


def clear_slot(program, semester, day, slot_id):
    _assignments.delete_one(
        {
            "program": program,
            "semester": semester,
            "day": day,
            "slot_id": slot_id,
        }
    )
