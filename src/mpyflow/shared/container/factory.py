import multiprocessing
from dataclasses import dataclass, field
from mpyflow.shared.interfaces.logger import LogManagerInterface
from mpyflow.shared.interfaces.work import WorkableTermInterface
from typing import final, Iterable

type _MPC = multiprocessing.context.SpawnProcess


@final
@dataclass(slots=True, kw_only=True)
class ProcessCon:
    log_manager: LogManagerInterface
    workable: tuple[WorkableTermInterface, ...]
    worker_process: tuple[_MPC, ...] = field(default_factory=tuple)
    extra_process: tuple[_MPC, ...] = field(default_factory=tuple)

    def add_new_workers(self, work: Iterable[_MPC], /) -> None:
        self.worker_process = (*self.worker_process, *work)

    def add_new_procs(self, proc: Iterable[_MPC], /) -> None:
        self.extra_process = (*self.extra_process, *proc)
