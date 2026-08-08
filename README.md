# Class Routine Builder

A Streamlit app (Python) with an embedded custom React grid for building
weekly class routines for B.Tech Computer Science, BSc Data Science, and
BCA — with teacher double-booking prevention and one-click Excel export.

## How it's built

- **Python (Streamlit)** owns everything: data storage (SQLite, `routine.db`,
  created automatically on first run), all business logic (teacher-conflict
  checks, credit-based scheduling limits), navigation, and the Excel export.
- **React** (loaded from a CDN, no Node/npm build step required) renders the
  interactive timetable grid — the one part of the UI where click-to-assign
  interactivity genuinely helps — as a custom Streamlit component in
  `components/routine_grid/frontend/index.html`. It talks back to Python
  using Streamlit's own component protocol, so every assignment is validated
  and stored server-side in Python before the grid updates.

## Setup

```bash
pip install -r requirements.txt
streamlit run app.py
```

This opens the app in your browser (usually http://localhost:8501). No
internet connection is needed to run it, other than your browser loading the
React library and fonts from public CDNs the first time.

## Using it

1. **Teachers** — add every teacher once.
2. **Subjects** — pick a Program + Semester, then add subjects with their
   course name, subject code, credit (= classes/week), and teacher.
3. **Time Slots** — the weekly period grid (Mon–Fri) is shared across all
   programs/semesters. Defaults are pre-filled; add, reorder, or remove
   periods, and mark any as a break.
4. **Build Routine** — pick a Program + Semester, then click an empty cell to
   assign a subject to that day/period. A subject stops appearing as an
   option once it has reached its credit count for the week. If you try to
   put the same teacher in two classes at the same time slot (even across
   different programs/semesters), the app blocks it and tells you why. Empty
   slots are simply left blank — nothing is auto-filled.
5. **Export** — pick which program/semester routines to include and download
   a single `.xlsx` workbook, one formatted sheet per routine.

## Notes

- All data lives in `routine.db` next to `app.py`. Delete that file to start
  fresh, or back it up to keep your data.
- Semester is a plain number (1–8) attached to each subject/routine, so you
  can build and keep multiple semesters per program side by side.
