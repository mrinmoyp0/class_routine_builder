"""
database.py
Data layer for the Class Routine Builder.
Uses MongoDB Atlas for persistent cloud storage so data survives app restarts.

Collections (all inside the "Routine" database):
  teachers, subjects, time_slots, assignments, counters

Time slots are scoped per program+semester so each routine can have its own
period layout.  Teacher-conflict detection uses actual time-range overlap
(start_minutes / end_minutes) so it works correctly even when different
semesters have different period grids.
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


def _parse_time_to_minutes(time_str):
    """Parse '9:00 AM' or '1:30 PM' into minutes from midnight."""
    s = time_str.strip().upper()
    is_pm = s.endswith("PM")
    s = s.replace("AM", "").replace("PM", "").strip()
    parts = s.split(":")
    hours = int(parts[0])
    minutes = int(parts[1]) if len(parts) > 1 else 0
    if is_pm and hours != 12:
        hours += 12
    elif not is_pm and hours == 12:
        hours = 0
    return hours * 60 + minutes


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def init_db():
    """Create indexes and clean up any legacy global time slots."""
    _teachers.create_index("id", unique=True)
    _teachers.create_index("name", unique=True)

    _subjects.create_index("id", unique=True)
    _subjects.create_index(
        [("program", 1), ("semester", 1), ("code", 1)], unique=True
    )

    _time_slots.create_index("id", unique=True)
    _time_slots.create_index([("program", 1), ("semester", 1), ("order_index", 1)])

    _assignments.create_index("id", unique=True)
    _assignments.create_index(
        [("program", 1), ("semester", 1), ("day", 1), ("slot_id", 1)],
        unique=True,
    )

    # Migration: remove old global time slots that lack program/semester.
    _time_slots.delete_many({"program": {"$exists": False}})


# ---------------------------------------------------------------------------
# Default slot seeding (per program+semester)
# ---------------------------------------------------------------------------

_DEFAULT_SLOTS = [
    (1, "Period 1",     "9:00 AM",  "9:50 AM",  0),
    (2, "Period 2",     "9:50 AM",  "10:40 AM", 0),
    (3, "Period 3",     "10:40 AM", "11:30 AM", 0),
    (4, "Period 4",     "11:30 AM", "12:20 PM", 0),
    (5, "Period 5",     "12:20 PM", "1:10 PM",  0),
    (6, "Lunch Break",  "1:10 PM",  "2:00 PM",  1),
    (7, "Period 6",     "2:00 PM",  "2:50 PM",  0),
    (8, "Period 7",     "2:50 PM",  "3:40 PM",  0),
    (9, "Period 8",     "3:40 PM",  "4:30 PM",  0),
]


def seed_default_slots(program, semester):
    """Create the 9 default periods for *program*+*semester* if none exist."""
    if _time_slots.count_documents({"program": program, "semester": semester}) > 0:
        return
    for order_index, label, start, end, is_break in _DEFAULT_SLOTS:
        _time_slots.insert_one(
            {
                "id": _next_id("time_slots"),
                "program": program,
                "semester": semester,
                "order_index": order_index,
                "label": label,
                "start_time": start,
                "end_time": end,
                "is_break": is_break,
                "start_minutes": _parse_time_to_minutes(start),
                "end_minutes": _parse_time_to_minutes(end),
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
    _assignments.delete_many({"subject_id": subject_id})


def assigned_count(subject_id):
    return _assignments.count_documents({"subject_id": subject_id})


def update_subject_teacher(subject_id, teacher_id):
    """Assign or change the teacher for a subject."""
    _subjects.update_one(
        {"id": subject_id}, {"$set": {"teacher_id": teacher_id}}
    )


# ---------- Time slots (per program + semester) ----------

def list_time_slots(program, semester):
    return list(
        _time_slots.find(
            {"program": program, "semester": semester}, {"_id": 0}
        ).sort("order_index", 1)
    )


def add_time_slot(program, semester, label, start_time, end_time, is_break):
    last = _time_slots.find_one(
        {"program": program, "semester": semester},
        sort=[("order_index", -1)],
    )
    max_order = last["order_index"] if last else 0
    _time_slots.insert_one(
        {
            "id": _next_id("time_slots"),
            "program": program,
            "semester": semester,
            "order_index": max_order + 1,
            "label": label.strip(),
            "start_time": start_time,
            "end_time": end_time,
            "is_break": int(is_break),
            "start_minutes": _parse_time_to_minutes(start_time),
            "end_minutes": _parse_time_to_minutes(end_time),
        }
    )


def delete_time_slot(slot_id):
    _time_slots.delete_one({"id": slot_id})
    _assignments.delete_many({"slot_id": slot_id})


def toggle_break(slot_id):
    """Flip the is_break flag on a time slot."""
    slot = _time_slots.find_one({"id": slot_id})
    if slot:
        _time_slots.update_one(
            {"id": slot_id},
            {"$set": {"is_break": 0 if slot["is_break"] else 1}},
        )


def move_time_slot(slot_id, direction):
    """direction: -1 to move up, +1 to move down (within the same program+semester)."""
    slot = _time_slots.find_one({"id": slot_id}, {"_id": 0})
    if not slot:
        return
    slots = list(
        _time_slots.find(
            {"program": slot["program"], "semester": slot["semester"]},
            {"_id": 0},
        ).sort("order_index", 1)
    )
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
    """Return dict keyed ``'day|slot_id'`` -> row with subject + teacher info."""
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


def assign_slot(program, semester, day, slot_id, subject_id, span=1):
    """Assign a subject to *span* consecutive slots.

    No credit cap is enforced — credit is informational only.
    Teacher conflicts are checked via actual time-range overlap so they work
    across semesters that may have different period layouts.

    Returns ``(ok: bool, message: str)``.
    """
    subject = _subjects.find_one({"id": subject_id}, {"_id": 0})
    if subject is None:
        return False, "Subject not found."

    # Resolve the ordered slot list for this program+semester.
    all_slots = list(
        _time_slots.find(
            {"program": program, "semester": semester}, {"_id": 0}
        ).sort("order_index", 1)
    )
    slot_ids = [s["id"] for s in all_slots]
    try:
        start_idx = slot_ids.index(slot_id)
    except ValueError:
        return False, "Time slot not found."

    if start_idx + span > len(all_slots):
        return False, f"Not enough slots to span {span} periods."

    target_slots = all_slots[start_idx : start_idx + span]

    # All target slots must be empty.
    for ts in target_slots:
        if _assignments.find_one(
            {"program": program, "semester": semester, "day": day, "slot_id": ts["id"]}
        ):
            return False, f"Slot '{ts['label']}' is already filled."

    # Teacher-conflict check using time-range overlap.
    if subject.get("teacher_id") is not None:
        target_start = min(ts.get("start_minutes", 0) for ts in target_slots)
        target_end = max(ts.get("end_minutes", 0) for ts in target_slots)

        conflict_pipeline = [
            {"$match": {"day": day}},
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
                "$lookup": {
                    "from": "time_slots",
                    "localField": "slot_id",
                    "foreignField": "id",
                    "as": "_slot",
                }
            },
            {"$unwind": "$_slot"},
            {
                "$project": {
                    "_id": 0,
                    "program": 1,
                    "semester": 1,
                    "subject_code": "$_subj.code",
                    "start_minutes": "$_slot.start_minutes",
                    "end_minutes": "$_slot.end_minutes",
                }
            },
        ]
        for r in _assignments.aggregate(conflict_pipeline):
            if r["program"] == program and r["semester"] == semester:
                continue
            r_start = r.get("start_minutes", 0)
            r_end = r.get("end_minutes", 0)
            if target_start < r_end and r_start < target_end:
                return (
                    False,
                    f"Teacher conflict: already assigned to {r['subject_code']} "
                    f"({r['program']}, Sem {r['semester']}) at an overlapping time.",
                )

    # Insert one assignment per spanned slot.
    for ts in target_slots:
        try:
            _assignments.insert_one(
                {
                    "id": _next_id("assignments"),
                    "program": program,
                    "semester": semester,
                    "day": day,
                    "slot_id": ts["id"],
                    "subject_id": subject_id,
                }
            )
        except DuplicateKeyError:
            return False, f"Slot '{ts['label']}' is already filled."

    return True, "Assigned."


def clear_slot(program, semester, day, slot_id, span=1):
    """Clear one or more consecutive slot assignments."""
    if span <= 1:
        _assignments.delete_one(
            {"program": program, "semester": semester, "day": day, "slot_id": slot_id}
        )
    else:
        all_slots = list(
            _time_slots.find(
                {"program": program, "semester": semester}, {"_id": 0}
            ).sort("order_index", 1)
        )
        slot_ids = [s["id"] for s in all_slots]
        try:
            start_idx = slot_ids.index(slot_id)
        except ValueError:
            return
        target_ids = slot_ids[start_idx : start_idx + span]
        _assignments.delete_many(
            {
                "program": program,
                "semester": semester,
                "day": day,
                "slot_id": {"$in": target_ids},
            }
        )


def list_program_semesters():
    """Distinct (program, semester) combos that have at least one subject."""
    pipeline = [
        {"$group": {"_id": {"program": "$program", "semester": "$semester"}}},
        {"$sort": {"_id.program": 1, "_id.semester": 1}},
    ]
    rows = list(_subjects.aggregate(pipeline))
    return [(r["_id"]["program"], r["_id"]["semester"]) for r in rows]


def clear_all_assignments(program, semester):
    """Remove every assignment for *program*+*semester*."""
    _assignments.delete_many({"program": program, "semester": semester})
