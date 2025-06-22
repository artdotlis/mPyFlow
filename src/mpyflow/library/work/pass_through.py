from concurrent.futures.thread import ThreadPoolExecutor
from mpyflow.shared.interfaces.logger import SyncStdoutInterface
from typing import AsyncIterator, final, Any


@final
class PassThrough:
    __slots__: tuple[str, ...] = tuple()

    def on_close(self, _sync_out: SyncStdoutInterface, /) -> None:
        pass

    async def work(
        self, sync_out: SyncStdoutInterface, data: Any, _th_exc: ThreadPoolExecutor, /
    ) -> AsyncIterator[Any]:
        sync_out.print_message("", f"worker: {data!s}")
        yield data
