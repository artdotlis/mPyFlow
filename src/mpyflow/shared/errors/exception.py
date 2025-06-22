from typing import final


class KnownException(Exception):
    __slots__ = ("__message",)

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.__message = message

    @final
    @property
    def message(self) -> str:
        return self.__message


@final
class BootstrapEx(KnownException):
    pass


@final
class SyncStdoutEx(KnownException):
    pass


@final
class WorkerEx(KnownException):
    pass


@final
class WorkableEx(KnownException):
    pass


@final
class IOProgressEx(KnownException):
    pass
