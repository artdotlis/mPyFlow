from concurrent.futures.thread import ThreadPoolExecutor
from mpyflow.shared.container.data import InputData
from typing import final, Any


@final
class HelloWorld:
    __slots__: tuple[str, ...] = ("__extra", "__in", "__out", "__to_print")

    def __init__(self, extra: str, /) -> None:
        super().__init__()
        self.__to_print = True
        self.__extra = extra
        self.__in = True
        self.__out = False

    def has_input(self) -> bool:
        return self.__in

    def has_output(self) -> bool:
        return self.__out

    def wr_on_close(self) -> None:
        pass

    def on_error(self) -> None:
        pass

    async def read(self, _th_exc: ThreadPoolExecutor, /) -> InputData[str] | None:
        if not self.__to_print:
            return None
        self.__to_print = False
        return InputData(f"Hello World! {self.__extra}")

    async def write(self, _data: Any, _th_exc: ThreadPoolExecutor, /) -> bool:
        raise NotImplementedError("Not implemented")

    async def running(self, _th_exc: ThreadPoolExecutor, _provider_cnt: int, /) -> bool:
        return self.__to_print
