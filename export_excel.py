"""
export_excel.py
Builds a downloadable .xlsx workbook of the routine grid(s) using openpyxl.
Supports per-semester time slots, merged (multi-period) assignments, and
break slots that may have assignments.
"""

import io
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

import database as db

INK = "1F2A44"
GOLD = "B8863B"
CREAM = "FAF7F0"
BREAK_FILL = "EAE4D6"

thin = Side(style="thin", color="C9C2AE")
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)


def _sheet_name(program, semester):
    short = {"B.Tech Computer Science": "BTech-CS", "BSc Data Science": "BSc-DS", "BCA": "BCA"}.get(
        program, program
    )
    name = f"{short} Sem{semester}"
    return name[:31]  # Excel sheet name limit


def _compute_merge_map(slots, assignments):
    """Build a dict  ``'day|slot_id' -> span (int)``  for merged cells.

    -  ``span > 1``  means the cell is the top of a vertically-merged group.
    - ``span == -1`` means the cell is hidden (swallowed by the merge above).
    """
    merge_map = {}
    for day in db.DAYS:
        i = 0
        while i < len(slots):
            key = f"{day}|{slots[i]['id']}"
            entry = assignments.get(key)
            if entry:
                span = 1
                while i + span < len(slots):
                    next_key = f"{day}|{slots[i + span]['id']}"
                    next_entry = assignments.get(next_key)
                    if next_entry and next_entry.get("subject_id") == entry.get("subject_id"):
                        span += 1
                    else:
                        break
                if span > 1:
                    merge_map[key] = span
                    for j in range(1, span):
                        merge_map[f"{day}|{slots[i + j]['id']}"] = -1
                i += span
            else:
                i += 1
    return merge_map


def build_workbook(program_semesters):
    """program_semesters: list of (program, semester) tuples to include, one sheet each."""
    wb = Workbook()
    wb.remove(wb.active)

    for program, semester in program_semesters:
        slots = db.list_time_slots(program, semester)
        if not slots:
            slots = []

        ws = wb.create_sheet(_sheet_name(program, semester))
        assignments = db.get_assignments(program, semester)
        merge_map = _compute_merge_map(slots, assignments)

        # Title row
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(db.DAYS) + 1)
        title_cell = ws.cell(row=1, column=1, value=f"{program} — Semester {semester}")
        title_cell.font = Font(size=14, bold=True, color=INK)
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 24

        # Header row
        header_row = 2
        ws.cell(row=header_row, column=1, value="Time").font = Font(bold=True, color="FFFFFF")
        ws.cell(row=header_row, column=1).fill = PatternFill("solid", fgColor=INK)
        ws.cell(row=header_row, column=1).alignment = Alignment(horizontal="center")
        ws.cell(row=header_row, column=1).border = BORDER

        for ci, day in enumerate(db.DAYS, start=2):
            c = ws.cell(row=header_row, column=ci, value=day)
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor=INK)
            c.alignment = Alignment(horizontal="center")
            c.border = BORDER

        # Body rows
        r = header_row + 1
        for slot in slots:
            time_label = f"{slot['label']}\n{slot['start_time']}-{slot['end_time']}"
            tc = ws.cell(row=r, column=1, value=time_label)
            tc.font = Font(bold=True, color=INK, size=9)
            tc.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            tc.border = BORDER
            tc.fill = PatternFill("solid", fgColor=CREAM)

            # A "pure break" row = break slot with NO assignments on any day.
            is_pure_break = slot["is_break"] and all(
                f"{day}|{slot['id']}" not in assignments for day in db.DAYS
            )

            if is_pure_break:
                ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=len(db.DAYS) + 1)
                bc = ws.cell(row=r, column=2, value=slot["label"])
                bc.font = Font(italic=True, color="6B6350")
                bc.alignment = Alignment(horizontal="center", vertical="center")
                bc.fill = PatternFill("solid", fgColor=BREAK_FILL)
                bc.border = BORDER
            else:
                for ci, day in enumerate(db.DAYS, start=2):
                    key = f"{day}|{slot['id']}"
                    m = merge_map.get(key)
                    entry = assignments.get(key)
                    cell = ws.cell(row=r, column=ci)
                    cell.border = BORDER
                    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

                    if m == -1:
                        # Swallowed by a merge above — leave blank (openpyxl
                        # already merged the cell range above).
                        continue

                    if m and m > 1:
                        ws.merge_cells(
                            start_row=r, start_column=ci,
                            end_row=r + m - 1, end_column=ci,
                        )

                    if entry:
                        cell.value = (
                            f"{entry['subject_code']}\n{entry['subject_name']}\n"
                            f"{entry['teacher_name'] or ''}"
                        )
                        cell.font = Font(size=9, color=INK)
                        cell.fill = PatternFill("solid", fgColor="EFEBDD")
                    elif slot["is_break"]:
                        cell.value = slot["label"]
                        cell.font = Font(italic=True, color="6B6350")
                        cell.fill = PatternFill("solid", fgColor=BREAK_FILL)
                    else:
                        cell.value = ""
            r += 1

        ws.column_dimensions["A"].width = 18
        for ci in range(2, len(db.DAYS) + 2):
            ws.column_dimensions[get_column_letter(ci)].width = 20
        for row in ws.iter_rows(min_row=header_row + 1, max_row=r - 1):
            ws.row_dimensions[row[0].row].height = 42
        ws.freeze_panes = "B3"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
