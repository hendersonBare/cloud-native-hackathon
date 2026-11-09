"""The spec's decision rule (§5.4), score conversion, centroids and pool narrowing."""

from __future__ import annotations

import math

import pytest

from rapport_speakers.config import POOL_BOOST, POOL_FILTER, POOL_OFF, Settings, Thresholds
from rapport_speakers.decide import apply_pool, decide, decide_with, top_two
from rapport_speakers.vectors import cosine_from_score, dot, es_score, normalize, recompute_centroid


def hit(person_id: str, cosine: float) -> dict:
    return {"_score": es_score(cosine), "_source": {"person_id": person_id, "name": person_id.title()}}


@pytest.mark.parametrize(
    ("cosines", "speech", "expected"),
    [
        ([0.80, 0.20], 10.0, ("identified", "a", 0.80)),
        ([0.80], 10.0, ("identified", "a", 0.80)),  # one hit: second counts as -1
        ([0.55, 0.45], 10.0, ("identified", "a", 0.55)),  # exactly at T_ACCEPT and MARGIN
        ([0.70, 0.65], 10.0, ("ambiguous", "a", 0.70)),  # accepted score, margin too small
        ([0.54, 0.10], 10.0, ("unknown", None, 0.54)),  # below T_ACCEPT
        ([0.90, 0.10], 2.9, ("unknown", None, None)),  # too little speech
        ([], 10.0, ("unknown", None, None)),  # no voiceprints
    ],
)
def test_decide_matches_the_spec(cosines, speech, expected):
    hits = [hit(pid, c) for pid, c in zip("abc", cosines)]
    status, pid, top = decide(hits, speech)
    assert (status, pid) == expected[:2]
    if expected[2] is None:
        assert top is None
    else:
        assert top == pytest.approx(expected[2])


def test_decide_with_uses_configured_thresholds():
    hits = [hit("a", 0.60), hit("b", 0.10)]
    assert decide_with(hits, 10, Thresholds(t_accept=0.65))[0] == "unknown"
    assert decide_with(hits, 10, Thresholds(margin=0.6))[0] == "ambiguous"
    assert decide_with(hits, 1, Thresholds(min_speech_s=0.5))[0] == "identified"


def test_score_conversion_round_trips():
    for cos in (-1.0, -0.3, 0.0, 0.55, 1.0):
        assert cosine_from_score(es_score(cos)) == pytest.approx(cos)
    assert es_score(1.0) == 1.0 and es_score(-1.0) == 0.0


def test_centroid_is_the_normalized_mean_of_normalized_samples():
    a, b = [3.0, 0.0, 0.0], [0.0, 0.5, 0.0]  # different lengths must not weigh differently
    c = recompute_centroid([a, b])
    assert c == pytest.approx([math.sqrt(0.5), math.sqrt(0.5), 0.0])
    assert dot(c, c) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        recompute_centroid([])
    with pytest.raises(ValueError):
        normalize([0.0, 0.0])


def test_pool_boost_reorders_toward_scheduled_speakers_without_mutating_hits():
    hits = [hit("guest", 0.62), hit("speaker", 0.60)]
    boosted = apply_pool(hits, ["speaker"], POOL_BOOST, 0.05)
    assert [h["_source"]["person_id"] for h in boosted] == ["speaker", "guest"]
    assert cosine_from_score(boosted[0]["_score"]) == pytest.approx(0.65)
    assert hits[0]["_source"]["person_id"] == "guest" and cosine_from_score(hits[1]["_score"]) == pytest.approx(0.60)


def test_pool_boost_cannot_name_a_cross_session_speaker_wrongly():
    """A Q&A question from someone enrolled elsewhere stays theirs: the bonus is small next to a real match."""
    hits = [hit("other-speaker", 0.72), hit("scheduled", 0.10)]
    status, pid, _ = decide(apply_pool(hits, ["scheduled"], POOL_BOOST, 0.05), 9.0)
    assert (status, pid) == ("identified", "other-speaker")


@pytest.mark.parametrize("mode", [POOL_FILTER, POOL_OFF])
def test_pool_is_a_no_op_outside_boost_mode(mode):
    hits = [hit("guest", 0.62), hit("speaker", 0.60)]
    assert apply_pool(hits, ["speaker"], mode, 0.05) == hits


def test_top_two_reports_raw_cosines_for_review():
    (best, best_s), (second, second_s) = top_two([hit("a", 0.4), hit("b", 0.2)])
    assert (best, second) == ("a", "b") and best_s == pytest.approx(0.4) and second_s == pytest.approx(0.2)
    assert top_two([]) == ((None, None), (None, None))


def test_settings_from_env_validates_pool_mode_and_picks_the_store():
    assert Settings.from_env({}).store == "memory"
    other_key = {"ES_URL": "https://es.example.invalid", "ES_API_KEY": "placeholder"}
    assert Settings.from_env(other_key).store == "memory"  # another component's key never switches to ES
    assert Settings.from_env({**other_key, "SPEAKERS_STORE": "es"}).es_api_key == "placeholder"
    env = {"ES_URL": "https://es.example.invalid", "SPEAKERS_ES_API_KEY": "placeholder",
           "SPEAKERS_POOL_MODE": "filter", "SPEAKERS_T_ACCEPT": "0.6"}
    s = Settings.from_env(env)
    assert (s.store, s.pool_mode, s.thresholds.t_accept) == ("es", "filter", 0.6)
    with pytest.raises(ValueError):
        Settings.from_env({"SPEAKERS_POOL_MODE": "maybe"})


@pytest.mark.parametrize("env", [
    {"SPEAKERS_T_ACCEPT": "nan"}, {"SPEAKERS_T_ACCEPT": "1.5"}, {"SPEAKERS_MARGIN": "-0.1"},
    {"SPEAKERS_MIN_SPEECH_S": "inf"}, {"SPEAKERS_POOL_BONUS": "0.9"}, {"SPEAKERS_POOL_BONUS": "nan"},
])
def test_settings_reject_nan_and_out_of_range_thresholds(env):
    """A NaN threshold would make every comparison False and silently label every speaker unknown."""
    with pytest.raises(ValueError):
        Settings.from_env(env)
