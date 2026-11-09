"""The responder's HTTP surface: health, validation (422), identity (403), ordering (409), replay, 500 handling."""

import httpx
from delegate_fixtures import ENC, Side, make_config

from rapport_common.models import Card, ExchangeMessage
from rapport_delegate.responder import create_app

CARD = Card(persona_id="acme.ava", name="Ava", title="Solutions Engineer", org_id="acme", org_name="Acme Observability",
            headline="h", interests=["ebpf"], looking_for=[])


def hello(**over) -> dict:
    base = dict(encounter_id=ENC, round=1, type="hello", from_org="acme", from_persona="acme.ava", to_org="bluefin",
                to_persona="bluefin.bo", card=CARD)
    base.update(over)
    return ExchangeMessage(**base).model_dump(mode="json")


async def client_for(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://peer.test")


def new_app(**kw):
    side = Side(make_config("responder"), **kw)
    return create_app(side.cfg, **side.kwargs()), side


async def test_healthz():
    app, _ = new_app()
    async with await client_for(app) as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200 and resp.json() == {"ok": True}


async def test_invalid_exchange_message_is_422():
    app, side = new_app()
    async with await client_for(app) as client:
        for body in (
            {"round": 1},  # missing fields
            hello() | {"card": None},  # hello without a card
            hello() | {"round": 2},  # round/type mismatch
            hello() | {"surprise": True},  # extra fields are forbidden
        ):
            resp = await client.post("/v1/exchange", json=body)
            assert resp.status_code == 422, body
            assert "detail" in resp.json()
        resp = await client.post("/v1/exchange", content=b"not json", headers={"content-type": "application/json"})
        assert resp.status_code == 422
    assert not side.sink.events  # nothing was started or reported for invalid input


async def test_message_for_somebody_else_is_403():
    app, _ = new_app()
    async with await client_for(app) as client:
        for body in (
            hello(encounter_id="enc-other"),
            hello(from_org="globex", from_persona="globex.eve"),
            hello(to_persona="bluefin.kai"),
            hello(card=CARD.model_copy(update={"persona_id": "acme.sam"})),
        ):
            resp = await client.post("/v1/exchange", json=body)
            assert resp.status_code == 403, body
            assert "detail" in resp.json()


async def test_rounds_must_come_in_order_and_a_repeat_replays_the_reply():
    app, _ = new_app()
    async with app.router.lifespan_context(app):
        async with await client_for(app) as client:
            skipped = hello() | {"round": 2, "type": "offers_asks", "card": None}
            assert (await client.post("/v1/exchange", json=skipped)).status_code == 409
            first = await client.post("/v1/exchange", json=hello())
            again = await client.post("/v1/exchange", json=hello())
    assert first.status_code == 200 and first.json()["card"]["persona_id"] == "bluefin.bo"
    assert again.json() == first.json()


async def test_internal_failure_is_a_500_with_detail_and_reports_failed():
    class Boom:
        def get(self, *a, **k):
            raise RuntimeError("secret-internal-detail")

        def search(self, *a, **k):
            raise RuntimeError("secret-internal-detail")

        def write(self, *a, **k):
            return 0

    side = Side(make_config("responder"))
    side.store = Boom()
    finished = []
    app = create_app(side.cfg, on_finished=finished.append, **side.kwargs() | {"store": side.store})
    async with app.router.lifespan_context(app):
        async with await client_for(app) as client:
            resp = await client.post("/v1/exchange", json=hello())
    assert resp.status_code == 500 and resp.json() == {"detail": "delegate failed"}
    assert finished == [False]
    statuses = [e.data["status"] for e in side.sink.events if e.type == "delegate_status"]
    assert statuses == ["started", "failed"]
    assert "secret-internal-detail" not in str([e.model_dump() for e in side.sink.events])


async def test_openapi_documents_every_route_with_tags_and_response_models():
    app, _ = new_app()
    spec = app.openapi()
    for path, ops in spec["paths"].items():
        for op in ops.values():
            assert op["tags"], path
            assert "200" in op["responses"] and "content" in op["responses"]["200"], path
    assert "422" in spec["paths"]["/v1/exchange"]["post"]["responses"]
