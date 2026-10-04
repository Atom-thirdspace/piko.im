from ..models import PUBLISHED, Unit, db, question_count


def problems(kind, row):
    out = []
    if kind == "lesson":
        if row.kind == "code" and row.problem_id is None:
            out.append("A code lesson needs a problem attached.")
        if row.kind == "quiz" and not question_count(row.id):
            out.append("A quiz lesson needs at least one question.")
        if row.kind != "code" and not (row.body_md or "").strip():
            out.append("The body is empty.")
    elif kind == "problem":
        if not (row.statement_md or "").strip():
            out.append("The statement is empty.")
        if not row.tests:
            out.append("It has no test cases.")
        elif not any(t.is_sample for t in row.tests):
            out.append("At least one test has to be a sample.")
        if not (row.reference_source or "").strip():
            out.append("It has no reference solution.")
        elif row.verified_at is None:
            out.append("Run the reference against your tests before sending it.")
    elif kind == "unit" and not row.lessons:
        out.append("It has no lessons yet.")
    elif kind == "track" and not row.units:
        out.append("It has no units yet.")
    return out


def waiting_on(kind, row):
    out = []
    if kind == "lesson":
        unit = db.session.get(Unit, row.unit_id)
        if unit is None or unit.status != PUBLISHED:
            out.append("its unit")
        if unit is None or unit.track is None or unit.track.status != PUBLISHED:
            out.append("its course")
    elif kind == "unit":
        if row.track is None or row.track.status != PUBLISHED:
            out.append("its course")
    return out
