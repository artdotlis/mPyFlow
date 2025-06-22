import asyncio
from concurrent.futures.thread import ThreadPoolExecutor
from mpyflow.shared.container.data import InputData
from mpyflow.shared.decorator.arguments import remove_all_args
from typing import final, Callable
import multiprocessing
from mpyflow.shared.container.process import ValueP
from multiprocessing import synchronize, connection
from dataclasses import dataclass


@final
@dataclass(frozen=True, kw_only=True, slots=True)
class _Locks:
    writer: tuple[synchronize.Lock, ...]
    reader: tuple[synchronize.Lock, ...]


@final
@dataclass(frozen=True, kw_only=True, slots=True)
class _Heads:
    writer: ValueP[int]
    reader: ValueP[int]


@final
@dataclass(frozen=True, kw_only=True, slots=True)
class _BufferStructure:
    locks: _Locks
    heads: _Heads
    pipes: tuple[tuple[connection.Connection, connection.Connection], ...]


def _thread_send(
    data: bytes, buffer: _BufferStructure, max_puf: int, global_lock: synchronize.RLock, /
) -> Callable[[], bool]:
    def thread_send_inner() -> bool:
        head_pos = -1
        conveyable = True
        with global_lock:
            if buffer.heads.reader.value != (buffer.heads.writer.value + 1) % max_puf:
                head_pos = buffer.heads.writer.value
                buffer.heads.writer.value = (buffer.heads.writer.value + 1) % max_puf
            else:
                conveyable = False
        if conveyable:
            with buffer.locks.writer[head_pos]:
                buffer.pipes[head_pos][1].send(data)
            return False
        return True

    return thread_send_inner


def _thread_recv(
    buffer: _BufferStructure, max_puf: int, global_lock: synchronize.RLock, /
) -> Callable[[], bytes | None]:
    def thread_recv_inner() -> bytes | None:
        value_bytes: bytes | None = None
        receivable = True
        with global_lock:
            if buffer.heads.reader.value != buffer.heads.writer.value:
                head_pos = buffer.heads.reader.value
                buffer.heads.reader.value = (buffer.heads.reader.value + 1) % max_puf
            else:
                receivable = False

        if receivable:
            with buffer.locks.reader[head_pos]:
                value_bytes = buffer.pipes[head_pos][0].recv()
        return value_bytes

    return thread_recv_inner


def _check_run(
    lock_global: synchronize.RLock, buffer: _BufferStructure, /
) -> Callable[[], bool]:
    def check_run_inner() -> bool:
        with lock_global:
            if buffer.heads.reader.value == buffer.heads.writer.value:
                return False
        return True

    return check_run_inner


@final
class SyncQueue[IN, OT]:
    __slots__ = (
        "__buffer_structure",
        "__de_ser",
        "__in",
        "__lock_global",
        "__max",
        "__out",
        "__ser",
    )

    def __init__(
        self,
        ctx: multiprocessing.context.SpawnContext,
        puffer_size: int,
        serializer: Callable[[OT], bytes],
        deserializer: Callable[[bytes], IN],
        /,
    ) -> None:
        super().__init__()
        self.__lock_global: synchronize.RLock = ctx.RLock()
        self.__max: int = puffer_size
        self.__ser = serializer
        self.__de_ser = deserializer
        self.__buffer_structure: _BufferStructure = _BufferStructure(
            locks=_Locks(
                writer=tuple(ctx.Lock() for _ in range(self.__max)),
                reader=tuple(ctx.Lock() for _ in range(self.__max)),
            ),
            heads=_Heads(reader=ctx.Value("i", 0), writer=ctx.Value("i", 0)),
            pipes=tuple(ctx.Pipe(False) for _ in range(self.__max)),
        )
        self.__in = True
        self.__out = True

    def has_input(self) -> bool:
        return self.__in

    def has_output(self) -> bool:
        return self.__out

    def wr_on_close(self) -> None:
        pass

    def on_error(self) -> None:
        pass

    # For coroutines etc.!
    async def read(self, th_exec: ThreadPoolExecutor, /) -> InputData[IN] | None:
        values_bytes = await asyncio.get_event_loop().run_in_executor(
            th_exec,
            remove_all_args(
                _thread_recv(self.__buffer_structure, self.__max, self.__lock_global)
            ),
        )
        if values_bytes is None:
            return None
        return InputData(self.__de_ser(values_bytes))

    async def write(self, data: OT, th_exec: ThreadPoolExecutor, /) -> bool:
        erg_write = await asyncio.get_event_loop().run_in_executor(
            th_exec,
            remove_all_args(
                _thread_send(
                    self.__ser(data),
                    self.__buffer_structure,
                    self.__max,
                    self.__lock_global,
                )
            ),
        )
        return erg_write

    async def running(self, th_exec: ThreadPoolExecutor, provider_cnt: int, /) -> bool:
        running: bool = await asyncio.get_event_loop().run_in_executor(
            th_exec,
            remove_all_args(_check_run(self.__lock_global, self.__buffer_structure)),
        )
        return running or provider_cnt != 0
