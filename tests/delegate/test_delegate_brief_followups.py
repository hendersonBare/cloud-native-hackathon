"""Regression: SharedBrief follow-ups are all in the brief's language and capped at 3, talk first."""

from delegate_fixtures import ENC
from test_delegate_exchange import events, run_exchange
from test_delegate_llm import ScriptedLLM

from rapport_common.models import SharedBrief
from rapport_delegate.llm import BriefText, FollowupDraft, FollowupPlan

ENGLISH_PHRASES = ("Review ", " from ", "Attend ", "together", "Follow up")


def briefs(init, resp):
    ava = SharedBrief.model_validate(events(init, "shared_brief")[0].data)
    bo = SharedBrief.model_validate(events(resp, "shared_brief")[0].data)
    return ava, bo


async def test_rule_made_followups_are_in_each_persons_language_and_capped():
    _, init, resp, _, _ = await run_exchange(malicious=False)
    ava, bo = briefs(init, resp)
    assert ava.language == "en" and bo.language == "es"

    assert 1 < len(bo.followups) <= 3
    assert bo.followups[0].followup_id == f"fu-{ENC}-talk"
    for f in bo.followups:  # the follow-ups from Bluefin's own side are no longer left in English
        assert not any(p in f.text for p in ENGLISH_PHRASES), f.text
        assert f.text.startswith(("Asistir juntos a", "Revisar "))

    assert 1 < len(ava.followups) <= 3
    assert ava.followups[0].followup_id == f"fu-{ENC}-talk"
    assert all(f.text.startswith(("Attend ", "Review ")) for f in ava.followups)
    assert len({f.followup_id for f in ava.followups}) == len(ava.followups)  # the talk is not listed twice


async def test_model_made_followups_are_capped_and_never_left_in_english_for_bo():
    plan = FollowupPlan(talk_id=None, followups=[
        FollowupDraft(text="Compare notes", item_id=None, owner="both"),
        FollowupDraft(text="Share the dashboard export", item_id=None, owner="me"),
    ])
    # the model gives no translations: Bo still gets Spanish text, and both briefs have at most 3 follow-ups
    llm = ScriptedLLM(plan=plan, brief=BriefText(summary="Resumen", translations=[]))
    _, init, resp, _, _ = await run_exchange(malicious=False, initiator_kw={"llm": llm}, responder_kw={"llm": llm})
    ava, bo = briefs(init, resp)
    assert len(bo.followups) <= 3 and len(ava.followups) <= 3
    assert bo.followups[0].followup_id == f"fu-{ENC}-talk" and ava.followups[0].followup_id == f"fu-{ENC}-talk"
    for f in bo.followups:
        assert not any(p in f.text for p in ENGLISH_PHRASES + ("Compare notes", "dashboard export")), f.text
