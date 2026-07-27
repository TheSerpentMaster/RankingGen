from pathlib import Path

from app import build_ranking_beats


def test_build_ranking_beats_creates_five_entries():
    beats = build_ranking_beats("best sci-fi movies")
    assert len(beats) == 5
    assert all("rank" in beat and "title" in beat for beat in beats)
    assert beats[0]["title"]
