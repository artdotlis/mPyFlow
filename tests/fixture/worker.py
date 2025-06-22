import pytest

from mpyflow.library.workable.element import Workable
from mpyflow.library.worker import Worker

pytest_plugins = ("tests.fixture.workable",)

type _TWO_WORKA = tuple[Workable[str, str], Workable[str, str]]


@pytest.fixture
def worker_reader(
    hello_world: Workable[str, str], two_sync_workables: _TWO_WORKA
) -> Worker[str, str]:
    w_queue_1, w_queue_2 = two_sync_workables
    return Worker[str, str]("reader", (hello_world,), (w_queue_1, w_queue_2), True)


@pytest.fixture
def worker_writer(
    throw_away_sink: Workable[str, str], two_sync_workables: _TWO_WORKA
) -> Worker[str, str]:
    w_queue_1, w_queue_2 = two_sync_workables
    return Worker[str, str]("writer", (w_queue_1, w_queue_2), (throw_away_sink,))
