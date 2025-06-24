from concurrent.futures.thread import ThreadPoolExecutor
from mpyflow.shared.interfaces.logger import SyncStdoutInterface
from typing import AsyncIterator, final, Any


@final
class PassThrough:
    __slots__: tuple[str, ...] = ("__output",)

    def __init__(self, output: bool = False) -> None:
        super().__init__()
        self.__output = output

    def on_close(self, sync_out: SyncStdoutInterface, /) -> None:
        if self.__output:
            sync_out.print_message("", "worker: finished")

    async def work(
        self, sync_out: SyncStdoutInterface, data: Any, _th_exc: ThreadPoolExecutor, /
    ) -> AsyncIterator[Any]:
        if self.__output:
            sync_out.print_message("", f"worker: {data!s}")
        yield data
