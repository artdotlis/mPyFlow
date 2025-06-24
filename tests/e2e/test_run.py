from mpyflow.library.workable.element import Workable
from mpyflow.library.worker import Worker
from multiprocessing.context import SpawnContext
from pathlib import Path

import tempfile
from mpyflow.run_wrapper import start_worker

pytest_plugins = (
    "tests.fixture.context",
    "tests.fixture.workable",
    "tests.fixture.worker",
)


type _TWO_WORKA = tuple[Workable[str, str], Workable[str, str]]


def test_simple_run(
    factory_ctx: SpawnContext,
    worker_reader: Worker[str, str],
    worker_writer: Worker[str, str],
    two_sync_workables: _TWO_WORKA,
    hello_world: Workable[str, str],
    throw_away_sink: Workable[str, str],
) -> None:
    tmp = tempfile.TemporaryDirectory(delete=True)
    start_worker(
        Path(tmp.name),
        "test_logger",
        factory_ctx,
        ((2, worker_reader), (2, worker_writer)),
        (hello_world, throw_away_sink, *two_sync_workables),
    )
