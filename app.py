"""
app.py
Class Routine Builder — Streamlit app with an embedded custom React grid.

Run with:  streamlit run app.py
"""

import streamlit as st
import database as db
from export_excel import build_workbook
from components.routine_grid import routine_grid

st.set_page_config(page_title="Class Routine Builder", page_icon="📖", layout="wide")
db.init_db()

# ---------------------------------------------------------------------------
# Theme: printed academic ledger — cream paper, navy ink, gold rule, sage for
# filled classes, terracotta reserved for delete/error only.
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Lora:wght@600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap');

    html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
    .stApp { background-color: #FAF7F0; }

    h1, h2, h3 { font-family: 'Lora', serif !important; color: #1F2A44 !important; }
    h1 { border-bottom: 2px solid #B8863B; padding-bottom: 10px; }

    section[data-testid="stSidebar"] {
        background-color: #1F2A44;
    }
    section[data-testid="stSidebar"] * { color: #FAF7F0 !important; }
    section[data-testid="stSidebar"] .stRadio label:hover { color: #B8863B !important; }

    .stButton>button {
        background-color: #1F2A44;
        color: #FAF7F0;
        border: 1px solid #1F2A44;
        border-radius: 2px;
        font-weight: 500;
    }
    .stButton>button:hover { background-color: #B8863B; border-color: #B8863B; color: #1F2A44; }

    .stDownloadButton>button {
        background-color: #5C8374;
        color: #FAF7F0;
        border-radius: 2px;
        border: none;
    }

    div[data-testid="stMetric"] {
        background: #F3EEE1;
        border: 1px solid #D9D2BE;
        border-left: 3px solid #B8863B;
        padding: 10px 14px;
    }

    .ledger-note {
        font-size: 13px;
        color: #6B6350;
        border-left: 3px solid #D9D2BE;
        padding-left: 10px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
st.sidebar.markdown("## 📖 Routine Builder")
page = st.sidebar.radio(
    "Navigate",
    ["Teachers", "Subjects", "Time Slots", "Build Routine", "Export"],
    label_visibility="collapsed",
)


def credit_bar(used, total):
    filled = "●" * min(used, total)
    empty = "○" * max(total - used, 0)
    return filled + empty


# ---------------------------------------------------------------------------
# Teachers
# ---------------------------------------------------------------------------
def page_teachers():
    st.title("Teachers")
    st.markdown('<p class="ledger-note">Add every teacher once here, then assign them to subjects on the Subjects page.</p>', unsafe_allow_html=True)

    with st.form("add_teacher_form", clear_on_submit=True):
        c1, c2 = st.columns([3, 1])
        name = c1.text_input("Teacher name")
        short_code = c2.text_input("Short code (optional)", max_chars=10)
        submitted = st.form_submit_button("Add teacher")
        if submitted:
            if not name.strip():
                st.error("Enter a teacher name.")
            else:
                try:
                    db.add_teacher(name, short_code)
                    st.success(f"Added {name}.")
                except Exception as ex:
                    st.error(f"Could not add teacher: {ex}")

    teachers = db.list_teachers()
    st.subheader(f"All teachers ({len(teachers)})")
    if not teachers:
        st.info("No teachers yet — add one above.")
    else:
        for t in teachers:
            c1, c2, c3 = st.columns([4, 2, 1])
            c1.write(t["name"])
            c2.write(t["short_code"] or "—")
            if c3.button("Remove", key=f"del_teacher_{t['id']}"):
                db.delete_teacher(t["id"])
                st.rerun()


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------
def page_subjects():
    st.title("Subjects")
    st.markdown('<p class="ledger-note">Credit = classes per week (Monday–Friday) for that subject.</p>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    program = c1.selectbox("Program", db.PROGRAMS, key="subj_program")
    semester = c2.number_input("Semester", min_value=1, max_value=8, value=1, step=1, key="subj_semester")

    teachers = db.list_teachers()
    teacher_options = {"— none —": None}
    teacher_options.update({t["name"]: t["id"] for t in teachers})

    with st.form("add_subject_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([3, 2, 1, 2])
        name = c1.text_input("Course name")
        code = c2.text_input("Subject code")
        credit = c3.number_input("Credit", min_value=1, max_value=6, value=3, step=1)
        teacher_label = c4.selectbox("Teacher", list(teacher_options.keys()))
        submitted = st.form_submit_button("Add subject")
        if submitted:
            if not name.strip() or not code.strip():
                st.error("Enter both course name and subject code.")
            else:
                try:
                    db.add_subject(program, int(semester), name, code, int(credit), teacher_options[teacher_label])
                    st.success(f"Added {code} — {name}.")
                except Exception as ex:
                    st.error(f"Could not add subject (code may already exist for this program/semester): {ex}")

    subjects = db.list_subjects(program, int(semester))
    st.subheader(f"{program} · Semester {int(semester)} — {len(subjects)} subject(s)")
    if not subjects:
        st.info("No subjects yet for this program and semester — add one above.")
    else:
        # Build teacher lookup once for all subject rows.
        teacher_names_list = ["— none —"] + [t["name"] for t in teachers]
        teacher_id_map = {"— none —": None}
        teacher_id_map.update({t["name"]: t["id"] for t in teachers})

        def _on_teacher_update(subject_id, tid_map, sel_key):
            db.update_subject_teacher(subject_id, tid_map[st.session_state[sel_key]])

        for s in subjects:
            used = db.assigned_count(s["id"])
            c1, c2, c3, c4, c5 = st.columns([3, 2, 1, 2, 1])
            c1.write(f"**{s['code']}** — {s['name']}")

            current_teacher = s.get("teacher_name") or "— none —"
            if current_teacher not in teacher_names_list:
                current_teacher = "— none —"
            sel_key = f"teacher_sel_{s['id']}"
            c2.selectbox(
                "Teacher",
                teacher_names_list,
                index=teacher_names_list.index(current_teacher),
                key=sel_key,
                label_visibility="collapsed",
                on_change=_on_teacher_update,
                args=(s["id"], teacher_id_map, sel_key),
            )

            c3.write(f"Cr {s['credit']}")
            c4.markdown(f"`{credit_bar(used, s['credit'])}`  {used}/{s['credit']} placed")
            if c5.button("Remove", key=f"del_subject_{s['id']}"):
                db.delete_subject(s["id"])
                st.rerun()


# ---------------------------------------------------------------------------
# Time slots
# ---------------------------------------------------------------------------
def page_time_slots():
    st.title("Time Slots")
    st.markdown('<p class="ledger-note">This period grid is shared across all programs and semesters.</p>', unsafe_allow_html=True)

    with st.form("add_slot_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
        label = c1.text_input("Label", placeholder="e.g. Period 7")
        start_time = c2.text_input("Start", placeholder="3:15 PM")
        end_time = c3.text_input("End", placeholder="4:10 PM")
        is_break = c4.checkbox("Break?")
        submitted = st.form_submit_button("Add period")
        if submitted:
            if not label.strip() or not start_time.strip() or not end_time.strip():
                st.error("Fill in label, start time, and end time.")
            else:
                db.add_time_slot(label, start_time, end_time, is_break)
                st.success(f"Added {label}.")
                st.rerun()

    slots = db.list_time_slots()
    st.subheader(f"Weekly periods ({len(slots)})")
    if not slots:
        st.info("No periods defined yet.")
    for i, s in enumerate(slots):
        c1, c2, c3, c4, c5, c6 = st.columns([3, 2, 1, 1, 1, 1])
        c1.write(("🔸 " if s["is_break"] else "▪️ ") + s["label"])
        c2.write(f"{s['start_time']} – {s['end_time']}")
        if c3.button("↑", key=f"up_{s['id']}", disabled=(i == 0)):
            db.move_time_slot(s["id"], -1)
            st.rerun()
        if c4.button("↓", key=f"down_{s['id']}", disabled=(i == len(slots) - 1)):
            db.move_time_slot(s["id"], 1)
            st.rerun()
        if c6.button("Remove", key=f"del_slot_{s['id']}"):
            db.delete_time_slot(s["id"])
            st.rerun()


# ---------------------------------------------------------------------------
# Build routine
# ---------------------------------------------------------------------------
def page_build_routine():
    st.title("Build Routine")

    c1, c2 = st.columns(2)
    program = c1.selectbox("Program", db.PROGRAMS, key="build_program")
    semester = int(c2.number_input("Semester", min_value=1, max_value=8, value=1, step=1, key="build_semester"))

    msg_key = f"pending_msg_{program}_{semester}"
    if msg_key in st.session_state:
        kind, text = st.session_state.pop(msg_key)
        (st.success if kind == "success" else st.error)(text)

    subjects_rows = db.list_subjects(program, semester)
    if not subjects_rows:
        st.warning("No subjects defined for this program and semester yet. Add some on the Subjects page first.")
        return

    slots_rows = db.list_time_slots()
    if not slots_rows:
        st.warning("No time slots defined yet. Add some on the Time Slots page first.")
        return

    subjects_payload = []
    for s in subjects_rows:
        subjects_payload.append(
            {
                "id": s["id"],
                "code": s["code"],
                "name": s["name"],
                "credit": s["credit"],
                "assigned_count": db.assigned_count(s["id"]),
                "teacher_name": s["teacher_name"],
            }
        )

    slots_payload = [
        {
            "id": s["id"],
            "label": s["label"],
            "start_time": s["start_time"],
            "end_time": s["end_time"],
            "is_break": bool(s["is_break"]),
        }
        for s in slots_rows
    ]

    assignments_payload = db.get_assignments(program, semester)

    st.markdown('<p class="ledger-note">Click an empty cell to assign a subject. Click the × on a filled cell to clear it. Blank cells stay blank.</p>', unsafe_allow_html=True)

    action = routine_grid(
        days=db.DAYS,
        slots=slots_payload,
        assignments=assignments_payload,
        subjects=subjects_payload,
        key=f"grid_{program}_{semester}",
    )

    if action is not None:
        nonce_key = f"last_nonce_{program}_{semester}"
        if st.session_state.get(nonce_key) != action.get("nonce"):
            st.session_state[nonce_key] = action.get("nonce")
            if action["action"] == "assign":
                ok, text = db.assign_slot(program, semester, action["day"], action["slot_id"], action["subject_id"])
                st.session_state[msg_key] = ("success" if ok else "error", text)
            elif action["action"] == "clear":
                db.clear_slot(program, semester, action["day"], action["slot_id"])
                st.session_state[msg_key] = ("success", "Slot cleared.")
            st.rerun()

    st.subheader("Credit progress")
    for s in subjects_payload:
        st.markdown(f"`{credit_bar(s['assigned_count'], s['credit'])}`  **{s['code']}** — {s['assigned_count']}/{s['credit']} classes placed")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def page_export():
    st.title("Export to Excel")

    combos = db.list_program_semesters()
    if not combos:
        st.info("No subjects defined yet — there's nothing to export.")
        return

    st.markdown('<p class="ledger-note">Pick which routines to include. Each becomes its own sheet in the workbook.</p>', unsafe_allow_html=True)
    labels = [f"{p} — Semester {sem}" for p, sem in combos]
    selected = st.multiselect("Include", labels, default=labels)
    selected_combos = [combos[labels.index(l)] for l in selected]

    if st.button("Generate Excel workbook", disabled=(not selected_combos)):
        buf = build_workbook(selected_combos)
        st.session_state["export_buf"] = buf.getvalue()

    if "export_buf" in st.session_state:
        st.download_button(
            "⬇ Download class_routine.xlsx",
            data=st.session_state["export_buf"],
            file_name="class_routine.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


# ---------------------------------------------------------------------------
PAGES = {
    "Teachers": page_teachers,
    "Subjects": page_subjects,
    "Time Slots": page_time_slots,
    "Build Routine": page_build_routine,
    "Export": page_export,
}
PAGES[page]()
