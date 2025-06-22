import multiprocessing
from mpyflow.shared.errors.exception import BootstrapEx
from typing import Final

_CTX: Final[multiprocessing.context.BaseContext] = multiprocessing.get_context("spawn")


def get_worker_ctx() -> multiprocessing.context.SpawnContext:
    if not isinstance(_CTX, multiprocessing.context.SpawnContext):
        raise BootstrapEx(f"Expected SpawnContext got {type(_CTX).__name__}")
    return _CTX
