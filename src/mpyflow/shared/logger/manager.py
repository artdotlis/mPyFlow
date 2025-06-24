import json
from io import TextIOWrapper

import sys
import time

from rich.console import Console
from functools import reduce
import queue
import datetime
import logging
import multiprocessing
from dataclasses import dataclass
from mpyflow.shared.constants.message import TIME_FORMAT_REG
from mpyflow.shared.container.message import SyncOutMsg, LMOutputWaitingProcessTypes
from mpyflow.shared.errors.exception import SyncStdoutEx
from mpyflow.shared.container.process import ValueP, CMDictWrapper
from mpyflow.shared.path.create import create_dirs_rec
from multiprocessing import synchronize
from multiprocessing.process import current_process
from multiprocessing.queues import Queue
from pathlib import Path
from typing import final, Callable, Final

type _SyncOutSt = tuple[float, bool]
_MSG_STR: Final[tuple[str, str, str, str]] = ("-", "\\", "|", "/")


@final
class LogManager:
    __slots__ = (
        "__error",
        "__manager_counter",
        "__manager_lock",
        "__queue",
        "__sync_object_manager",
        "__wa_process_attributes",
    )

    def __init__(self, ctx_local: multiprocessing.context.SpawnContext, /) -> None:
        super().__init__()
        self.__manager_counter = ctx_local.Value("i", 0)
        self.__sync_object_manager = CMDictWrapper[str, _SyncOutSt](ctx_local)
        self.__manager_lock = ctx_local.RLock()
        self.__wa_process_attributes = LMOutputWaitingProcessTypes(
            run=ctx_local.Value("i", 0),
            status=ctx_local.Value("i", 0),
            logger_cnt=ctx_local.Value("i", 0),
            started=time.time(),
            id_cnt=ctx_local.Value("i", 1),
        )
        self.__queue: Queue[SyncOutMsg] = ctx_local.Queue()
        self.__error = ctx_local.Value("i", 0)

    @property
    def manager_error(self) -> bool:
        return bool(self.__error.value)

    def set_manager_error(self) -> None:
        with self.__manager_lock:
            self.__error.value = 1

    def write_to_queue(self, msg: SyncOutMsg, /) -> None:
        self.__queue.put(msg)

    def get_from_queue(self) -> SyncOutMsg:
        return self.__queue.get(True, 2)

    @property
    def queue_empty(self) -> bool:
        return self.__queue.empty()

    @property
    def wa_process_attributes(self) -> LMOutputWaitingProcessTypes:
        return self.__wa_process_attributes

    @property
    def manager_done_counter(self) -> ValueP[int]:
        return self.__manager_counter

    @property
    def sync_object_manager(self) -> CMDictWrapper[str, _SyncOutSt]:
        return self.__sync_object_manager

    @property
    def manager_lock(self) -> synchronize.RLock:
        return self.__manager_lock

    @property
    def id_cnt(self) -> int:
        return self.__wa_process_attributes.id_cnt.value

    def zero_status(self) -> None:
        with self.__manager_lock:
            self.__wa_process_attributes.status.value = 0

    @property
    def logger_cnt(self) -> int:
        with self.__manager_lock:
            return self.__wa_process_attributes.logger_cnt.value

    @property
    def run(self) -> bool:
        with self.__manager_lock:
            return bool(self.__wa_process_attributes.run.value >= 1)

    def run_with_update(self, run_par: bool, /) -> bool:
        start_pr = False
        with self.__manager_lock:
            if run_par:
                if self.__wa_process_attributes.status.value == 0:
                    self.__wa_process_attributes.status.value = 1
                    start_pr = True
                    self.__wa_process_attributes.id_cnt.value += 1
                self.__wa_process_attributes.logger_cnt.value += 1
                self.__wa_process_attributes.run.value += 1
            else:
                if self.__wa_process_attributes.run.value <= 0:
                    raise SyncStdoutEx("No logger was started!")
                self.__wa_process_attributes.run.value -= 1
        return start_pr

    def join(self) -> None:
        wait_bool = True
        while wait_bool:
            with self.__manager_lock:
                if not (self.__wa_process_attributes.status.value != 0 or self.run):
                    wait_bool = False
            time.sleep(1.5)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class _LoggingStats:
    errors_cnt: ValueP[int]
    info_cnt: ValueP[int]
    warn_cnt: ValueP[int]
    other_cnt: ValueP[int]


def _logger_switch(log_stats: _LoggingStats, status: int, /) -> None:
    match status:
        case logging.ERROR:
            log_stats.errors_cnt.value += 1
        case logging.WARNING:
            log_stats.warn_cnt.value += 1
        case logging.INFO:
            log_stats.info_cnt.value += 1
        case _:
            log_stats.other_cnt.value += 1


@final
@dataclass(slots=True, frozen=True, kw_only=True)
class _LoggerMsg:
    msg: str
    level: int


@final
@dataclass(slots=True, frozen=True, kw_only=True)
class _LoggerData:
    lock: synchronize.RLock
    queue: Queue[_LoggerMsg]
    running: ValueP[int]
    finished: ValueP[int]


@final
@dataclass(slots=True, frozen=True, kw_only=True)
class _General:
    g_id: int
    step: str
    working_dir: str
    global_manager: LogManager


@final
@dataclass(slots=True, frozen=True, kw_only=True)
class _EndConD:
    flush_stats: ValueP[int]
    flush_log: ValueP[int]


def _print_at_exit(output_stream: TextIOWrapper | None, /) -> None:
    if output_stream is not None:
        output_stream.write("\n")
        output_stream.flush()
        output_stream.close()


def _prog_bar_calc(count: int, prog: float, /) -> str:
    if count <= int(prog):
        return "#"
    return " "


def _check_message(message: SyncOutMsg, /) -> None:
    if message.status < 0 or message.status > 100:
        raise SyncStdoutEx(
            "Status values for the SyncOutMsg type must be floats between 0 and 100!"
        )
    if message.s_id == "":
        raise SyncStdoutEx("Message id ca not be empty!")


def _check_object_status(message: SyncOutMsg, to_check: _SyncOutSt, /) -> None:
    if message.done and to_check[1]:
        SyncStdoutEx("The messaging object was already closed!")
    if message.status < to_check[0]:
        SyncStdoutEx(
            "The messaging object had a higher progress value than stated in the message!"
        )


def _format_global_status(
    act_objects: int, done_objects: int, time_started: float, prog: float, /
) -> str:
    sec = time.time() - time_started
    time_form = TIME_FORMAT_REG.search(str(datetime.timedelta(seconds=sec)))
    prog_bar = "".join(_prog_bar_calc(x_n + 1, prog) for x_n in range(10))
    upt = time_form.group(1) if time_form is not None else "ERROR"
    return f" Uptime: {upt} | {done_objects}/{act_objects} |{prog_bar}|"


class _RichCast:
    __slots__ = ("__formatter",)

    def __init__(self, formatter: Callable[[], str]) -> None:
        super().__init__()
        self.__formatter = formatter

    def __rich__(self) -> str:
        return self.__formatter()


def _print_status(manager: LogManager, /) -> str:
    uptime_loc = manager.wa_process_attributes.started
    with manager.manager_lock:
        act_obj = len(manager.sync_object_manager.managed_dict)
        if act_obj > 0:
            mana = manager.sync_object_manager.managed_dict
            gen = (elem[0] for elem in mana.values())
            prog: float = reduce((lambda x, y: x + y), gen) / (10 * act_obj)
        else:
            prog = 0.0
        msg_st = _format_global_status(
            act_obj, manager.manager_done_counter.value, uptime_loc, prog
        )
        return f"[bold green]{msg_st}"


def _p2c(manager: LogManager, message: SyncOutMsg, console: Console, /) -> None:
    _check_message(message)
    with manager.manager_lock:
        new_act_object = manager.sync_object_manager.managed_dict.get(message.s_id, None)
        if new_act_object is not None:
            _check_object_status(message, new_act_object)
        new_act_object = (message.status, message.done)
        if message.done:
            manager.manager_done_counter.value += 1
        manager.sync_object_manager.managed_dict[message.s_id] = new_act_object
    if len(message.msg) > 5:
        console.log(message.msg)
        time.sleep(1)


def _waiting_output_str(manager: LogManager, /) -> None:
    pid_cur = current_process().pid
    running = True
    cons = Console(log_path=False)
    with cons.status(_RichCast(lambda: _print_status(manager))):
        s_id = f"_OutputWaitingProcess_{pid_cur!s}_{manager.id_cnt!s}"
        sync = SyncOutMsg(s_id=s_id, msg="", status=0.0, done=False)
        _p2c(manager, sync, cons)
        try:
            while running:
                try:
                    erg = manager.get_from_queue()
                except queue.Empty:
                    s_id = f"_OutputWaitingProcess_{pid_cur!s}_{manager.id_cnt!s}"
                    sync = SyncOutMsg(s_id=s_id, msg="", status=0.0, done=False)
                    _p2c(manager, sync, cons)
                else:
                    _p2c(manager, erg, cons)
                running = manager.run or not manager.queue_empty
            out_msg = r"_OutputWaitingProcess \[done]"
            act_obj = len(manager.sync_object_manager.managed_dict) - 1
            act_obj -= manager.manager_done_counter.value
            if act_obj > 0:
                out_msg = f"{out_msg} unfinished objects: {act_obj}"
            s_id = f"_OutputWaitingProcess_{pid_cur!s}_{manager.id_cnt!s}"
            sync = SyncOutMsg(s_id=s_id, msg=out_msg, status=100.0, done=True)
            _p2c(manager, sync, cons)
        except Exception:
            manager.set_manager_error()
            raise
        finally:
            manager.zero_status()
    _print_at_exit(sys.__stdout__)


def _logger_process(
    working_data: _LoggerData, working_dir: Path, step_name: str, /
) -> None:
    logger: logging.Logger = logging.getLogger(step_name)
    logger.setLevel(logging.INFO)

    ch_handler = logging.FileHandler(Path(working_dir).joinpath(f"{step_name}.log"), "w")
    ch_handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(processName)s - %(message)s",
        datefmt="%m/%d/%Y %I:%M:%S %p",
    )

    ch_handler.setFormatter(formatter)

    logger.addHandler(ch_handler)
    running = True
    while running:
        try:
            erg = working_data.queue.get(True, 10)
        except queue.Empty:
            erg = None
        with working_data.lock:
            if working_data.queue.empty() and working_data.running.value == 0:
                running = False
        if erg is not None and isinstance(erg, _LoggerMsg):
            logger.log(erg.level, erg.msg, exc_info=False)

    with working_data.lock:
        working_data.finished.value = 0


def _print_to_sys_out(msg: str, /) -> None:
    syso = sys.__stdout__
    if syso is not None:
        syso.write(msg)
        syso.flush()


@final
class SyncStdout:
    __slots__ = (
        "__end_con",
        "__general",
        "__logger_data",
        "__logging_stats",
        "__procs",
        "__stats",
        "__stats_lock",
    )

    def __init__(
        self,
        step_name: str,
        working_dir: Path,
        ctx_local: multiprocessing.context.SpawnContext,
        log_manager: LogManager,
        /,
    ) -> None:
        super().__init__()
        create_dirs_rec(working_dir)
        self.__logger_data = _LoggerData(
            lock=ctx_local.RLock(),
            queue=ctx_local.Queue(),
            running=ctx_local.Value("i", 1),
            finished=ctx_local.Value("i", 1),
        )
        self.__stats_lock = ctx_local.RLock()
        self.__stats: CMDictWrapper[str, int] = CMDictWrapper[str, int](ctx_local)
        self.__logging_stats: _LoggingStats = _LoggingStats(
            errors_cnt=ctx_local.Value("i", 0),
            info_cnt=ctx_local.Value("i", 0),
            warn_cnt=ctx_local.Value("i", 0),
            other_cnt=ctx_local.Value("i", 0),
        )
        self.__general = _General(
            g_id=log_manager.logger_cnt,
            step=step_name,
            working_dir=str(working_dir),
            global_manager=log_manager,
        )
        self.__end_con: _EndConD = _EndConD(
            flush_stats=ctx_local.Value("i", 1), flush_log=ctx_local.Value("i", 1)
        )
        if self.__general.global_manager.manager_error:
            _logger_switch(self.__logging_stats, logging.ERROR)
            _print_to_sys_out("ERROR occurred in output process (init step)!")
        else:
            log_manager.write_to_queue(
                SyncOutMsg(
                    s_id=f"SyncStdout_{self.__general.g_id!s}",
                    msg=f"SyncStdout_{self.__general.g_id!s} started!",
                    status=0.0,
                    done=False,
                )
            )

    @property
    def logger_data(self) -> _LoggerData:
        return self.__logger_data

    def error_occurred(self) -> bool:
        with self.__stats_lock:
            return bool(self.__logging_stats.errors_cnt.value > 0)

    def print_message(
        self, name: str, message: str, prog: float = 0.0, done: bool = False, /
    ) -> None:
        if self._check_closed():
            raise SyncStdoutEx("The logger was already closed - (message)!")
        if self.__general.global_manager.manager_error:
            _logger_switch(self.__logging_stats, logging.ERROR)
            _print_to_sys_out(
                "ERROR occurred in output process (printing message simple)!"
            )
        else:
            idn = f"SyncStdout_{self.__general.g_id!s}"
            if name != "":
                idn += f"_{name}"
            else:
                prog = 0.0
                done = False
            self.__general.global_manager.write_to_queue(
                SyncOutMsg(s_id=idn, msg=message, status=prog, done=done)
            )

    def print_logger(self, message: str, log_level: int, /) -> None:
        if self._check_closed():
            raise SyncStdoutEx("The logger was already closed - (log)!")
        self.__logger_data.queue.put(_LoggerMsg(msg=message, level=log_level))
        with self.__stats_lock:
            _logger_switch(self.__logging_stats, log_level)

    def save_stats(self, stats_to_merge: dict[str, int], /) -> None:
        if self._check_closed():
            raise SyncStdoutEx("The logger was already closed - (stats)!")
        with self.__stats_lock:
            for key, val in stats_to_merge.items():
                if key not in self.__stats.managed_dict:
                    self.__stats.managed_dict[key] = 0
                self.__stats.managed_dict[key] = self.__stats.managed_dict[key] + val

    # can be flushed several times, but only the first time are the stats saved
    def flush_stats(self) -> None:
        with self.__stats_lock:
            if self.__end_con.flush_stats.value:
                dict_json = {}
                for keys, count in self.__stats.managed_dict.items():
                    dict_json[keys] = count
                if len(dict_json) > 0:
                    with (
                        Path(self.__general.working_dir)
                        .joinpath(f"{self.__general.step}_stats.json")
                        .open("w") as file_hand
                    ):
                        json.dump(dict_json, file_hand, indent=4)
                self.__end_con.flush_stats.value = 0

    def flush_log_stats(self) -> None:
        with self.__stats_lock:
            flushed = self.__end_con.flush_log.value
            self.__end_con.flush_log.value = 0

        if flushed > 0:
            msg = (
                f"Step {self.__general.step!s}: "
                + f"Errors: {self.__logging_stats.errors_cnt.value!s}; "
                + f"Warnings: {self.__logging_stats.warn_cnt.value!s}; "
                + f"Info: {self.__logging_stats.info_cnt.value!s}; "
                + f"Other: {self.__logging_stats.other_cnt.value!s}"
            )

            if self.__general.global_manager.manager_error:
                _logger_switch(self.__logging_stats, logging.ERROR)
                _print_to_sys_out("ERROR occurred in output process (flushing step)!")
            else:
                self.__general.global_manager.write_to_queue(
                    SyncOutMsg(
                        s_id=f"SyncStdout_{self.__general.g_id!s}",
                        msg=msg,
                        status=50.0,
                        done=False,
                    )
                )

    def _check_closed(self) -> bool:
        with self.__stats_lock:
            return (
                self.__end_con.flush_log.value == 0
                and self.__end_con.flush_stats.value == 0
            )

    def _join_logger(self) -> None:
        wait_bool = True
        while wait_bool:
            with self.__logger_data.lock:
                if self.__logger_data.finished.value == 0:
                    wait_bool = False
            time.sleep(1.5)

    # should be used only once
    def close_logger(self) -> None:
        msg = ""
        with self.__stats_lock:
            flush_log = self.__end_con.flush_log.value
            flush_stats = self.__end_con.flush_stats.value
            self.__end_con.flush_log.value = 0
            self.__end_con.flush_stats.value = 0

        if flush_log > 0:
            msg += "The logger log_stats were not flushed!\n"
        if flush_stats > 0:
            msg += "The logger stats were not flushed!\n"
        if flush_stats == 0 and flush_log == 0:
            msg += "The logger was closed correctly!\n"

        if self.__general.global_manager.manager_error:
            _logger_switch(self.__logging_stats, logging.ERROR)
            _print_to_sys_out("ERROR occurred in output process (closing step)!")
        else:
            self.__general.global_manager.write_to_queue(
                SyncOutMsg(
                    s_id=f"SyncStdout_{self.__general.g_id!s}",
                    msg=msg,
                    status=100.0,
                    done=True,
                )
            )

        _ = self.__general.global_manager.run_with_update(False)
        with self.__logger_data.lock:
            self.__logger_data.running.value = 0

        self._join_logger()
        self.__general.global_manager.join()


def factory_log_manager(ctx_local: multiprocessing.context.SpawnContext, /) -> LogManager:
    return LogManager(ctx_local)


def factory_sync_out(
    working_dir: Path,
    step_name: str,
    log_manager: LogManager,
    ctx_local: multiprocessing.context.SpawnContext,
    /,
) -> tuple[tuple[multiprocessing.context.SpawnProcess, ...], SyncStdout]:
    procs: tuple[multiprocessing.context.SpawnProcess, ...] = tuple()
    sync = SyncStdout(step_name, working_dir, ctx_local, log_manager)
    if log_manager.run_with_update(True):
        procs = (ctx_local.Process(target=_waiting_output_str, args=(log_manager,)),)
    procs = (
        *procs,
        ctx_local.Process(
            target=_logger_process, args=(sync.logger_data, working_dir, step_name)
        ),
    )
    return procs, sync
