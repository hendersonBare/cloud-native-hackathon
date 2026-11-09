from rapport_common.interfaces import InMemoryStore
from rapport_common.models import MemoryRecord
from rapport_common.names import internal_index, shareable_index


def rec(memory_id, share_level, tags, text="eBPF tracing for Kubernetes"):
    return MemoryRecord(
        memory_id=memory_id, org_id="acme", share_level=share_level, kind="document", title=memory_id,
        text=text, summary=text[:100], tags=tags, source={"type": "seed"},
    )


def test_fake_respects_index_boundary():
    store = InMemoryStore([
        rec("pricing", "partner", ["pricing"]),
        rec("discounts", "internal", ["pricing"]),
        rec("case", "public", ["ebpf"]),
    ])
    shareable_only = [shareable_index("acme")]
    ids = {r.memory_id for r in store.search("pricing", indices=shareable_only, tags=["pricing"])}
    assert ids == {"pricing"}  # the internal discount doc is invisible to a delegate
    assert store.get("discounts", indices=shareable_only) is None
    assert store.get("discounts", indices=[internal_index("acme")]) is not None
    assert store.search("ebpf kubernetes", indices=shareable_only)[0].memory_id in {"case", "pricing"}
