"""Offline audio step (spec M1, §5.2 steps 1-3): one recording -> the fixture JSON shape.

NOT part of the service or the image. It needs torch, WhisperX, pyannote and SpeechBrain, a Hugging Face token
with the pyannote `speaker-diarization-community-1` terms accepted, and ffmpeg on PATH. None of these are project
dependencies (they would add gigabytes to the shared image), so run it with throwaway extras:

    ffmpeg -i talk.mp4 -ac 1 -ar 16000 talk.wav
    HF_TOKEN=... uv run --with whisperx --with speechbrain \\
        python -m rapport_speakers.audio talk.wav --session talk-ebpf-zero-code > recording.json

The output is one entry for `recordings` in `data/fixtures.json`: segments with local labels (SPEAKER_00, ...)
and one L2-normalized ECAPA embedding per cluster, built from up to 60 s of its clean (non-overlapped) speech of
at least 1 s per segment. Written against the WhisperX 3.x and SpeechBrain 1.x documentation; not run in CI.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

MIN_SEGMENT_S = 1.0
MAX_EMBED_S = 60.0
SAMPLE_RATE = 16_000


def _overlaps(start: float, end: float, label: str, turns: list[tuple[float, float, str]]) -> bool:
    return any(s < end and start < e and spk != label for s, e, spk in turns)


def process(wav_path: str, session_id: str, *, device: str = "cpu", model_name: str = "large-v3") -> dict:
    import torch  # noqa: F401  (imported lazily: optional, heavy)
    import whisperx
    from speechbrain.inference.speaker import EncoderClassifier

    from .vectors import normalize

    audio = whisperx.load_audio(wav_path)
    asr = whisperx.load_model(model_name, device, compute_type="float16" if device == "cuda" else "int8")
    result = asr.transcribe(audio, batch_size=8)
    align_model, metadata = whisperx.load_align_model(language_code=result["language"], device=device)
    result = whisperx.align(result["segments"], align_model, metadata, audio, device, return_char_alignments=False)
    diarize = whisperx.diarize.DiarizationPipeline(use_auth_token=os.environ["HF_TOKEN"], device=device)
    turns_df = diarize(audio)
    result = whisperx.assign_word_speakers(turns_df, result)
    turns = [(float(r.start), float(r.end), str(r.speaker)) for r in turns_df.itertuples()]

    segments = []
    for seg in result["segments"]:
        label = seg.get("speaker")
        if not label:
            continue
        start, end = float(seg["start"]), float(seg["end"])
        segments.append({"start_s": round(start, 2), "end_s": round(end, 2), "label": label,
                         "text": seg["text"].strip(), "overlap": _overlaps(start, end, label, turns)})

    encoder = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb", run_opts={"device": device})
    waveform = torch.from_numpy(audio)
    clusters = []
    for label in sorted({s["label"] for s in segments}):
        pieces, used = [], 0.0
        for s in segments:
            dur = s["end_s"] - s["start_s"]
            if s["label"] != label or s["overlap"] or dur < MIN_SEGMENT_S or used >= MAX_EMBED_S:
                continue
            take = min(dur, MAX_EMBED_S - used)
            a = int(s["start_s"] * SAMPLE_RATE)
            pieces.append(waveform[a:a + int(take * SAMPLE_RATE)])
            used += take
        if not pieces:
            continue  # no clean speech: identification will say unknown
        emb = encoder.encode_batch(torch.cat(pieces).unsqueeze(0)).squeeze().tolist()
        clusters.append({"label": label, "embedding": [round(x, 6) for x in normalize(emb)]})
    return {"session_id": session_id, "recording_uri": f"recordings/{session_id}.mp4", "clusters": clusters,
            "segments": segments}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("wav")
    parser.add_argument("--session", required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--model", default="large-v3")
    args = parser.parse_args(argv)
    if "HF_TOKEN" not in os.environ:
        sys.exit("set HF_TOKEN (pyannote diarization is a gated model)")
    json.dump(process(args.wav, args.session, device=args.device, model_name=args.model), sys.stdout, indent=1)


if __name__ == "__main__":
    main()
