"""Interview history: save each finished live interview and summarize the trend.

Results are written as one JSON file per interview into
``context/private/progress/``. That folder is ignored by the public
repository and lives inside the private context repository, so scores stay
private and get backed up with the rest of the private context (see sync.py).

JSON rather than Markdown on purpose: session.load_context() feeds every .md
file under context/ into the interviewer's instructions, and raw score files
should not be. The interviewer gets a short summary instead
(``summary_for_interviewer``), with an explicit instruction that history may
steer what it probes but never what it scores.

Offline interviews are never saved. Their keyword scores are not real
feedback, and mixing them in would make the trend meaningless.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from interview import DEFAULT_TRACK, TRACKS, dimension_label
from session import CONTEXT_DIR

PROGRESS_DIR = CONTEXT_DIR / "private" / "progress"
FORMAT_VERSION = 1

# How many recent scores per stage the interviewer and the page see.
RECENT = 5


def should_save(session):
    """Only finished live interviews that scored something are worth keeping."""
    return (
        session.mode == "live"
        and session.state.finished
        and bool(session.state.signals)
    )


def build_record(session, model, finished_at):
    state = session.state
    card = state.scorecard()
    return {
        "version": FORMAT_VERSION,
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "mode": session.mode,
        "model": model,
        "track": {"key": state.track.key, "label": state.track.label},
        "prompt": {"key": state.prompt.key, "question": state.prompt.question},
        "level": {"key": state.level.key, "label": state.level.label},
        "scores": {row["dimension"]: row["score"] for row in card["rows"]},
        "gaps": {row["dimension"]: row["gap"] for row in card["rows"] if row["score"] is not None},
        "total": card["total"],
        "possible": card["possible"],
        "assessed": card["assessed"],
        "headline": (state.debrief or {}).get("headline", ""),
        "improvements": (state.debrief or {}).get("improvements", []),
    }


def save_result(session, directory=PROGRESS_DIR, model="", now=None):
    """Write one finished interview to disk. Returns the path, or None if skipped."""
    if not should_save(session):
        return None
    finished_at = now or datetime.now()
    record = build_record(session, model, finished_at)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    stem = "%s_%s" % (finished_at.strftime("%Y-%m-%dT%H-%M-%S"), _slug(record["prompt"]["key"]))
    path = directory / ("%s.json" % stem)
    counter = 2
    while path.exists():
        path = directory / ("%s-%d.json" % (stem, counter))
        counter += 1
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


def record_track(record):
    """The track a saved record belongs to. Records from before tracks existed are product sense."""
    key = (record.get("track") or {}).get("key", DEFAULT_TRACK)
    return key if key in TRACKS else DEFAULT_TRACK


def load_history(directory=PROGRESS_DIR, track=None):
    """Every readable saved interview, oldest first, optionally for one track only.

    Unreadable files are skipped.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    records = []
    for path in directory.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict) or not isinstance(record.get("scores"), dict):
            continue
        if track is not None and record_track(record) != track:
            continue
        records.append(record)
    records.sort(key=lambda r: str(r.get("finished_at", "")))
    return records


def summarize(history, track=DEFAULT_TRACK):
    """Per-stage averages and recent scores for one track, plus the weakest stage.

    ``history`` should already be that track's records. Only stages with at
    least one score count toward ``weakest``. Ties break in stage order,
    matching InterviewState.weakest.
    """
    stages = []
    for dimension in TRACKS[track].dimensions:
        scores = [
            r["scores"].get(dimension)
            for r in history
            if isinstance(r["scores"].get(dimension), int)
        ]
        stages.append(
            {
                "dimension": dimension,
                "label": dimension_label(dimension),
                "count": len(scores),
                "average": round(sum(scores) / len(scores), 1) if scores else None,
                "recent": scores[-RECENT:],
            }
        )
    scored = [s for s in stages if s["count"]]
    weakest = min(scored, key=lambda s: s["average"]) if scored else None
    return {
        "interviews": len(history),
        "stages": stages,
        "weakest": weakest["label"] if weakest else None,
    }


def summary_for_interviewer(history, track=DEFAULT_TRACK):
    """A few lines for the interviewer's instructions, or '' with no history.

    Only that track's interviews count; other tracks score different stages.
    """
    history = [r for r in history if record_track(r) == track]
    if not history:
        return ""
    summary = summarize(history, track)
    lines = ["%d previous interview%s." % (summary["interviews"], "" if summary["interviews"] == 1 else "s")]
    for stage in summary["stages"]:
        if stage["count"]:
            lines.append(
                "  %s: average %.1f over %d; most recent %s"
                % (
                    stage["label"],
                    stage["average"],
                    stage["count"],
                    ", ".join(str(s) for s in stage["recent"]),
                )
            )
        else:
            lines.append("  %s: never assessed" % stage["label"])
    if summary["weakest"]:
        lines.append("Weakest stage so far: %s." % summary["weakest"])
    return "\n".join(lines)


def overview(history):
    """What the Progress page shows: one section per track that has interviews.

    Each section has that track's stage summary plus one row per interview,
    newest first.
    """
    sections = []
    for key, track in TRACKS.items():
        records = [r for r in history if record_track(r) == key]
        if not records:
            continue
        section = summarize(records, key)
        section["key"] = key
        section["label"] = track.label
        section["history"] = [
            {
                "finished_at": r.get("finished_at", ""),
                "question": (r.get("prompt") or {}).get("question", ""),
                "level": (r.get("level") or {}).get("label", ""),
                "total": r.get("total"),
                "possible": r.get("possible"),
                "headline": r.get("headline", ""),
                "scores": [
                    {"label": dimension_label(d), "score": r["scores"].get(d)}
                    for d in track.dimensions
                ],
            }
            for r in reversed(records)
        ]
        sections.append(section)
    return {"interviews": len(history), "tracks": sections}


def commit_message(record_path):
    """A readable commit message for an auto-saved interview."""
    try:
        record = json.loads(Path(record_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "Save interview result"
    return "Save interview: %s, %s/%s (%s)" % (
        (record.get("prompt") or {}).get("key", "interview"),
        record.get("total"),
        record.get("possible"),
        (record.get("level") or {}).get("label", ""),
    )


def _slug(text):
    return re.sub(r"[^a-z0-9-]+", "-", str(text).lower()).strip("-") or "interview"
