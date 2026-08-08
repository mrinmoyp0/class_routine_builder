import os
import streamlit.components.v1 as components

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")

_component_func = components.declare_component(
    "routine_grid",
    path=_FRONTEND_DIR,
)


def routine_grid(days, slots, assignments, subjects, key=None):
    """
    Renders the interactive React timetable grid.

    days: list[str]
    slots: list[dict] with id, label, start_time, end_time, is_break
    assignments: dict "Day|slot_id" -> {subject_id, subject_code, subject_name, teacher_name}
    subjects: list[dict] with id, code, name, credit, assigned_count, teacher_name

    Returns the last user action as a dict: {action: "assign"|"clear", day, slot_id, subject_id, nonce}
    or None if nothing has happened yet.
    """
    return _component_func(
        days=days,
        slots=slots,
        assignments=assignments,
        subjects=subjects,
        key=key,
        default=None,
    )
