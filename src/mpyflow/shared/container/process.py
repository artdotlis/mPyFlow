from multiprocessing import context
from multiprocessing.managers import SyncManager
from typing import Protocol, final


class ValueP[T](Protocol):
    value: T


@final
class CMDictWrapper[K, V]:
    __slots__ = ("__managed_dict",)

    def __init__(
        self, ctx: context.SpawnContext, manager: SyncManager | None = None, /
    ) -> None:
        super().__init__()
        manager_local = ctx.Manager() if manager is None else manager
        self.__managed_dict: dict[K, V] = manager_local.dict({})  # type: ignore

    @property
    def managed_dict(self) -> dict[K, V]:
        return self.__managed_dict
