from datetime import timedelta

from .models import (Assignment, AssignmentItem, ClassroomMember,
                     LessonProgress, ProblemSolve, Submission, User, _utcnow, db)

STUCK_ATTEMPTS = 4

def roster(classroom):
    return db.session.execute(
        db.select(User).join(ClassroomMember,
                             ClassroomMember.user_id == User.id)
        .where(ClassroomMember.classroom_id == classroom.id,
               ClassroomMember.removed_at.is_(None))
        .order_by(User.username, User.id)).scalars().all()


def grid(classroom, assignment):
    students = roster(classroom)
    if not students or not assignment.items:
        # "work", not "items": Jinja resolves a dict's .items to the method,
        # so a key by that name is unreachable from a template.
        return {"students": students, "work": list(assignment.items),
                "rows": [], "done": 0, "possible": 0}

    ids = [u.id for u in students]
    problem_ids = [i.problem_id for i in assignment.items if i.problem_id]
    lesson_ids = [i.lesson_id for i in assignment.items if i.lesson_id]

    solved = set()
    if problem_ids:
        solved = {(r.user_id, r.problem_id) for r in db.session.execute(
            db.select(ProblemSolve.user_id, ProblemSolve.problem_id)
            .where(ProblemSolve.user_id.in_(ids),
                   ProblemSolve.problem_id.in_(problem_ids))).all()}

    read = set()
    if lesson_ids:
        read = {(r.user_id, r.lesson_id) for r in db.session.execute(
            db.select(LessonProgress.user_id, LessonProgress.lesson_id)
            .where(LessonProgress.user_id.in_(ids),
                   LessonProgress.lesson_id.in_(lesson_ids))).all()}

    rows, done_total = [], 0
    for student in students:
        cells, done = {}, 0
        for item in assignment.items:
            if item.problem_id:
                ok = (student.id, item.problem_id) in solved
            else:
                ok = (student.id, item.lesson_id) in read
            cells[item.id] = ok
            done += 1 if ok else 0
        done_total += done
        rows.append({"student": student, "cells": cells, "done": done,
                     "total": len(assignment.items),
                     "complete": done == len(assignment.items)})

    return {"students": students, "work": list(assignment.items),
            "rows": rows, "done": done_total,
            "possible": len(students) * len(assignment.items)}


def stuck(classroom, days = 7, attempts=STUCK_ATTEMPTS):
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
    from .models import Problem
    problems = {p.id: p for p in db.session.execute(
        db.select(Problem).where(
            Problem.id.in_([t.problem_id for t in tried]))).scalars()}

    out = [{"student": people.get(t.user_id), "problem": problems.get(t.problem_id),
            "attempts": t.n}
           for t in tried if (t.user_id, t.problem_id) not in won]
    out.sort(key=lambda r: -r["attempts"])
    return out