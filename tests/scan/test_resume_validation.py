"""A resumed scan validates a retried case once, as a clean scan does."""

import asyncio
from pathlib import Path

import pytest
from inspect_scout import (
    Result,
    Scanner,
    Transcript,
    ValidationCase,
    ValidationSet,
    scan,
    scan_resume,
    scanner,
    transcripts_from,
)

from tests.helpers import temp_active_scans_store

LOGS_DIR = Path(__file__).parents[2] / "examples" / "scanner" / "logs"
FAILING_ID = "MUBxLNC9YwakjPFXaFuEZ4"
LIMIT = 4


@scanner(name="resume_validation_retry", messages="all")
def retry_validation(marker: str) -> Scanner[Transcript]:
    async def run(transcript: Transcript) -> Result:
        if transcript.transcript_id == FAILING_ID and not Path(marker).exists():
            raise RuntimeError("judge crashed")
        return Result(value=True)

    return run


async def _transcript_ids() -> list[str]:
    async with transcripts_from(LOGS_DIR).reader() as reader:
        return [info.transcript_id async for info in reader.index()][:LIMIT]


@pytest.mark.parametrize("processes", [1, 2])
def test_resume_revalidates_errored_case_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, processes: int
) -> None:
    monkeypatch.setenv("SCOUT_SCANBUFFER_DIR", str(tmp_path / "buffer"))
    transcript_ids = asyncio.run(_transcript_ids())
    assert FAILING_ID in transcript_ids
    validation = ValidationSet(
        cases=[ValidationCase(id=tid, target=True) for tid in transcript_ids],
        predicate="eq",
    )
    marker = tmp_path / "recovered"
    name = "resume_validation_retry"
    with temp_active_scans_store():
        initial = scan(
            scanners=[retry_validation(str(marker))],
            transcripts=transcripts_from(LOGS_DIR),
            validation=validation,
            scans=str(tmp_path / "interrupted"),
            limit=LIMIT,
            max_processes=processes,
            display="none",
        )
        assert not initial.complete and len(initial.errors) == 1
        marker.touch()
        resumed = scan_resume(initial.location, display="none")
        clean = scan(
            scanners=[retry_validation(str(marker))],
            transcripts=transcripts_from(LOGS_DIR),
            validation=validation,
            scans=str(tmp_path / "clean"),
            limit=LIMIT,
            max_processes=processes,
            display="none",
        )

    assert resumed.complete and not resumed.errors
    resumed_validation = resumed.summary.scanners[name].validation
    clean_validation = clean.summary.scanners[name].validation
    assert resumed_validation is not None and clean_validation is not None
    assert sorted(str(e.id) for e in resumed_validation.entries) == sorted(
        transcript_ids
    )
    assert resumed_validation.metrics == clean_validation.metrics
