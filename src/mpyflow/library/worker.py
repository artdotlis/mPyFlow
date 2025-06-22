import sys
import random
from dataclasses import dataclass
import asyncio
import logging
import traceback
from mpyflow.library.workable.element import Workable
from mpyflow.library.workable.manager import WorkableManager
from mpyflow.shared.errors.exception import KnownException, WorkerEx

from multiprocessing.process import current_process
from mpyflow.shared.interfaces.logger import SyncStdoutInterface
from mpyflow.shared.logger.redirect import RedirectSysHandler
from typing import final, Any

type _RoutineReturnA = tuple[
    int | BaseException, int | BaseException, BaseException | None
]


@final
@dataclass(slots=True, frozen=True, kw_only=True)
class _EventQueues[IN, OT]:
    reader_queue: asyncio.queues.Queue[tuple[int, IN]]
    worker_queue: asyncio.queues.Queue[OT]
    stop_event_reader: asyncio.locks.Event
    stop_event_worker: asyncio.locks.Event
    stop_event_error: asyncio.locks.Event


async def _await_job(queue: asyncio.Queue[Any], event: asyncio.Event, /) -> None:
    job_done = False
    while not (event.is_set() or job_done):
        try:
            await asyncio.wait_for(queue.join(), timeout=1)
        except asyncio.TimeoutError:
            pass
        else:
            job_done = True


@final
class Worker[IN, OT]:
    __slots__ = ("__error", "__evq", "__hub", "__name", "__sha", "__syo", "__wm")

    def __init__(
        self,
        name: str,
        workable_in: tuple[Workable[IN, Any], ...],
        workable_out: tuple[Workable[Any, OT], ...],
        hub: bool = False,
        /,
    ) -> None:
        super().__init__()
        self.__name = name
        self.__syo: SyncStdoutInterface | None = None
        self.__sha: RedirectSysHandler | None = None
        self.__wm: WorkableManager[IN, OT] = WorkableManager(workable_in, workable_out)
        self.__evq: _EventQueues[IN, OT] | None = None
        self.__error: bool = False
        self.__hub = hub

    def register_worker(self, sync_out: SyncStdoutInterface, /) -> None:
        self.__wm.provider_process_started()
        if self.__syo is None:
            self.__syo = sync_out
            self.__wm.register_output(sync_out)

    @property
    def evq(self) -> _EventQueues[IN, OT]:
        if self.__evq is None:
            self.__evq = _EventQueues(
                reader_queue=asyncio.Queue(),
                worker_queue=asyncio.Queue(),
                stop_event_reader=asyncio.Event(),
                stop_event_worker=asyncio.Event(),
                stop_event_error=asyncio.Event(),
            )
        return self.__evq

    @property
    def name(self) -> str:
        return f"{self.__name}_{current_process().pid!s}"

    @property
    def sync_out(self) -> SyncStdoutInterface:
        if self.__syo is None:
            raise WorkerEx("Output not set!")
        return self.__syo

    def __start_redirect(self) -> None:
        sys_handlers = RedirectSysHandler(self.sync_out, sys.stdout, sys.stderr)
        sys_handlers.set_sys_handler()
        self.__sha = sys_handlers

    def __stop_redirect(self) -> None:
        if self.__sha is not None:
            self.__sha.close()

    def __handle_error(self, error: Exception, report: bool, /) -> None:
        self.__error = True
        msg = ("Expected" if isinstance(error, KnownException) else "Not expected",)
        self.sync_out.print_logger(
            f"{msg} error: {error!s} in {self.name}\n{traceback.format_exc()}",
            logging.ERROR,
        )
        if self.__sha is not None and report:
            reporter = self.__sha.on_exception
            if isinstance(error, KnownException):
                reporter = self.__sha.on_known_errors
            reporter(str(error))
        if not isinstance(error, KnownException):
            raise error

    def __finished(self, p_name: str, counter_read: int, counter_write: int, /) -> None:

        self.sync_out.save_stats(
            {f"{self.__name}_in": counter_read, f"{self.__name}_out": counter_read}
        )
        if not self.sync_out.error_occurred():
            msg = f"[{self.name}] elements received: {counter_read!s}"
            self.sync_out.print_logger(msg, logging.INFO)
            msg = f"[{self.name}] elements send: {counter_write!s}"
            self.sync_out.print_logger(msg, logging.INFO)
            msg = f"Worker {self.name} ({p_name}) \\[done]"
            self.sync_out.print_message(self.name, msg, 100.0, True)
            self.__wm.provider_process_stopped()

    def __print_con(self, p_name: str, p_typ: str, cnt: int, /) -> None:
        msg = (
            f"{p_name} process_{p_typ} {self.name} "
            + f"workable_running, {cnt!s}-th element!"
        )
        self.sync_out.print_message(self.name, msg, 0.0, False)

    async def __read(
        self, p_name: str, rpl: list[int], re_cnt: int, lac: int, reader_len: int, /
    ) -> tuple[int, int]:
        if len(rpl) == 0:
            rpl = list(range(0, reader_len))
        pos_puf = random.randint(0, len(rpl) - 1)  # noqa: S311
        reader_pointer: int = rpl[pos_puf]
        del rpl[pos_puf]
        if await self.__wm.workable_in[reader_pointer].workable_running():
            val_new = await self.__wm.workable_in[reader_pointer].workable_read()
            cnt_buf = re_cnt
            if val_new is not None:
                self.__print_con(p_name, "read", re_cnt + 1)
                await _await_job(self.evq.reader_queue, self.evq.stop_event_error)
                await self.evq.reader_queue.put((reader_pointer, val_new.value))
                cnt_buf += 1
            return cnt_buf, lac
        else:
            return re_cnt, lac + 1

    async def __reader(self, p_name: str, /) -> int:
        rpl: list[int] = []
        last_active = 0
        reader_len = len(self.__wm.workable_in)
        counter_read = 0
        try:
            while last_active < reader_len and not self.evq.stop_event_error.is_set():
                counter_read, last_active = await self.__read(
                    p_name, rpl, counter_read, last_active, reader_len
                )
        except Exception:
            self.evq.stop_event_error.set()
            raise
        finally:
            self.evq.stop_event_reader.set()
        return counter_read

    async def __work(self, erg: tuple[int, IN], /) -> None:
        self.evq.reader_queue.task_done()
        ind, data = erg
        async for list_worked in self.__wm.workable_in[ind].workable_work(data):
            if sum(len(list_elem) for list_elem in list_worked):
                await _await_job(self.evq.worker_queue, self.evq.stop_event_error)
                await self.evq.worker_queue.put(list_worked)
            if self.evq.stop_event_error.is_set():
                break

    async def __worker(self) -> None:
        try:
            while not (
                (self.evq.stop_event_reader.is_set() and self.evq.reader_queue.empty())
                or self.evq.stop_event_error.is_set()
            ):
                try:
                    erg: tuple[int, IN] = await asyncio.wait_for(
                        self.evq.reader_queue.get(), timeout=1
                    )
                except asyncio.TimeoutError:
                    pass
                else:
                    await self.__work(erg)
        except Exception:
            self.evq.stop_event_error.set()
            raise
        finally:
            self.evq.stop_event_worker.set()

    async def __write_to_one(self, erg: OT, wpl: list[int], writer_len: int, /) -> None:
        if len(wpl) == 0:
            wpl = list(range(0, writer_len))
        wpl_ind = random.randint(0, len(wpl) - 1)  # noqa: S311
        while await self.__wm.workable_out[wpl[wpl_ind]].workable_write(erg):
            wpl_ind = (wpl_ind + 1) % len(wpl)
        self.evq.worker_queue.task_done()
        del wpl[wpl_ind]

    async def __write_to_all(self, erg: OT, writer_len: int, /) -> None:
        pointers = list(range(0, writer_len))
        while len(pointers) > 0:
            local_pointer = random.choice(pointers)  # noqa: S311
            while await self.__wm.workable_out[local_pointer].workable_write(erg):
                local_pointer = random.choice(pointers)  # noqa: S311
            pointers.remove(local_pointer)
        self.evq.worker_queue.task_done()

    async def __writer(self, p_name: str, /) -> int:
        counter_write = 0
        wpl: list[int] = []
        writer_len = len(self.__wm.workable_out)
        try:
            while not (
                (self.evq.stop_event_worker.is_set() and self.evq.worker_queue.empty())
                or self.evq.stop_event_error.is_set()
            ):
                try:
                    erg: OT = await asyncio.wait_for(
                        self.evq.worker_queue.get(), timeout=1
                    )
                except asyncio.TimeoutError:
                    pass
                else:
                    counter_write += 1
                    self.__print_con(p_name, f"write_hub_{self.__hub}", counter_write)
                    if self.__hub:
                        await self.__write_to_all(erg, writer_len)
                    else:
                        await self.__write_to_one(erg, wpl, writer_len)
        except Exception:
            self.evq.stop_event_error.set()
            raise
        return counter_write

    async def __start_coroutines(self, p_name: str, /) -> _RoutineReturnA:
        self.evq.stop_event_worker.clear()
        self.evq.stop_event_reader.clear()
        self.evq.stop_event_error.clear()
        erg = await asyncio.gather(
            self.__reader(p_name),
            self.__writer(p_name),
            self.__worker(),
            return_exceptions=True,
        )
        return erg

    def run(self) -> None:
        try:
            self.__start_redirect()
            p_name = str(current_process().name)
            output = asyncio.run(self.__start_coroutines(p_name))
            for p_err in output:
                if not isinstance(p_err, Exception):
                    continue
                self.__handle_error(p_err, isinstance(p_err, KnownException))
            counter_read, counter_write, *_ = output
        except KnownException as known_error:
            self.__handle_error(known_error, True)
        except Exception as error:
            self.__handle_error(error, True)
        else:
            if not (isinstance(counter_read, int) and isinstance(counter_write, int)):
                self.__handle_error(WorkerEx("Fatal flow error!"), True)
            else:
                self.__finished(p_name, counter_read, counter_write)
        finally:
            if self.__error:
                self.__wm.set_error_in_workables()
            self.__stop_redirect()
