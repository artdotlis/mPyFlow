from mpyflow.shared.container.message import SyncOutMsg, LMOutputWaitingProcessTypes
from mpyflow.shared.container.process import CMDictWrapper, ValueP
from multiprocessing import synchronize
from typing import Protocol

type _SyncOutSt = tuple[float, bool]


class SyncStdoutInterface(Protocol):
    def error_occurred(self) -> bool: ...
    def print_message(
        self, name: str, msg: str, prog: float = 0.0, done: bool = False, /
    ) -> None: ...
    def print_logger(self, message: str, log_level: int, /) -> None: ...
    def save_stats(self, stats_to_merge: dict[str, int], /) -> None: ...
    def flush_stats(self) -> None: ...
    def flush_log_stats(self) -> None: ...
    def close_logger(self) -> None: ...


class LogManagerInterface(Protocol):
    @property
    def manager_error(self) -> bool: ...
    def set_manager_error(self) -> None: ...
    def write_to_queue(self, msg: SyncOutMsg, /) -> None: ...
    def get_from_queue(self) -> SyncOutMsg: ...
    @property
    def queue_empty(self) -> bool: ...
    @property
    def wa_process_attributes(self) -> LMOutputWaitingProcessTypes: ...
    @property
    def manager_done_counter(self) -> ValueP[int]: ...
    @property
    def sync_object_manager(self) -> CMDictWrapper[str, _SyncOutSt]: ...
    @property
    def manager_lock(self) -> synchronize.RLock: ...
    @property
    def id_cnt(self) -> int: ...
    def zero_status(self) -> None: ...
    @property
    def logger_cnt(self) -> int: ...
    @property
    def run(self) -> bool: ...
    def run_with_update(self, run_par: bool, /) -> bool: ...
    def join(self) -> None: ...
