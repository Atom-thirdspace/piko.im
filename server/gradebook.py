import csv
import io

from datetime import timedelta

from sqlalchemy.orm import aliased

from .models import (PUBLISHED, Assignment, AssignmentItem, ClassroomMember,
                     LessonProgress, Problem, ProblemSolve, SimilarityFlag,
                     Submission, User, _utcnow, db)

STUCK_ATTEMPTS = 4

DONE, LATE, MISSING, OPEN = "done", "late", "missing", "open"
FINISHED = (DONE, LATE)


def roster(classroom, include_staff=False):
    stmt = (db.select(User).join(ClassroomMember,
                                 ClassroomMember.user_id == User.id)
            .where(ClassroomMember.classroom_id == classroom.id,
                   ClassroomMember.removed_at.is_(None))
            .order_by(User.username, User.id))
    if not include_staff:
        stmt = stmt.where(ClassroomMember.role != "ta")
    return db.session.execute(stmt).scalars().all()

def _state(at, due, now):
    if at is not None:
        return LATE if (due is not None and at > due) else DONE
    return MISSING if (due is not None and due < now) else OPEN


def grid(classroom, assignment):
    students = roster(classroom)
    empty = {"students": students, "work": list(assignment.items), "rows": [],
             "done": 0, "late": 0, "possible": 0}
    if not students or not assignment.items:
        return empty

    ids = [u.id for u in students]
    problem_ids = [i.problem_id for i in assignment.items if i.problem_id]
    lesson_ids = [i.lesson_id for i in assignment.items if i.lesson_id]
    due, now = assignment.due_at, _utcnow()

    solved = {}
    if problem_ids:
        solved = {(r.user_id, r.problem_id): r.solved_at
                  for r in db.session.execute(
                      db.select(ProblemSolve.user_id, ProblemSolve.problem_id,
                                ProblemSolve.solved_at)
                      .where(ProblemSolve.user_id.in_(ids),
                             ProblemSolve.problem_id.in_(problem_ids))).all()}
        

    read = {}
    if lesson_ids:
        read = {(r.user_id, r.lesson_id): r.completed_at
                for r in db.session.execute(
                    db.select(LessonProgress.user_id, LessonProgress.lesson_id,
                              LessonProgress.completed_at)
                    .where(LessonProgress.user_id.in_(ids),
                           LessonProgress.lesson_id.in_(lesson_ids))).all()}

    rows, done_total, late_total = [], 0, 0
    for student in students:
        cells, done, late = {}, 0, 0
        for item in assignment.items:
            key = (student.id, item.problem_id or item.lesson_id)
            at = (solved if item.problem_id else read).get(key)
            state = _state(at, due, now)
            cells[item.id] = {"state": state, "at": at,
                              "done": state in FINISHED}
            done += 1 if state in FINISHED else 0
            late += 1 if state == LATE else 0
        done_total += done
        late_total += late
        rows.append({"student": student, "cells": cells, "done": done,
                     "late": late, "total": len(assignment.items),
                     "complete": done == len(assignment.items)})

    return {"students": students, "work": list(assignment.items), "rows": rows,
            "done": done_total, "late": late_total,
            "possible": len(students) * len(assignment.items)}


def _safe(value):
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text

def as_csv(classroom, assignment):
    board = grid(classroom, assignment)
    buf = io.StringIO()
    out = csv.writer(buf, lineterminator="\n")

    work = board["work"]
    out.writerow(["student", "name", "email"]
                 + [_safe(i.title) for i in work]
                 + ["done", "late", "total"])

    for row in board["rows"]:
        student = row["student"]
        out.writerow([_safe(student.username), _safe(student.name),
                      _safe(student.email)]
                     + [row["cells"][i.id]["state"] for i in work]
                     + [row["done"], row["late"], row["total"]])
    return buf.getvalue()


def stuck_csv(classroom, days = 7):
    buf = io.StringIO()
    out = csv.writer(buf, lineterminator="\n")
    out.writerow(["student", "email", "problem", "difficulty", "attempts"])
    for row in stuck(classroom, days=days):
        student, problem = row["student"], row["problem"]
        out.writerow([_safe(student.username if student else ""),
                      _safe(student.email if student else ""),
                      _safe(problem.title if problem else ""),
                      problem.difficulty if problem else "",
                      row["attempts"]])
    return buf.getvalue()

def attempts(classroom, user_id, problem_id, limit=50):
    if user_id not in {u.id for u in roster(classroom, include_staff=True)}:
        return None
    return db.session.execute(
        db.select(Submission)
        .where(Submission.user_id == user_id,
               Submission.problem_id == problem_id)
        .order_by(Submission.created_at.desc()).limit(limit)).scalars().all()


def stuck(classroom, days=7, attempts=STUCK_ATTEMPTS):
    ids = [u.id for u in roster(classroom)]
    if not ids:
        return []
    since = _utcnow() - timedelta(days=days)

    tried = db.session.execute(
        db.select(Submission.user_id, Submission.problem_id,
                  db.func.count().label("n"))
        .where(Submission.user_id.in_(ids), Submission.created_at >= since)
        .group_by(Submission.user_id, Submission.problem_id)
        .having(db.func.count() >= attempts)).all()
    if not tried:
        return []

    won = {(r.user_id, r.problem_id) for r in db.session.execute(
        db.select(ProblemSolve.user_id, ProblemSolve.problem_id)
        .where(ProblemSolve.user_id.in_(ids))).all()}

    people = {u.id: u for u in db.session.execute(
        db.select(User).where(User.id.in_(ids))).scalars()}
    problems = {p.id: p for p in db.session.execute(
        db.select(Problem).where(
             Problem.id.in_([t.problem_id for t in tried]))).scalars()}

    out = [{"student": people.get(t.user_id),
            "problem": problems.get(t.problem_id), "attempts": t.n}
           for t in tried if (t.user_id, t.problem_id) not in won]
    out.sort(key=lambda r: -r["attempts"])
    return out


def similar_pairs(classroom, days=120, limit=50):
    ids = [u.id for u in roster(classroom)]
    if len(ids) < 2:
        return []

    mine, theirs = aliased(Submission), aliased(Submission)
    rows = db.session.execute(
        db.select(SimilarityFlag.id, SimilarityFlag.score,
                  SimilarityFlag.status, SimilarityFlag.created_at,
                  mine.id.label("a_id"), mine.user_id.label("a_user"),
                  theirs.id.label("b_id"), theirs.user_id.label("b_user"),
                  mine.problem_id.label("problem_id"))
        .join(mine, mine.id == SimilarityFlag.submission_id)
        .join(theirs, theirs.id == SimilarityFlag.matched_id)
        .where(mine.user_id.in_(ids), theirs.user_id.in_(ids),
               mine.user_id != theirs.user_id,
               SimilarityFlag.created_at >= _utcnow() - timedelta(days=days))
        .order_by(SimilarityFlag.score.desc()).limit(limit * 2)).all()
    if not rows:
        return []

    # One flag per direction gets written, so collapse (a,b) and (b,a).
    seen, keep = set(), []
    for row in rows:
        pair = (min(row.a_user, row.b_user), max(row.a_user, row.b_user),
                row.problem_id)
        if pair in seen:
            continue
        seen.add(pair)
        keep.append(row)
        if len(keep) >= limit:
            break

    # Batched on purpose: lazy-loading .user per row is a round trip each, and
    # the trip to the database is the slowest thing on the page.
    people = {u.id: u for u in db.session.execute(
        db.select(User).where(User.id.in_(ids))).scalars()}
    problems = {p.id: p for p in db.session.execute(
        db.select(Problem).where(
            Problem.id.in_({r.problem_id for r in keep}))).scalars()}

    return [{"flag_id": r.id, "score": r.score, "status": r.status,
             "created_at": r.created_at,
             "a": people.get(r.a_user), "b": people.get(r.b_user),
             "a_submission": r.a_id, "b_submission": r.b_id,
             "problem": problems.get(r.problem_id)} for r in keep]


def assign_unit(assignment, unit):
    """Add a whole unit's worth of work in one go.

    A lesson that wraps a problem contributes the problem, not the lesson:
    that is the gradeable artefact, and counting both would make every row
    read half-finished.
    """
    have_problems = {i.problem_id for i in assignment.items if i.problem_id}
    have_lessons = {i.lesson_id for i in assignment.items if i.lesson_id}
    position = max([i.position for i in assignment.items], default=-1)

    added = 0
    for lesson in unit.lessons:
        if lesson.status != PUBLISHED:
            continue
        if lesson.problem_id:
            problem = lesson.problem
            if problem is None or problem.status != PUBLISHED:
                continue
            if lesson.problem_id in have_problems:
                continue
            have_problems.add(lesson.problem_id)
            position += 1
            db.session.add(AssignmentItem(assignment_id=assignment.id,
                                          position=position,
                                          problem_id=lesson.problem_id))
        else:
            if lesson.id in have_lessons:
                continue
            have_lessons.add(lesson.id)
            position += 1
            db.session.add(AssignmentItem(assignment_id=assignment.id,
                                          position=position,
                                          lesson_id=lesson.id))
        added += 1

    if added:
        db.session.commit()
    return added


def clone_assignment(assignment, target, user):
    """Copy an assignment into another classroom.

    The due date is deliberately dropped. A deadline carried into next term is
    always wrong, and a silently-overdue assignment is worse than none.
    """
    row = Assignment(classroom_id=target.id, title=assignment.title[:200],
                     note_md=assignment.note_md, due_at=None,
                     created_by_id=user.id)
    db.session.add(row)
    db.session.flush()

    for item in assignment.items:
        db.session.add(AssignmentItem(assignment_id=row.id,
                                      position=item.position,
                                      problem_id=item.problem_id,
                                      lesson_id=item.lesson_id))
    db.session.commit()
    return row