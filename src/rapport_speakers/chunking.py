"""Turn chunking (spec §4.4): split long speaker turns into windows of up to ~60 s on sentence boundaries,
so a search hit lands on a precise timestamp."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Segment:
    """One diarized, transcribed sentence (WhisperX output shape, local speaker label)."""

    start_s: float
    end_s: float
    label: str
    text: str
    overlap: bool = False

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)


@dataclass
class Window:
    label: str
    start_s: float
    end_s: float
    texts: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(self.texts)


def chunk_turns(segments: list[Segment], *, max_window_s: float = 60.0, max_gap_s: float = 2.0) -> list[Window]:
    """Merge consecutive same-speaker sentences while the window stays within `max_window_s` and the pause
    between sentences is at most `max_gap_s`. A single sentence longer than the window stays whole."""
    windows: list[Window] = []
    for seg in sorted(segments, key=lambda s: (s.start_s, s.end_s)):
        cur = windows[-1] if windows else None
        if (
            cur is not None and cur.label == seg.label and seg.start_s - cur.end_s <= max_gap_s
            and seg.end_s - cur.start_s <= max_window_s
        ):
            cur.end_s = max(cur.end_s, seg.end_s)
            cur.texts.append(seg.text)
        else:
            windows.append(Window(seg.label, seg.start_s, seg.end_s, [seg.text]))
    return windows


def clean_speech_s(segments: list[Segment], label: str) -> float:
    """Speech for one local speaker, excluding overlapped regions (§5.2 step 3)."""
    return sum(s.duration_s for s in segments if s.label == label and not s.overlap)
