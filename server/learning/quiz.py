from ..models import LessonQuestion, db
from .catalog import QuizQuestion, quiz_for as _catalog_quiz

def _adapt(row):
    correct = next((c for c in row.choices if c.is_correct), None)
    return QuizQuestion(
        id="q%d" % row.id,
        prompt=row.prompt,
        choices=tuple(("c%d" % c.id, c.text) for c in row.choices),
        answer=("c%d" % correct.id) if correct else "",
    )

def rows_for(lesson_id):
    return db.session.execute(
        db.select(LessonQuestion).where(LessonQuestion.lesson_id == lesson_id)
        .order_by(LessonQuestion.position, LessonQuestion.id)).scalars().all()


def questions_for(lesson, track, unit):
    rows = rows_for(lesson.id)
    if rows:
        return tuple(_adapt(r) for r in rows)
    return _catalog_quiz(track.slug, unit.slug, lesson.slug)