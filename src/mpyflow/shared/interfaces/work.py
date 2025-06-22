from concurrent.futures.thread import ThreadPoolExecutor
from mpyflow.shared.interfaces.logger import SyncStdoutInterface
from typing import Protocol, AsyncIterator


class WorkInterface[IT, OT](Protocol):
    # Can block event queue
    def on_close(self, sync_out: SyncStdoutInterface, /) -> None: ...

    # Should not block event queue
    # TODO async should ne re-added, when mypy support improves:
    # async def work(...
    def work(
        self, sync_out: SyncStdoutInterface, data: IT, thread_pool: ThreadPoolExecutor, /
    ) -> AsyncIterator[OT]: ...


class WorkableTermInterface(Protocol):

    def workable_set_error(self) -> None: ...

    def terminated_set_error(self) -> None: ...
