import asyncio
from concurrent.futures.thread import ThreadPoolExecutor

from dataclasses import dataclass

import multiprocessing
from mpyflow.shared.container.data import InputData
from mpyflow.shared.container.process import ValueP
from mpyflow.shared.errors.exception import WorkableEx, IOProgressEx
from mpyflow.shared.interfaces.io import IOInterface
from mpyflow.shared.interfaces.logger import SyncStdoutInterface
from mpyflow.shared.interfaces.work import WorkInterface
from multiprocessing import synchronize
from typing import final, AsyncIterator


@final
@dataclass(slots=True, frozen=True, kw_only=True)
class _EndTypeInt:
    error: int
    term: int


@final
@dataclass(slots=True, frozen=True, kw_only=True)
class _EndType:
    error: ValueP[int]
    term: ValueP[int]


@final
@dataclass(slots=True, frozen=True, kw_only=True)
class _AsLock:
    writer_async: asyncio.locks.Lock
    reader_async: asyncio.locks.Lock
    worker_async: asyncio.locks.Lock


@final
class IOProgress:
    __slots__ = ("__error", "__lock", "__term")

    def __init__(self, ctx: multiprocessing.context.SpawnContext, /) -> None:
        super().__init__()
        self.__error: ValueP[int] = ctx.Value("i", 0)
        self.__term: ValueP[int] = ctx.Value("i", -1)
        self.__lock: synchronize.RLock = ctx.RLock()

    @property
    def end_type(self) -> _EndTypeInt:
        return _EndTypeInt(error=self.__error.value, term=self.__term.value)

    def add_provider(self) -> None:
        with self.__lock:
            if self.__term.value == -1:
                self.__term.value = 1
            else:
                self.__term.value += 1

    def remove_provider(self) -> bool:
        last = False
        with self.__lock:
            self.__term.value -= 1
            if self.__term.value < 0:
                raise IOProgressEx(
                    "IOProgress had no provider left, but one was removed!"
                )
            if self.__term.value == 0:
                last = True
        return last

    def set_error(self) -> None:
        with self.__lock:
            self.__error.value = 1


@final
class Workable[IN, OT]:
    __slots__ = (
        "__as_lock",
        "__gl_lock",
        "__io_obj",
        "__io_progress",
        "__sync_out",
        "__thp",
        "__work_obj",
    )

    def __init__(
        self,
        ctx: multiprocessing.context.SpawnContext,
        work_instance: WorkInterface[IN, OT],
        io_instance: IOInterface[IN],
        /,
    ) -> None:
        super().__init__()
        self.__sync_out: SyncStdoutInterface | None = None
        self.__work_obj: WorkInterface[IN, OT] = work_instance
        self.__io_obj: IOInterface[IN] = io_instance
        self.__io_progress: IOProgress = IOProgress(ctx)
        self.__thp: ThreadPoolExecutor | None = None
        self.__gl_lock = ctx.Condition()
        self.__as_lock = _AsLock(
            writer_async=asyncio.Lock(),
            worker_async=asyncio.Lock(),
            reader_async=asyncio.Lock(),
        )

    @property
    def thp(self) -> ThreadPoolExecutor:
        if self.__thp is None:
            self.__thp = ThreadPoolExecutor(max_workers=4)
        return self.__thp

    def register_output(self, sync: SyncStdoutInterface, /) -> None:
        if self.__sync_out is None:
            self.__sync_out = sync

    @property
    def sync_out(self) -> SyncStdoutInterface:
        if self.__sync_out is None:
            raise WorkableEx("Output not set!")
        return self.__sync_out

    # WorkInterface and ReWrProgress static. Managed by WorkableManager.
    def workable_on_close(self) -> None:
        self.__work_obj.on_close(self.sync_out)

    def workable_add_provider(self) -> None:
        self.__io_progress.add_provider()
        with self.__gl_lock:
            self.__gl_lock.notify_all()

    def workable_remove_provider(self) -> None:
        if self.__io_progress.remove_provider():
            self.__io_obj.wr_on_close()
            with self.__gl_lock:
                self.__gl_lock.notify_all()

    def workable_set_error(self) -> None:
        self.__io_progress.set_error()
        self.__io_obj.on_error()
        with self.__gl_lock:
            self.__gl_lock.notify_all()
        self.workable_shutdown()

    def terminated_set_error(self) -> None:
        self.__io_obj.on_error()

    def workable_shutdown(self) -> None:
        self.thp.shutdown(True)

    # For coroutines etc. WorkInterface and ReWrProgress custom
    async def workable_running(self) -> bool:
        if self.__io_progress.end_type.error == 1 or self.sync_out.error_occurred():
            raise WorkableEx("Workable error was set!")
        async with self.__as_lock.reader_async:
            return await self.__io_obj.running(self.thp, self.__io_progress.end_type.term)

    async def workable_read(self) -> InputData[IN] | None:
        if self.__io_progress.end_type.error == 1 or self.sync_out.error_occurred():
            raise WorkableEx("Workable error was set!")
        if not self.__io_obj.has_input():
            raise WorkableEx("Workable can not be used as input sink")
        if self.__io_obj.has_output() and self.__io_progress.end_type.term == -1:
            self.sync_out.print_message("", "Waiting for providers!")
            with self.__gl_lock:
                self.__gl_lock.wait(20)
            return None
        async with self.__as_lock.reader_async:
            return await self.__io_obj.read(self.thp)

    async def workable_write(self, data: IN, /) -> bool:
        if self.__io_progress.end_type.error == 1 or self.sync_out.error_occurred():
            raise WorkableEx("Workable error was set!")
        if not self.__io_obj.has_output():
            raise WorkableEx("Workable can not be used as output sink")
        async with self.__as_lock.writer_async:
            return await self.__io_obj.write(data, self.thp)

    async def workable_work(self, data: IN, /) -> AsyncIterator[OT]:
        async with self.__as_lock.worker_async:
            async for subtotals in self.__work_obj.work(self.sync_out, data, self.thp):
                if (
                    self.__io_progress.end_type.error == 1
                    or self.sync_out.error_occurred()
                ):
                    raise WorkableEx("Workable error was set!")
                yield subtotals
