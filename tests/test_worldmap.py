from server.learning import worldmap
from server.models import Track, db


def _track(session):
    return session.execute(
        db.select(Track).order_by(Track.position).limit(1)).scalar_one()


def test_sequential_fallback_when_no_edges(session):
    struct = worldmap._build_structure(_track(session).id, None)
    ids = [u["id"] for u in struct["units"]]
    assert struct["edges"][ids[0]] == set()
    assert all(struct["edges"][ids[i]] == {ids[i - 1]}
               for i in range(1, len(ids)))


def test_clearing_an_area_opens_the_next(session):
    struct = worldmap._build_structure(_track(session).id, None)
    ids = [u["id"] for u in struct["units"]]

    first = worldmap.build(struct, set())
    by_id = {r["id"]: r for r in first["regions"]}
    assert by_id[ids[0]]["state"] == "open"
    assert by_id[ids[1]]["state"] == "locked"

    done = set(struct["units"][0]["lesson_ids"])
    after = {r["id"]: r for r in worldmap.build(struct, done)["regions"]}
    assert after[ids[0]]["state"] == "cleared"
    assert after[ids[1]]["state"] == "open"


def test_a_cycle_does_not_hang_the_map(session):
    struct = {"units": [{"id": 1, "slug": "a", "title": "A", "topic": "",
                         "level": "", "lesson_ids": [1], "lessons": [], "total": 1},
                        {"id": 2, "slug": "b", "title": "B", "topic": "",
                         "level": "", "lesson_ids": [2], "lessons": [], "total": 1}],
              "edges": {1: {2}, 2: {1}}}
    world = worldmap.build(struct, set())
    assert world["acyclic"] is False
    assert len(world["regions"]) == 2


def test_an_empty_unit_never_clears():
    struct = {"units": [{"id": 9, "slug": "e", "title": "E", "topic": "",
                         "level": "", "lesson_ids": [], "lessons": [], "total": 0}],
              "edges": {9: set()}}
    assert worldmap.cleared_ids(struct, set()) == set()
