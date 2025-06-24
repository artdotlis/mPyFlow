import pytest

from mpyflow.library.sync_io.hello_world import HelloWorld
from mpyflow.library.sync_io.no_output import NoOutputSink
from mpyflow.library.sync_io.queue import SyncQueue
from mpyflow.library.work.pass_through import PassThrough
from mpyflow.library.workable.element import Workable
from mpyflow.shared.convert.enc_dec import str_to_bytes, bytes_to_str
from multiprocessing.context import SpawnContext

pytest_plugins = ("tests.fixture.context",)


@pytest.fixture
def two_sync_workables(
    factory_ctx: SpawnContext,
) -> tuple[Workable[str, str], Workable[str, str]]:
    que_1 = SyncQueue[str](factory_ctx, 2, str_to_bytes, bytes_to_str)
    que_2 = SyncQueue[str](factory_ctx, 2, str_to_bytes, bytes_to_str)
    return (
        Workable[str, str](factory_ctx, PassThrough(), que_1),
        Workable[str, str](factory_ctx, PassThrough(), que_2),
    )


@pytest.fixture
def hello_world(factory_ctx: SpawnContext) -> Workable[str, str]:
    return Workable[str, str](factory_ctx, PassThrough(), HelloWorld("test"))


@pytest.fixture
def throw_away_sink(factory_ctx: SpawnContext) -> Workable[str, str]:
    return Workable[str, str](factory_ctx, PassThrough(), NoOutputSink())
