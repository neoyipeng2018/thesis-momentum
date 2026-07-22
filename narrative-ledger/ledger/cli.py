from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, cast

from pydantic import TypeAdapter

from .candidates import (
    CandidatePublicationError,
    active_candidates,
    list_candidates,
    publish_candidate,
)
from .check import check_case
from .migrate import MigrationConflictError, fresh_start, migrate_v1
from .models import (
    CheckResult,
    EvidenceCapture,
    ResearchCase,
    ResearchEpisode,
    SourceProfile,
    ValidatedCandidate,
    research_episodes_by_id,
    source_profiles_by_id,
)
from .render import render_candidate
from .router import ModeResult, full, monitor, scan, scout, underwrite
from .storage import load_model, load_models


ROOT = Path(__file__).resolve().parent.parent


class _BaseArgs(Protocol):
    command: str
    root: Path


class _CaseArgs(_BaseArgs, Protocol):
    case: Path


class _PublishArgs(_CaseArgs, Protocol):
    expect_digest: str
    published_at: datetime


class _RenderArgs(_BaseArgs, Protocol):
    candidate: Path
    output: Path


class _AsOfArgs(_BaseArgs, Protocol):
    as_of: datetime


class _WindowArgs(_AsOfArgs, Protocol):
    start: datetime
    end: datetime


class _FullArgs(_WindowArgs, _CaseArgs, Protocol):
    pass


class _ApplyArgs(_BaseArgs, Protocol):
    apply: bool


@dataclass(frozen=True)
class _CaseContext:
    case: ResearchCase
    profile: SourceProfile
    episode: ResearchEpisode
    evidence: tuple[EvidenceCapture, ...]


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ledger")
    parser.add_argument("--root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)

    check_parser = commands.add_parser("check")
    check_parser.add_argument("case", type=Path)

    publish = commands.add_parser("publish-candidate")
    publish.add_argument("case", type=Path)
    publish.add_argument("--expect-digest", required=True)
    publish.add_argument("--published-at", type=_timestamp, required=True)

    report = commands.add_parser("render-candidate")
    report.add_argument("candidate", type=Path)
    report.add_argument("--output", type=Path, required=True)

    candidates = commands.add_parser("candidates")
    candidates.add_argument(
        "--as-of", type=_timestamp, default=datetime.now(timezone.utc)
    )

    commands.add_parser("scout")

    scan_parser = commands.add_parser("scan")
    _window_arguments(scan_parser)

    underwrite_parser = commands.add_parser("underwrite")
    underwrite_parser.add_argument("case", type=Path)

    monitor_parser = commands.add_parser("monitor")
    monitor_parser.add_argument(
        "--as-of", type=_timestamp, default=datetime.now(timezone.utc)
    )

    full_parser = commands.add_parser("full")
    full_parser.add_argument("case", type=Path)
    _window_arguments(full_parser)

    migration = commands.add_parser("migrate-v2")
    migration.add_argument("--apply", action="store_true")

    reset = commands.add_parser("fresh-start")
    reset.add_argument("--apply", action="store_true")
    return parser


def _window_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start", type=_timestamp, required=True)
    parser.add_argument("--end", type=_timestamp, required=True)
    parser.add_argument("--as-of", type=_timestamp, required=True)


def _record_path(path: Path, root: Path, directory: str) -> Path:
    if path.is_file():
        return path
    relative = root / path
    if relative.is_file():
        return relative
    name = path.name if path.suffix == ".json" else f"{path.name}.json"
    candidate = root / "records" / directory / name
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(path)


def _case_context(root: Path, path: Path) -> _CaseContext:
    records = root / "records"
    case = load_model(_record_path(path, root, "research"), ResearchCase)
    profiles = load_models(records / "sources", SourceProfile)
    episodes = load_models(records / "episodes", ResearchEpisode)
    profile = source_profiles_by_id(profiles).get(case.source_id)
    episode = research_episodes_by_id(episodes).get(case.episode_id)
    if profile is None:
        raise ValueError(f"source profile not found: {case.source_id}")
    if episode is None:
        raise ValueError(f"research episode not found: {case.episode_id}")
    evidence = load_models(records / "evidence", EvidenceCapture)
    return _CaseContext(case, profile, episode, evidence)


def _mode_json(result: ModeResult) -> str:
    adapter = TypeAdapter(ModeResult)
    return adapter.dump_json(result, indent=2).decode()


def _candidate_json(candidates: tuple[ValidatedCandidate, ...]) -> str:
    adapter = TypeAdapter(tuple[ValidatedCandidate, ...])
    return adapter.dump_json(candidates, indent=2).decode()


def _check_command(args: _CaseArgs) -> int:
    context = _case_context(args.root, args.case)
    result = check_case(
        context.case, context.profile, context.episode, context.evidence
    )
    print(result.model_dump_json(indent=2))
    return 0 if result.valid else 2


def _publish_command(args: _PublishArgs) -> int:
    context = _case_context(args.root, args.case)
    result = publish_candidate(
        context.case,
        context.profile,
        context.episode,
        context.evidence,
        args.expect_digest,
        args.published_at,
        args.root / "records" / "candidates",
    )
    print(result.candidate.model_dump_json(indent=2))
    print(f"created={str(result.created).lower()} path={result.path}")
    return 0


def _render_command(args: _RenderArgs) -> int:
    records = args.root / "records"
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    output = output.resolve()
    allowed_directories = {
        (root / "reports").resolve(),
        (root / "records" / "reports").resolve(),
    }
    if output.suffix != ".html" or output.parent not in allowed_directories:
        raise ValueError(
            "candidate report output must be a flat HTML file in reports/ "
            "or records/reports/"
        )
    candidate = load_model(
        _record_path(args.candidate, args.root, "candidates"), ValidatedCandidate
    )
    profiles = load_models(records / "sources", SourceProfile)
    profile = source_profiles_by_id(profiles).get(candidate.source_id)
    if profile is None:
        raise ValueError(f"source profile not found: {candidate.source_id}")
    evidence = load_models(records / "evidence", EvidenceCapture)
    output.parent.mkdir(parents=True, exist_ok=True)
    render_candidate(candidate, profile, evidence, output)
    print(output)
    return 0


def _candidates_command(args: _AsOfArgs) -> int:
    records = args.root / "records"
    candidates = list_candidates(records / "candidates")
    profiles = load_models(records / "sources", SourceProfile)
    print(_candidate_json(active_candidates(candidates, profiles, args.as_of)))
    return 0


def _scout_command(args: _BaseArgs) -> int:
    profiles = load_models(args.root / "records" / "sources", SourceProfile)
    print(_mode_json(scout(profiles)))
    return 0


def _scan_command(args: _WindowArgs) -> int:
    records = args.root / "records"
    profiles = load_models(records / "sources", SourceProfile)
    episodes = load_models(records / "episodes", ResearchEpisode)
    print(_mode_json(scan(profiles, episodes, args.start, args.end, args.as_of)))
    return 0


def _underwrite_command(args: _CaseArgs) -> int:
    context = _case_context(args.root, args.case)
    print(
        _mode_json(
            underwrite(
                context.case, context.profile, context.episode, context.evidence
            )
        )
    )
    return 0


def _monitor_command(args: _AsOfArgs) -> int:
    records = args.root / "records"
    candidates = list_candidates(records / "candidates")
    profiles = load_models(records / "sources", SourceProfile)
    print(_mode_json(monitor(candidates, profiles, args.as_of)))
    return 0


def _full_command(args: _FullArgs) -> int:
    records = args.root / "records"
    case = load_model(_record_path(args.case, args.root, "research"), ResearchCase)
    profiles = load_models(records / "sources", SourceProfile)
    episodes = load_models(records / "episodes", ResearchEpisode)
    evidence = load_models(records / "evidence", EvidenceCapture)
    print(
        _mode_json(
            full(
                profiles,
                episodes,
                case,
                evidence,
                args.start,
                args.end,
                args.as_of,
            )
        )
    )
    return 0


def _migration_command(args: _ApplyArgs) -> int:
    result = migrate_v1(args.root, dry_run=not args.apply)
    mode = "applied" if args.apply else "dry-run"
    print(
        f"{result.status} mode={mode} sources={len(result.source_ids)} "
        f"episodes={result.episode_count} evidence={result.evidence_count} "
        f"manifest={result.manifest_sha256}"
    )
    for action in result.actions:
        print(f"{action.kind}\t{action.source or '-'}\t{action.target or '-'}")
    return 0


def _reset_command(args: _ApplyArgs) -> int:
    result = fresh_start(args.root, dry_run=not args.apply)
    mode = "applied" if args.apply else "dry-run"
    print(f"fresh_start_complete mode={mode} removed={len(result.removed)}")
    for path in result.removed:
        print(path)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parsed = cast(_BaseArgs, _parser().parse_args(argv))
    try:
        if parsed.command == "check":
            return _check_command(cast(_CaseArgs, parsed))
        if parsed.command == "publish-candidate":
            return _publish_command(cast(_PublishArgs, parsed))
        if parsed.command == "render-candidate":
            return _render_command(cast(_RenderArgs, parsed))
        if parsed.command == "candidates":
            return _candidates_command(cast(_AsOfArgs, parsed))
        if parsed.command == "scout":
            return _scout_command(parsed)
        if parsed.command == "scan":
            return _scan_command(cast(_WindowArgs, parsed))
        if parsed.command == "underwrite":
            return _underwrite_command(cast(_CaseArgs, parsed))
        if parsed.command == "monitor":
            return _monitor_command(cast(_AsOfArgs, parsed))
        if parsed.command == "full":
            return _full_command(cast(_FullArgs, parsed))
        if parsed.command == "migrate-v2":
            return _migration_command(cast(_ApplyArgs, parsed))
        if parsed.command == "fresh-start":
            return _reset_command(cast(_ApplyArgs, parsed))
        raise ValueError(f"unknown command: {parsed.command}")
    except MigrationConflictError as error:
        print(error.manifest_json, file=sys.stderr, end="")
        return 2
    except (CandidatePublicationError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
