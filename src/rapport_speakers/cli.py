"""Local commands for speaker identification.

    PYTHONPATH=src uv run python -m rapport_speakers.cli demo
    PYTHONPATH=src uv run python -m rapport_speakers.cli who "who asked about eBPF overhead on robots"
    PYTHONPATH=src uv run python -m rapport_speakers.cli who "kernel" --speaker Dev
    PYTHONPATH=src uv run python -m rapport_speakers.cli top "eBPF"
    PYTHONPATH=src uv run python -m rapport_speakers.cli said kestrel.mia
    PYTHONPATH=src uv run python -m rapport_speakers.cli eval

With `ES_URL` plus `ES_ADMIN_API_KEY` (or `SPEAKERS_ES_API_KEY`) set, commands use Elasticsearch: run `seed` once,
then the others read the indices. With no keys, every command seeds an in-memory store from the committed
fixtures first, so `enroll` and `erase` only last for that one command (use `demo` to see them chained).

Output goes to your terminal only (it includes transcript text and speaker names). Logs stay IDs and counts.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace

from .config import STORE_ES, Settings
from .decide import AMBIGUOUS, IDENTIFIED, UNKNOWN, decide
from .fixtures import load as load_fixtures
from .models import SearchResult
from .runtime import Runtime, build_runtime


def _settings() -> Settings:
    settings = Settings.from_env()
    admin_key = os.environ.get("ES_ADMIN_API_KEY")
    if admin_key and settings.es_url and not os.environ.get("SPEAKERS_ES_API_KEY"):
        settings = replace(settings, es_api_key=admin_key, store=os.environ.get("SPEAKERS_STORE") or STORE_ES)
    return settings


def _print_hits(result: SearchResult) -> None:
    if not result.hits:
        print("  (no matching moments)")
        return
    for h in result.hits:
        status = "" if h.speaker_status == IDENTIFIED else f" [{h.speaker_status}]"
        print(f"  {h.speaker_name}{status} at {h.spoken_at_label} in \"{h.session_title}\" ({h.room}), "
              f"t={h.start_s:.0f}s  {h.jump_url or ''}")
        print(f"      \"{h.text}\"")


def cmd_seed(rt: Runtime, _: argparse.Namespace) -> None:
    from .pipeline import seed

    report = rt.seed_report or seed(rt.store, rt.settings)
    print(f"store: {rt.settings.store}  conference: {rt.settings.conference_id}  sessions: {report.sessions}")
    print(f"enrolled from the schedule: {len(report.enroll.enrolled)}")
    for sid, reason in report.enroll.flagged:
        print(f"  flagged for review: {sid}: {reason}")
    for sid, reason in report.enroll.skipped:
        print(f"  not auto-enrolled: {sid}: {reason}")
    totals = {IDENTIFIED: 0, AMBIGUOUS: 0, UNKNOWN: 0}
    for r in report.identify:
        for status, n in r.counts().items():
            totals[status] += n
    print(f"clusters: {totals}")
    print(f"documents: {report.counts}")


def cmd_who(rt: Runtime, args: argparse.Namespace) -> None:
    result = rt.search.search(args.query, speaker=args.speaker, session=args.session, size=args.size)
    print(f"Q: {args.query}" + (f"  (speaker={args.speaker})" if args.speaker else "") + f"  [{result.mode}]")
    if result.hits:
        top = result.hits[0]
        note = "" if top.speaker_status == IDENTIFIED else f" ({top.speaker_status}: not named)"
        print(f"A: {top.speaker_name}{note}, at {top.spoken_at_label} in \"{top.session_title}\" ({top.room}), "
              f"{top.jump_url}")
    _print_hits(result)


def cmd_top(rt: Runtime, args: argparse.Namespace) -> None:
    result = rt.search.top_speakers(args.query, size=args.size)
    print(f"Who talked most about: {args.query}")
    for row in result.speakers:
        print(f"  {row.speaker_name:<12} {row.utterances} moments  ({row.speaker_id})")


def cmd_said(rt: Runtime, args: argparse.Namespace) -> None:
    result = rt.search.speaker_utterances(args.speaker, size=args.size)
    print(f"Everything {args.speaker} said:")
    for h in result.utterances:
        print(f"  {h.spoken_at_label}  {h.session_title}: \"{h.text}\"")


def cmd_enroll(rt: Runtime, args: argparse.Namespace) -> None:
    fx = load_fixtures()
    person, clip = fx.people.get(args.person_id), fx.registration_clips.get(args.person_id)
    if person is None or clip is None:
        sys.exit(f"no registration clip for {args.person_id}; have: {', '.join(sorted(fx.registration_clips))}")
    voiceprint, relabel = rt.pipeline.enroll_registration(person, clip)
    print(f"enrolled {voiceprint.name} ({voiceprint.person_id}) from a registration clip; "
          f"{voiceprint.sample_count} sample(s)")
    print(f"relabeled {len(relabel.voices)} past unknown voices, {relabel.utterances} utterances: "
          f"{', '.join(relabel.voices) or '-'}")


def cmd_erase(rt: Runtime, args: argparse.Namespace) -> None:
    print(rt.pipeline.erase_person(args.person_id).model_dump_json(indent=1))


def cmd_purge(rt: Runtime, _: argparse.Namespace) -> None:
    print(f"deleted (retention): {rt.pipeline.purge_biometrics()}")


def cmd_eval(rt: Runtime, _: argparse.Namespace) -> None:
    """§7 on the fixtures: identification accuracy, false accepts, false rejects, and a threshold sweep.
    Gallery = schedule-enrolled voiceprints; probes = every cluster. Ground truth comes from the fixtures."""
    fx = load_fixtures()
    store = rt.store
    conf, model = rt.settings.conference_id, rt.settings.model_id
    enrolled = {pid for pid in fx.people if store.samples_for(conf, pid, model)}
    probes = []
    for rec in fx.recordings.values():
        for c in rec.clusters:
            speech = sum(s.duration_s for s in rec.segments if s.label == c.label and not s.overlap)
            hits = store.knn_voiceprints(c.embedding, conference_id=conf, model_id=model, k=5, num_candidates=50)
            probes.append((c.truth, speech, hits))
    print(f"gallery: {len(enrolled)} voiceprints   probes: {len(probes)} clusters")
    print(f"{'T_ACCEPT':>8} {'MARGIN':>6} {'accuracy':>8} {'false-acc':>9} {'false-rej':>9}")
    for t in (0.45, 0.55, 0.65, 0.75):
        for m in (0.05, 0.10, 0.20):
            correct = fa = fr = 0
            for truth, speech, hits in probes:
                status, pid, _ = decide(hits, speech, T_ACCEPT=t, MARGIN=m)
                accepted = status == IDENTIFIED
                if accepted and pid == truth:
                    correct += 1
                elif accepted:
                    fa += 1
                elif truth in enrolled:
                    fr += 1
                else:
                    correct += 1  # correctly left unknown
            n = len(probes)
            mark = "  <- default" if (t, m) == (0.55, 0.10) else ""
            print(f"{t:>8.2f} {m:>6.2f} {correct / n:>8.0%} {fa:>9d} {fr:>9d}{mark}")
    print("Pool boost is off here (raw kNN), so this is the conservative case.")


def cmd_demo(rt: Runtime, _: argparse.Namespace) -> None:
    """The whole story on one store: seed, ask, enroll a chair (relabel), ask again, erase."""
    cmd_seed(rt, argparse.Namespace())
    intro = argparse.Namespace(query="welcome to Room B", speaker=None, session="talk-ebpf-zero-code", size=1)
    for q, speaker in (("who asked about eBPF overhead on edge robots", None), ("eBPF kernel versions", "Dev")):
        print()
        cmd_who(rt, argparse.Namespace(query=q, speaker=speaker, session=None, size=3))
    print()
    cmd_who(rt, intro)
    print()
    cmd_top(rt, argparse.Namespace(query="eBPF", size=5))
    print()
    cmd_enroll(rt, argparse.Namespace(person_id="chair-felix"))
    print()
    cmd_who(rt, intro)
    print()
    print("erasure of chair-felix:")
    cmd_erase(rt, argparse.Namespace(person_id="chair-felix"))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="rapport_speakers.cli", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed", help="create the indices and load the schedule, voiceprints and utterances")
    p = sub.add_parser("who", help="who said what: hybrid search with speaker and timestamp")
    p.add_argument("query")
    p.add_argument("--speaker")
    p.add_argument("--session")
    p.add_argument("--size", type=int, default=5)
    p = sub.add_parser("top", help="who talked most about a topic")
    p.add_argument("query")
    p.add_argument("--size", type=int, default=5)
    p = sub.add_parser("said", help="everything one speaker said")
    p.add_argument("speaker")
    p.add_argument("--size", type=int, default=50)
    p = sub.add_parser("enroll", help="enroll from a registration clip, then relabel past unknown voices")
    p.add_argument("person_id")
    p = sub.add_parser("erase", help="erase a person's voice data and reset their labels")
    p.add_argument("person_id")
    sub.add_parser("purge", help="retention: delete every voiceprint, sample and unknown voice")
    sub.add_parser("eval", help="calibration on the fixtures: accuracy and false accepts per threshold")
    sub.add_parser("demo", help="seed, ask, enroll a chair, ask again, erase")
    args = parser.parse_args(argv)

    rt = build_runtime(_settings())  # in-memory: seeded from the fixtures here; Elasticsearch: as it is
    handlers = {"seed": cmd_seed, "who": cmd_who, "top": cmd_top, "said": cmd_said, "enroll": cmd_enroll,
                "erase": cmd_erase, "purge": cmd_purge, "eval": cmd_eval, "demo": cmd_demo}
    handlers[args.cmd](rt, args)


if __name__ == "__main__":
    main()
