from mpyflow.library.workable.element import Workable
from mpyflow.shared.interfaces.logger import SyncStdoutInterface
from typing import final, Any, Iterable


@final
class WorkableManager[IN, OT]:

    __slots__ = ("__read_from", "__write_to")

    def __init__(
        self,
        workable_in: tuple[Workable[IN, Any], ...],
        workable_out: tuple[Workable[Any, OT], ...],
        /,
    ) -> None:
        super().__init__()
        self.__read_from: tuple[Workable[IN, Any], ...] = workable_in
        self.__write_to: tuple[Workable[Any, OT], ...] = workable_out

    @property
    def workable_in(self) -> tuple[Workable[IN, Any], ...]:
        return self.__read_from

    @property
    def workable_out(self) -> tuple[Workable[Any, OT], ...]:
        return self.__write_to

    def _run_registration(self) -> Iterable[Workable[Any, Any]]:
        yield from self.workable_in
        yield from self.workable_out

    def register_output(self, sync: SyncStdoutInterface, /) -> None:
        for work in self._run_registration():
            work.register_output(sync)

    def set_error_in_workables(self) -> None:
        for pr_workable in self.__read_from:
            pr_workable.workable_set_error()
        for re_workable in self.__write_to:
            re_workable.workable_set_error()

    def provider_process_started(self) -> None:
        for re_workable in self.__write_to:
            re_workable.workable_add_provider()

    def provider_process_stopped(self) -> None:
        for write_to in self.__write_to:
            write_to.workable_remove_provider()
            write_to.workable_shutdown()
        for read_from in self.__read_from:
            read_from.workable_on_close()
            read_from.workable_shutdown()
