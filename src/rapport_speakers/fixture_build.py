"""Generate `data/fixtures.json`: synthetic diarized transcripts and voice embeddings for the seed talks.

    PYTHONPATH=src uv run python -m rapport_speakers.fixture_build

Everything is fictional. Each person gets a random 192-dim "voice"; a cluster embedding is that voice plus
noise whose size models the channel (podium mic 0.35, chair 0.5, handheld Q&A mic 0.85). Unknown attendees
get fresh random voices. Deterministic (fixed seed), so the committed file only changes when this does.

Scenarios the fixtures cover (asserted below, so a regenerated file keeps them):
- every consenting talk speaker is auto-enrolled from the schedule (§5.3);
- `talk-search-ops-data` fails the enrollment guards (a co-presenter talks about as much as Ken);
- `talk-finops-showback`: the speaker did not consent, so the talk stays "Unknown speaker";
- the keynote is never auto-enrolled (only `talk` sessions are);
- Q&A questions from speakers of *later* sessions are identified (two-pass order, §5.2);
- one noisy handheld-mic question sits between two enrolled voices and comes out `ambiguous`;
- a "Thank you!" over applause has no clean speech and stays `unknown`;
- the three room chairs and the keynote speaker have registration clips for later enrollment and relabel (§5.5).
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

from rapport_memory.seed_talks import _TALKS

from .config import CONFERENCE_ID_DEFAULT, EMBEDDING_DIMS, MODEL_ID_DEFAULT
from .fixtures import FIXTURES_PATH
from .schedule import person_id_for, recording_uri, scheduled_speakers
from .vectors import dot, normalize

SEED = 20261109
CONSENT_AT = "2026-11-01T17:00:00+00:00"  # speaker agreement / registration checkbox (synthetic)
NO_CONSENT = {"spk-rosa"}
CHAIRS = {"Room A": ("chair-noor", "Noor"), "Room B": ("chair-felix", "Felix"), "Room C": ("chair-ines", "Ines")}
REGISTERED = ["chair-noor", "chair-felix", "chair-ines", "spk-marcus"]
NOISE = {"speaker": 0.35, "chair": 0.5, "qa": 0.85, "co": 0.4, "registration": 0.4, "attendee": 0.3}

# Hand-written transcripts: (start_s, duration_s, who, text). who is "chair", "speaker", "co" (co-presenter),
# "q:<person_id>" (an enrolled speaker asking a question), "q:unknown-<x>" (an attendee who never enrolled) or
# "q:mix:<a>+<b>" (a handheld-mic voice halfway between two enrolled speakers). A trailing "!" on who marks
# overlapped speech.
TRANSCRIPTS: dict[str, list[tuple[float, float, str, str]]] = {
    "talk-ebpf-zero-code": [
        (20, 18, "speaker", "eBPF lets us run small, verified programs inside the Linux kernel, so we can watch "
                            "every request without touching application code."),
        (38.5, 16, "speaker", "That is what zero-code tracing means: no SDK, no sidecar and no redeploy of your "
                              "services."),
        (55, 20, "speaker", "On Kubernetes we run one agent per node as a DaemonSet, and it attaches eBPF probes "
                            "to the network and TLS functions of every pod."),
        (300, 22, "speaker", "From those probes we rebuild HTTP and gRPC requests, measure latency, and stitch "
                             "them into traces across services."),
        (322.5, 18, "speaker", "The trace context comes from the headers on the wire, so spans from eBPF line up "
                               "with spans from your existing OpenTelemetry SDKs."),
        (600, 25, "speaker", "Now the live demo. This sample shop has six microservices and none of them is "
                             "instrumented."),
        (625.5, 20, "speaker", "Within a minute of installing the agent we see the full call graph and the slow "
                               "checkout call, all from eBPF."),
        (1100, 22, "speaker", "Where eBPF cannot help: it does not see inside a process, so business attributes "
                              "like a cart ID still need a line of SDK code."),
        (1122.5, 18, "speaker", "Kernel versions matter too. You want a recent kernel with BTF, which every major "
                                "managed Kubernetes now ships."),
        (1380, 15, "speaker", "So start with eBPF for coverage on day one, and add SDK spans where you need detail."),
        (1450, 9, "q:kestrel.mia", "How much CPU overhead does eBPF tracing add on small edge nodes, like the "
                                   "computers on our warehouse robots?"),
        (1460, 30, "speaker", "On small nodes we measured about one to two percent CPU with the default probes. The "
                              "cost grows with the number of probes, so start with HTTP and DNS and add more once "
                              "you know your budget."),
        (1493, 8, "q:lumenly.priya", "Can the same eBPF data show which services sit idle, so we can cut the "
                                     "cloud bill?"),
        (1502, 20, "speaker", "Yes. Request counts per service fall out of the same probes, and idle services stand "
                              "out within a day."),
        (1525, 7, "q:unknown-tls", "Does zero-code tracing still work when the traffic is encrypted with TLS?"),
        (1533, 20, "speaker", "Mostly. We hook the TLS library before encryption, so we see the request, but "
                              "statically linked binaries need extra probes."),
        (1556, 6, "q:mix:spk-arjun+harborline.lena", "Does the agent export OpenTelemetry spans directly, or do we "
                                                     "still need a collector?"),
        (1563, 15, "speaker", "It exports OTLP directly, so any OpenTelemetry collector or backend works unchanged."),
        (1580, 1.5, "q:unknown-thanks!", "Thank you!"),
    ],
    "talk-ebpf-cost": [
        (18, 20, "speaker", "Our cloud bill grew forty percent in a year, and nobody could say which services were "
                            "responsible."),
        (38.5, 22, "speaker", "We used eBPF to count requests and bytes per pod at the kernel, which gave us a cost "
                              "map without changing a single service."),
        (400, 20, "speaker", "The first surprise was idle capacity: a third of our deployments handled almost no "
                             "traffic outside business hours."),
        (420.5, 18, "speaker", "The second was chatty services calling each other thousands of times per page "
                               "view."),
        (800, 22, "speaker", "Measurement has a cost too, so we kept the eBPF probes to a sampled set and stayed "
                             "under half a percent of CPU."),
        (1200, 20, "speaker", "In six months we cut spend by twenty-eight percent, and the savings held because the "
                              "dashboards stayed on."),
        (1450, 10, "q:spk-nadia", "How did you prove the savings to finance before the invoices came in?"),
        (1461, 20, "speaker", "We priced each idle replica at the on-demand rate and showed finance the forecast "
                              "next to the actual bill every month."),
        (1483, 9, "q:spk-dev", "Did older kernel versions on some nodes block the eBPF rollout?"),
        (1493, 15, "speaker", "Two node pools were too old, so we upgraded them first. Everything since then has "
                              "had BTF."),
    ],
    "talk-ebpf-edge": [
        (20, 20, "speaker", "Our warehouse robots each run a tiny Kubernetes cluster on a fanless computer, so "
                            "every percent of CPU matters."),
        (40.5, 22, "speaker", "We set an overhead budget of one percent for observability, and eBPF was the only "
                              "tracing approach that fit."),
        (500, 20, "speaker", "Networks on a warehouse floor are flaky, so the agent buffers traces locally and ships "
                             "them when the robot docks."),
        (900, 22, "speaker", "The best bug we found was a retry storm between the navigation and lidar services "
                             "that only happened near the loading bays."),
        (1300, 15, "speaker", "If you run eBPF at the edge, pin your kernel version across the fleet, or your "
                              "probes will break one robot at a time."),
        (1440, 8, "q:spk-dev", "What did you have to turn off to stay under the one percent budget?"),
        (1449, 18, "speaker", "We dropped DNS tracing and sampled HTTP at ten percent on each robot. Errors are "
                              "always kept."),
        (1470, 7, "q:unknown-robots", "How many robots run this today?"),
        (1478, 10, "speaker", "About two hundred robots across four warehouses."),
    ],
    "talk-otel-regulated": [
        (20, 20, "speaker", "At a bank, every new telemetry signal goes through a compliance review before it "
                            "leaves the building."),
        (40.5, 20, "speaker", "We kept data residency simple: all telemetry stays in one region, and the collector "
                              "redacts account numbers before export."),
        (600, 22, "speaker", "Traces were the easiest to approve because they carry timings and service names, "
                             "not customer data."),
        (1000, 18, "speaker", "Logs were the hardest. We only ship structured logs with an allow-list of fields."),
        (1300, 15, "speaker", "The result: incident time dropped by a third in the first quarter."),
        (1450, 9, "q:spk-arjun", "Did you run the collector as a central gateway for the redaction?"),
        (1460, 15, "speaker", "Yes, one gateway pool per region, so the redaction rules live in one place that "
                              "auditors can read."),
    ],
    "talk-ai-agents-guardrails": [
        (20, 20, "speaker", "An agent that acts for a person should see only the data that person would share."),
        (40.5, 22, "speaker", "We give each agent a scoped key, check every outbound item against a policy engine, "
                              "and fail closed when the policy service is down."),
        (700, 22, "speaker", "Text from another company's agent is untrusted input. It goes into the prompt as "
                             "data, never as instructions."),
        (1200, 15, "speaker", "Keep an audit trail of every decision, so a person can see why their agent said "
                              "no."),
        (1450, 9, "q:spk-wei", "How do you stop prompt injection when two agents negotiate with each other?"),
        (1460, 18, "speaker", "Treat the other agent's message as data in a delimited block, and only let the model "
                              "pick from IDs you already know."),
    ],
    "talk-search-ops-data": [
        (20, 20, "speaker", "Our operations team searches shipment records all day, and keyword search alone kept "
                            "missing the right record."),
        (45, 45, "co", "I run the data platform, so I will show how we index the records. Every shipment event "
                       "becomes one document with the carrier, the route and free-text notes."),
        (110, 40, "co", "We added a semantic field next to the text field and merge both result lists with "
                        "reciprocal rank fusion."),
        (600, 22, "speaker", "Here is the difference: a search for frozen goods stuck at the border now finds notes "
                             "that say refrigerated cargo held at customs."),
        (622.5, 30, "speaker", "Nobody had to learn a query language. People type the question the way they would "
                               "ask a colleague."),
        (900, 30, "co", "Filters still matter. We always filter on the customer and the date range first, and then "
                        "rank."),
        (1300, 15, "speaker", "Hybrid search cut our time to the right record from minutes to seconds."),
    ],
    "talk-inclusive-confs": [
        (20, 20, "speaker", "Accessible events start with the schedule: fewer parallel tracks, longer breaks and a "
                            "quiet room people can find."),
        (40.5, 22, "speaker", "Live captions help everyone, not only people who are deaf or hard of hearing. They "
                              "also help anyone listening in a second language."),
        (700, 18, "speaker", "Publish talk recordings with captions and timestamps, so people can jump to the part "
                             "they need."),
        (1200, 15, "speaker", "Ask attendees what would help them before the event, not after."),
        (1450, 6, "q:unknown-captions", "Do you caption the questions from the audience too?"),
        (1457, 14, "speaker", "We do. The moderator repeats each question into the microphone, so the captions pick "
                              "it up."),
    ],
    "talk-hipaa-k8s": [
        (20, 22, "speaker", "Auditors ask the same four things about a cluster that handles health data: logging, "
                            "encryption, access reviews and vendor paperwork."),
        (600, 20, "speaker", "Turn on Kubernetes audit logging on day one and keep the logs for six years, because "
                             "that is what they will ask for."),
        (1100, 20, "speaker", "Encrypt secrets at rest with a managed key, and show the key rotation history in the "
                              "review."),
        (1350, 15, "speaker", "Hospital security teams will also ask every vendor for a completed security "
                              "questionnaire before a pilot."),
    ],
}


def _sentences(text: str) -> list[str]:
    parts = [p.strip() for p in text.replace("? ", "?|").replace(". ", ".|").split("|")]
    return [p if p.endswith((".", "?", "!")) else f"{p}." for p in parts if p]


def _auto_transcript(summary: str, text: str) -> list[tuple[float, float, str, str]]:
    """Talks without a hand-written transcript: the speaker reads the agenda summary and description."""
    turns, at = [], 20.0
    for sentence in _sentences(summary) + _sentences(text):
        turns.append((at, 35.0, "speaker", sentence))
        at += 300.0
    return turns


class _Voices:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.voices: dict[str, list[float]] = {}

    def unit(self) -> list[float]:
        return normalize([self.rng.gauss(0.0, 1.0) for _ in range(EMBEDDING_DIMS)])

    def voice(self, key: str) -> list[float]:
        if key not in self.voices:
            self.voices[key] = self.unit()
        return self.voices[key]

    def sample(self, keys: list[str], noise: float) -> list[float]:
        n = self.unit()
        base = [sum(self.voice(k)[i] for k in keys) for i in range(EMBEDDING_DIMS)]
        return normalize([b + noise * x for b, x in zip(base, n)])


def _rounded(v: list[float]) -> list[float]:
    return [round(x, 6) for x in v]


def build() -> dict:
    rng = random.Random(SEED)
    voices = _Voices(rng)
    people = []
    for pid, name, affiliation in scheduled_speakers():
        people.append({"person_id": pid, "name": name, "affiliation": affiliation, "role": "speaker",
                       "consent_granted_at": None if pid in NO_CONSENT else CONSENT_AT})
    for room, (pid, name) in sorted(CHAIRS.items()):
        people.append({"person_id": pid, "name": name, "affiliation": f"Session chair, {room}", "role": "chair",
                       "consent_granted_at": CONSENT_AT})

    recordings = []
    talk_embeddings: dict[str, list[float]] = {}
    for mid, title, _start, room, _track, speakers, about, _tags, summary, text in _TALKS:
        speaker_id = person_id_for(speakers[0], about)
        chair_id, _ = CHAIRS[room]
        intro = (5.0, 12.0, "chair", f"Welcome to {room}. Our next speaker is {speakers[0]}, with {title}.")
        turns = [intro] + TRANSCRIPTS.get(mid, _auto_transcript(summary, text))
        labels: dict[str, str] = {}
        segments, clusters = [], []
        for start, dur, who, line in turns:
            overlap = who.endswith("!")
            who = who.rstrip("!")
            if who not in labels:
                labels[who] = f"SPEAKER_{len(labels):02d}"
                if who == "chair":
                    keys, noise, truth = [chair_id], NOISE["chair"], chair_id
                elif who == "speaker":
                    keys, noise, truth = [speaker_id], NOISE["speaker"], speaker_id
                elif who == "co":
                    keys, noise, truth = [f"co:{mid}"], NOISE["co"], None
                elif who.startswith("q:mix:"):
                    a, b = who[len("q:mix:"):].split("+")
                    keys, noise, truth = [a, b], NOISE["qa"] * 0.7, a
                elif who.startswith("q:unknown-"):
                    keys, noise, truth = [who], NOISE["attendee"], None
                else:
                    pid = who[2:]
                    keys, noise, truth = [pid], NOISE["qa"], pid
                emb = voices.sample(keys, noise)
                if who == "speaker":
                    talk_embeddings[speaker_id] = emb
                clusters.append({"label": labels[who], "truth": truth, "embedding": _rounded(emb)})
            segments.append({"start_s": start, "end_s": round(start + dur, 2), "label": labels[who], "text": line,
                             "overlap": overlap})
        recordings.append({"session_id": mid, "recording_uri": recording_uri(mid), "clusters": clusters,
                           "segments": segments})

    clips = []
    for pid in REGISTERED:
        if not any(p["person_id"] == pid for p in people):
            raise ValueError(f"registration clip for unknown person {pid}")
        clips.append({"person_id": pid, "duration_s": 20.0, "audio_uri": f"registration/{pid}.wav",
                      "embedding": _rounded(voices.sample([pid], NOISE["registration"]))})

    _check_scenarios(recordings, talk_embeddings)
    return {
        "_comment": "SYNTHETIC test data for speaker identification. Fictional people, random-noise voices. "
                    "Generated by `python -m rapport_speakers.fixture_build`; do not edit by hand.",
        "conference_id": CONFERENCE_ID_DEFAULT,
        "model_id": MODEL_ID_DEFAULT,
        "dims": EMBEDDING_DIMS,
        "people": people,
        "registration_clips": clips,
        "recordings": recordings,
    }


def _check_scenarios(recordings: list[dict], centroids: dict[str, list[float]]) -> None:
    """The mixed handheld-mic voice must be ambiguous between its two speakers with the default thresholds."""
    for rec in recordings:
        for c in rec["clusters"]:
            if rec["session_id"] == "talk-ebpf-zero-code" and c["truth"] == "spk-arjun":
                emb = normalize(c["embedding"])
                cos = sorted((dot(emb, normalize(v)) for v in centroids.values()), reverse=True)
                if not (cos[0] >= 0.55 and cos[0] - cos[1] < 0.10):
                    raise AssertionError(f"mixed voice is not ambiguous: top={cos[0]:.3f} second={cos[1]:.3f}")


def main() -> None:
    data = build()
    Path(FIXTURES_PATH).parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=1)
    # one line per embedding instead of one line per float
    text = re.sub(r"\[\s+(-?[0-9][^\]\[{}\"]*?)\s+\]",
                  lambda m: "[" + ",".join(x.strip() for x in m.group(1).split(",")) + "]", text)
    Path(FIXTURES_PATH).write_text(text + "\n")
    n_clusters = sum(len(r["clusters"]) for r in data["recordings"])
    print(f"wrote {FIXTURES_PATH} ({len(data['recordings'])} recordings, {n_clusters} clusters)")


if __name__ == "__main__":
    main()
