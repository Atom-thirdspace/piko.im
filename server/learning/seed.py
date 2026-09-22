"""Push the catalog in catalog.py into the database. Idempotent: safe to re-run."""

from ..models import Lesson, Problem, Track, Unit, db
from .catalog import TRACKS

def _problem_ids():
    rows = db.session.execute(db.select(Problem.slug, Problem.id)).all()
    return {slug: pid for slug, pid in rows}

def seed_catalog():
    problems = _problem_ids()
    counts = {"tracks": 0, "units": 0, "lessons": 0, "unlinked": []}

    for t_pos, track_def in enumerate(TRACKS):
        track = db.session.execute(
            db.select(Track).filter_by(slug=track_def.slug)
        ).scalar_one_or_none()
        if track is None:
            track = Track(slug=track_def.slug)
            db.session.add(track)
            counts["tracks"] += 1
        track.title = track_def.title
        track.description = track_def.description
        track.position = t_pos
        db.session.flush()

        for u_pos, unit_def in enumerate(track_def.units):
            unit = db.session.execute(
                db.select(Unit).filter_by(track_id=track.id, slug=unit_def.slug)
            ).scalar_one_or_none()
            if unit is None:
                unit = Unit(track_id=track.id, slug=unit_def.slug)
                db.session.add(unit)
                counts["units"] += 1
            unit.title = unit_def.title
            unit.level = unit_def.level
            unit.topic = unit_def.topic
            unit.position = u_pos
            db.session.flush()

            for l_pos, lesson_def in enumerate(unit_def.lessons):
                lesson = db.session.execute(
                    db.select(Lesson).filter_by(unit_id=unit.id, slug=lesson_def.slug)
                ).scalar_one_or_none()
                if lesson is None:
                    lesson = Lesson(unit_id=unit.id, slug=lesson_def.slug)
                    db.session.add(lesson)
                    counts["lessons"] += 1
                lesson.title = lesson_def.title
                lesson.kind = lesson_def.kind
                lesson.xp = lesson_def.xp
                lesson.body_md = (lesson_def.body or "").strip()
                lesson.position = l_pos
                if lesson_def.problem_slug:
                    # A code lesson whose problem isn't seeded yet stays unlinked
                    # rather than blowing up the seed; re-running links it later.
                    lesson.problem_id = problems.get(lesson_def.problem_slug)
                    if lesson.problem_id is None:
                        counts["unlinked"].append(lesson_def.problem_slug)

    db.session.commit()
    return counts

def register_cli(app):
    @app.cli.command("seed-catalog")
    def _seed_catalog_command():
        counts = seed_catalog()
        print("added %d tracks, %d units, %d lessons"
              % (counts["tracks"], counts["units"], counts["lessons"]))
        if counts["unlinked"]:
            print("no problem row yet for: %s" % ", ".join(sorted(set(counts["unlinked"]))))
