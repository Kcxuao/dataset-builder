from uuid import uuid4

import pytest

from dataset_builder.application.distillation import DistillationResponse, DistillationService
from dataset_builder.db.orm import TrainingSampleRow


def test_distillation_response_trims_and_rejects_blank_answers() -> None:
    response = DistillationResponse.model_validate({"assistant_messages": [" 升级回答 "]})

    assert response.assistant_messages == ["升级回答"]
    with pytest.raises(ValueError):
        DistillationResponse.model_validate({"assistant_messages": [" "]})


def test_distillation_candidate_preserves_questions_and_replaces_only_assistant_messages() -> None:
    source_id, run_id, job_id = uuid4(), uuid4(), uuid4()
    seed = TrainingSampleRow(
        id=source_id,
        project_id=uuid4(),
        document_id=uuid4(),
        chunk_id=uuid4(),
        messages=[
            {"role": "system", "content": "规则"},
            {"role": "user", "content": "第一问"},
            {"role": "assistant", "content": "旧第一答"},
            {"role": "user", "content": "追问"},
            {"role": "assistant", "content": "旧第二答"},
        ],
        metadata_={"source_name": "guide.md"},
    )
    candidate = DistillationService._candidate(
        seed, DistillationResponse(assistant_messages=["新第一答", "新第二答"]), run_id, job_id
    )

    assert [message.content for message in candidate.messages] == ["规则", "第一问", "新第一答", "追问", "新第二答"]
    assert candidate.metadata["distillation_source_id"] == str(source_id)


def test_distillation_candidate_requires_matching_assistant_count() -> None:
    seed = TrainingSampleRow(
        id=uuid4(), project_id=uuid4(), document_id=uuid4(), chunk_id=uuid4(),
        messages=[{"role": "user", "content": "问题"}, {"role": "assistant", "content": "旧回答"}], metadata_={},
    )

    with pytest.raises(ValueError, match="数量一致"):
        DistillationService._candidate(seed, DistillationResponse(assistant_messages=["一", "二"]), uuid4(), uuid4())
