from uuid import UUID, uuid4

import pytest

from dataset_builder.application.review import ReviewService
from dataset_builder.db.orm import ChunkRow, ProjectRow, TrainingSampleRow


class ReviewSession:
    def __init__(self, rows: list[object]) -> None:
        self.rows = {(type(row), row.id): row for row in rows}
        self.flushed = False

    async def get(self, model: type, row_id: UUID) -> object | None:
        return self.rows.get((model, row_id))

    async def scalar(self, _query) -> object | None:
        return None

    def add(self, row: object) -> None:
        self.rows[(type(row), row.id)] = row

    def add_all(self, rows) -> None:
        for row in rows:
            self.add(row)

    async def execute(self, _query) -> None:
        return None

    async def flush(self, _rows=None) -> None:
        self.flushed = True


def review_fixture() -> tuple[ReviewSession, TrainingSampleRow, TrainingSampleRow]:
    project_id, document_id, chunk_id = uuid4(), uuid4(), uuid4()
    project = ProjectRow(id=project_id, name="dataset", deleted_at=None)
    chunk = ChunkRow(id=chunk_id, document_id=document_id, index=0, content="来源事实")
    source = TrainingSampleRow(
        id=uuid4(),
        project_id=project_id,
        document_id=document_id,
        chunk_id=chunk_id,
        messages=[{"role": "user", "content": "问题"}, {"role": "assistant", "content": "原回答"}],
        metadata_={},
        review_status="approved",
        validation_status="passed",
        is_deleted=False,
    )
    candidate = TrainingSampleRow(
        id=uuid4(),
        project_id=project_id,
        document_id=document_id,
        chunk_id=chunk_id,
        messages=[{"role": "user", "content": "问题"}, {"role": "assistant", "content": "教师回答"}],
        metadata_={"generator": "distillation", "distillation_source_id": str(source.id)},
        review_status="pending",
        validation_status="passed",
        is_deleted=False,
    )
    return ReviewSession([project, chunk, source, candidate]), source, candidate


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "candidate_status", "source_replaced"),
    [
        ("adopt_teacher", "approved", True),
        ("keep_original", "rejected", False),
        ("keep_both", "approved", False),
    ],
)
async def test_distillation_review_decisions(
    decision: str,
    candidate_status: str,
    source_replaced: bool,
) -> None:
    session, source, candidate = review_fixture()

    result = await ReviewService(session).decide_distillation(candidate.id, decision)  # type: ignore[arg-type]

    assert session.flushed is True
    assert candidate.review_status == candidate_status
    assert candidate.metadata_["distillation_decision"] == decision
    assert (source.superseded_at is not None) is source_replaced
    assert result["source_messages"][1]["content"] == "原回答"
    assert result["candidate_messages"][1]["content"] == "教师回答"
