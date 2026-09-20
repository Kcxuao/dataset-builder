"""Write records one at a time through an atomic temporary file."""

import json
import os
import tempfile
from collections.abc import AsyncIterable
from pathlib import Path


class JSONLExporter:
    async def export(self, records: AsyncIterable[dict[str, object]], destination: Path) -> int:
        return await _write(records, destination, jsonl=True)


class JSONExporter:
    async def export(self, records: AsyncIterable[dict[str, object]], destination: Path) -> int:
        return await _write(records, destination, jsonl=False)


async def _write(records: AsyncIterable[dict[str, object]], destination: Path, jsonl: bool) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    count = 0
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            if not jsonl:
                output.write("[")
            async for record in records:
                serialized = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                if jsonl:
                    output.write(serialized + "\n")
                else:
                    output.write(("," if count else "") + serialized)
                count += 1
            if not jsonl:
                output.write("]")
        os.replace(temporary, destination)
        return count
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
