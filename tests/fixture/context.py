import pytest

from mpyflow.shared.context.process import get_worker_ctx
from multiprocessing.context import SpawnContext


@pytest.fixture
def factory_ctx() -> SpawnContext:
    return get_worker_ctx()
