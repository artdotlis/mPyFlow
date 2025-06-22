import atexit
from io import TextIOWrapper

from mpyflow.shared.constants.message import NEW_LINE_REG
from queue import Empty, Queue

import io
import os
import sys
from mpyflow.shared.interfaces.logger import SyncStdoutInterface
from multiprocessing.process import current_process
from threading import Thread
from typing import final, TextIO, Literal


@final
class RedirectWriteToLogger(io.TextIOWrapper):
    __slots__ = ("__sync_out",)

    def __init__(self, sync_out: SyncStdoutInterface, /) -> None:
        dev_nul = open(os.devnull, "wb")  # noqa: PTH123
        atexit.register(dev_nul.close)
        super().__init__(dev_nul)
        self.__sync_out = sync_out

    def write(self, s: str) -> int:
        msg = s
        if [line_msg for line_msg in NEW_LINE_REG.split(msg) if line_msg]:
            self.__sync_out.print_message(
                "",
                f"{current_process().name} ({current_process().pid}):\n\t{msg}",
            )
        return len(msg)


def _writer_thread(
    sync_out: SyncStdoutInterface, queue: Queue[str | Literal[True]], /
) -> None:
    running = True
    wrapper_str = f"Error: {current_process().name} ({current_process().pid}):"
    msg_out = ""
    while running:
        try:
            erg = queue.get(True, 2)
        except Empty:
            erg = None
        if isinstance(erg, bool) and erg is True:
            running = False
        elif isinstance(erg, str):
            new_msg = "\n\t".join(
                line_msg for line_msg in NEW_LINE_REG.split(erg) if line_msg
            )
            if new_msg:
                msg_out += f"\n\t{new_msg}"
    sync_out.print_message("", f"{wrapper_str}{msg_out}")


@final
class RedirectErrorToLogger(io.TextIOWrapper):
    __slots__ = ("__closed", "__queue", "__sync_out", "__writer_thread")

    def __init__(self, sync_out: SyncStdoutInterface, /) -> None:
        dev_nul = open(os.devnull, "wb")  # noqa: PTH123
        atexit.register(dev_nul.close)
        super().__init__(dev_nul)
        self.__sync_out = sync_out
        self.__queue: Queue[str | Literal[True]] = Queue()
        self.__writer_thread: Thread | None = None
        self.__closed = False

    def write(self, s: str) -> int:
        msg = s
        new_msg = "\n".join(line_msg for line_msg in NEW_LINE_REG.split(msg) if line_msg)
        if self.__closed and new_msg:
            self.__sync_out.print_message(
                "",
                f"[red]THE MESSAGE WAS SEND AFTER CLOSING WRITER:\n{new_msg}",
            )
        elif new_msg:
            if self.__writer_thread is None:
                self.__writer_thread = Thread(
                    target=_writer_thread, args=(self.__sync_out, self.__queue)
                )
                self.__writer_thread.start()
            self.__queue.put(msg)

        return len(msg)

    def join_thread(self) -> None:
        if not self.__closed and self.__writer_thread is not None:
            self.__queue.put(True)
            self.__writer_thread.join()
        self.__closed = True


@final
class RedirectSysHandler:
    __slots__ = ("__stderr_buffer", "__stdout_buffer", "__sys_hand_err", "__sys_hand_out")

    def __init__(
        self,
        sync_out: SyncStdoutInterface,
        stderr_buffer: TextIOWrapper | TextIO | None,
        stdout_buffer: TextIOWrapper | TextIO | None,
        /,
    ) -> None:
        super().__init__()
        self.__sys_hand_out = RedirectWriteToLogger(sync_out)
        self.__sys_hand_err = RedirectErrorToLogger(sync_out)
        dev_null = io.TextIOWrapper(open(os.devnull, "wb"))  # noqa: PTH123
        self.__stderr_buffer = stderr_buffer if stderr_buffer is not None else dev_null
        self.__stdout_buffer = stdout_buffer if stdout_buffer is not None else dev_null

    def set_sys_handler(self) -> None:
        sys.stdout = self.__sys_hand_out
        sys.stderr = self.__sys_hand_err

    def on_known_errors(self, msg: str, /) -> None:
        self.__sys_hand_err.write(msg)

    def on_exception(self, msg: str, /) -> None:
        self.__sys_hand_err.write(msg)
        self.__stderr_buffer = io.TextIOWrapper(open(os.devnull, "wb"))  # noqa: PTH123
        atexit.register(self.__stderr_buffer.close)
        sys.stderr = self.__stderr_buffer

    def join_errors(self) -> None:
        self.__sys_hand_err.join_thread()

    def close(self) -> None:
        sys.stdout = self.__stdout_buffer
        sys.stderr = self.__stderr_buffer
        self.__sys_hand_out.close()
        self.__sys_hand_err.join_thread()
        self.__sys_hand_err.close()
