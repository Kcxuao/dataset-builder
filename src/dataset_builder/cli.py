"""CLI entry point using the same application services as future APIs."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from dataset_builder.application.build import BuildService
from dataset_builder.application.review import ReviewService
from dataset_builder.config import LLMSettings, Settings
from dataset_builder.db.session import create_engine, create_session_factory
from dataset_builder.exporters.service import SampleExportService
from dataset_builder.llm import OpenAICompatibleClient
from dataset_builder.models import ExportFileType, ExportFormat, Message, ReviewStatus


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="dataset-builder")
    commands = root.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="Import, split, and generate samples for review")
    build.add_argument("input", type=Path)
    build.add_argument("--project-name")
    build.add_argument("--generator", choices=["qa", "instruction"], default="qa")
    build.add_argument("--splitter", choices=["auto", "fixed", "paragraph", "markdown"], default="auto")
    build.add_argument("--max-chars", type=int, default=1000)
    build.add_argument("--overlap", type=int, default=0)
    build.add_argument("--parser-workers", type=int, default=1)
    build.add_argument("--content-field", help="JSON/JSONL field path, such as article.body")
    build.add_argument("--content-column", action="append", default=[], help="CSV column to include; repeat as needed")

    retry = commands.add_parser("retry", help="Retry failed or pending Chunks with the same LLM configuration")
    retry.add_argument("project_id", type=UUID)

    listing = commands.add_parser("list", help="Preview project samples and validation issues")
    listing.add_argument("project_id", type=UUID)
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--offset", type=int, default=0)

    show = commands.add_parser("show", help="Show a sample and its source Chunk")
    show.add_argument("sample_id", type=UUID)

    edit = commands.add_parser("edit", help="Replace sample messages from a JSON file")
    edit.add_argument("sample_id", type=UUID)
    edit.add_argument("--messages-file", type=Path, required=True)

    review = commands.add_parser("review", help="Set the sample review status")
    review.add_argument("sample_id", type=UUID)
    review.add_argument("status", choices=[status.value for status in ReviewStatus])

    for name in ("delete", "restore"):
        action = commands.add_parser(name, help=f"{name.title()} a sample")
        action.add_argument("sample_id", type=UUID)

    exporting = commands.add_parser("export", help="Export approved and validated samples")
    exporting.add_argument("project_id", type=UUID)
    exporting.add_argument("--format", choices=[format.value for format in ExportFormat], required=True)
    exporting.add_argument("--output", type=Path, required=True)
    return root


async def run(args: argparse.Namespace) -> object:
    engine = create_engine(Settings().database_url)
    sessions = create_session_factory(engine)
    try:
        if args.command in {"build", "retry"}:
            client = OpenAICompatibleClient(LLMSettings())
            try:
                builder = BuildService(sessions, client)
                if args.command == "build":
                    summary = await builder.build(
                        args.input, args.project_name or args.input.stem, args.generator,
                        args.splitter, args.max_chars, args.overlap,
                        args.content_field, tuple(args.content_column), parser_workers=args.parser_workers,
                    )
                else:
                    summary = await builder.retry_failed(args.project_id)
                return {
                    "project_id": str(summary.project_id), "run_id": str(summary.run_id),
                    "documents": summary.document_count, "chunks": summary.chunk_count,
                    "samples": summary.sample_count, "failed_chunks": summary.failed_chunk_count,
                }
            finally:
                await client.aclose()

        async with sessions() as session:
            review = ReviewService(session)
            if args.command == "list":
                return await review.list_samples(args.project_id, args.limit, args.offset)
            if args.command == "show":
                return await review.get_sample(args.sample_id)
            if args.command == "edit":
                data = json.loads(args.messages_file.read_text(encoding="utf-8"))
                raw_messages = data.get("messages") if isinstance(data, dict) else data
                if not isinstance(raw_messages, list):
                    raise ValueError("messages-file must contain a JSON array or an object with messages")
                result = await review.edit(args.sample_id, [Message.model_validate(item) for item in raw_messages])
            elif args.command == "review":
                result = await review.set_review(args.sample_id, ReviewStatus(args.status))
            elif args.command in {"delete", "restore"}:
                result = await review.set_deleted(args.sample_id, args.command == "delete")
            elif args.command == "export":
                extension = args.output.suffix.lower().lstrip(".")
                if extension not in {"json", "jsonl"}:
                    raise ValueError("Output file must end in .json or .jsonl")
                try:
                    exported = await SampleExportService(session).export(
                        args.project_id, ExportFormat(args.format), ExportFileType(extension), args.output
                    )
                except (ValueError, OSError):
                    await session.commit()
                    raise
                result = exported.model_dump(mode="json")
            else:
                raise AssertionError(f"Unhandled command: {args.command}")
            await session.commit()
            return result
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    try:
        result = asyncio.run(run(args))
    except (ValueError, LookupError, OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(result, ensure_ascii=False, default=str))
