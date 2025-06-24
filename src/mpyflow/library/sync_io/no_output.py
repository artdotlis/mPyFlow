from concurrent.futures.thread import ThreadPoolExecutor
from typing import final, Any


@final
class NoOutputSink:
    __slots__: tuple[str, ...] = ("__in", "__out")

    def __init__(self) -> None:
        super().__init__()
        self.__in = False
        self.__out = True

    def has_input(self) -> bool:
        return self.__in

    def has_output(self) -> bool:
        return self.__out

    def wr_on_close(self) -> None:
        pass

    def on_error(self) -> None:
        pass

    async def read(self, _th_exc: ThreadPoolExecutor, /) -> Any:
        raise NotImplementedError("Not implemented")

    async def write(self, _data: Any, _th_exc: ThreadPoolExecutor, /) -> bool:
        return False

    async def running(self, _th_exc: ThreadPoolExecutor, _provider_cnt: int, /) -> bool:
        raise NotImplementedError("Not implemented")
