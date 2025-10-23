# mPyFlow

[![release: 0.2.0](https://img.shields.io/badge/rel-0.2.0-blue.svg?style=flat-square)](https://github.com/artdotlis/mPyFlow)

[![MIT LICENSE](https://img.shields.io/badge/License-MIT-brightgreen.svg?style=flat-square)](https://choosealicense.com/licenses/mit/)
[![Documentation Status](https://img.shields.io/badge/docs-GitHub-blue.svg?style=flat-square)](https://artdotlis.github.io/mPyFlow/)

[![main](https://github.com/artdotlis/mPyFlow/actions/workflows/main.yml/badge.svg?branch=main)](https://github.com/artdotlis/mPyFlow/actions/workflows/main.yml)

---

mPyFlow is a lightweight Python library to help define, run and manage multiprocessing workflows. It provides primitives to compose tasks, express dependencies, and execute them using multiple processes.

## Features
- Simple API to define tasks and workflows
- Support for task dependencies and result collection
- Runs tasks in parallel using Python multiprocessing
- Small and easy to extend


## Installation
Install from source (recommended for development):

```bash
git clone https://github.com/artdotlis/mPyFlow.git
cd mPyFlow
pip install -e .
```

Or install directly from the repository:

```bash
pip install git+https://github.com/artdotlis/mPyFlow.git
```


## Installation - Development

### Prerequisites

- **GNU/Linux**
- **Docker (optional)**
- **Docker Compose (optional)**
- **Dev Container CLI (optional)**

### Steps

1. Clone the repository:
   ```sh
   git clone https://github.com/LeibnizDSMZ/cafi.git
   cd cafi
   ```

#### Docker

2. If using Docker, start the development container manually or use VSCode:
   ```sh
   devcontainer up --workspace-folder .
   devcontainer exec --workspace-folder . bash
   ```

3. Create and activate a virtual environment (inside docker the container):
   ```sh
   make dev
   make runAct
   ```

#### Local

2. Create and activate a virtual environment:
   ```sh
   python -m venv .venv
   source .venv/bin/activate
   ```
3. Install the dependencies:
   ```sh
   pip install .
   pip install -r configs/dev/requirements.dev.txt
   pip install -r configs/dev/requirements.test.txt
   pip install -r configs/dev/requirements.docs.txt
   ```

---

## Quick example

```python
import asyncio
from pathlib import Path
from multiprocessing import get_context
from typing import Optional, Any, AsyncIterator
from queue import Empty

# Import mPyFlow primitives
from mpyflow.library.worker import Worker
from mpyflow.library.workable.element import Workable
from mpyflow.run_wrapper import start_worker
from mpyflow.shared.container.data import InputData


#
# Minimal WorkInterface implementations (used by Workable)
#
class PassthroughWork:
    """WorkInterface: yield exactly the input value (no transform)."""

    def on_close(self, sync_out, /) -> None:
        # called when provider finishes
        pass

    async def work(self, sync_out, data: str, thread_pool) -> AsyncIterator[str]:
        # simple async generator producing the same data
        yield data


class UpperCaseWork:
    """WorkInterface: transform the input to uppercase and yield it."""

    def on_close(self, sync_out, /) -> None:
        pass

    async def work(self, sync_out, data: str, thread_pool) -> AsyncIterator[str]:
        yield data.upper()


class NoopWork:
    """WorkInterface for output-only Workable (not used, but required by API)."""

    def on_close(self, sync_out, /) -> None:
        pass

    async def work(self, sync_out, data: Any, thread_pool) -> AsyncIterator[Any]:
        if False:
            yield None  # never used


#
# Minimal in-memory IO implementations conforming to IOInterface
#
class MemorySource:
    """An IO-like object that can be read from (has_input=True, has_output=False)."""

    def __init__(self, items: list[str]) -> None:
        self._items = list(items)
        self._closed = False

    def has_input(self) -> bool:
        return True

    def has_output(self) -> bool:
        return False

    def wr_on_close(self) -> None:
        self._closed = True

    def on_error(self) -> None:
        self._closed = True

    async def read(self, _thread_pool) -> Optional[InputData[str]]:
        if not self._items:
            return None
        # return InputData wrapper expected by Workable.read
        item = self._items.pop(0)
        print(f"read from memory - {len(self._items)} - {item}")
        return InputData(item)

    async def write(self, _data: Any, _thread_pool) -> bool:
        raise NotImplementedError("Source does not implement write")

    async def running(self, _thread_pool, _provider_cnt: int) -> bool:
        # still 'running' while there are items available
        return len(self._items) > 0


# IOInterface signature expects (thread_pool) argument on async methods
class MemoryQueue:
    """A multiprocessing-safe in-memory queue implementing the IOInterface."""

    def __init__(self, ctx, /) -> None:
        # Use the provided spawn context to create an IPC queue that is safe
        # to share with child processes.
        self._queue = ctx.Queue()
        self._closed = False

    def has_input(self) -> bool:
        # This IO supports being read from
        return True

    def has_output(self) -> bool:
        # This IO also supports being written into
        return True

    def wr_on_close(self) -> None:
        self._closed = True

    def on_error(self) -> None:
        self._closed = True

    # synchronous helpers (run in executor)
    def _get_nowait(self) -> Optional[InputData[Any]]:
        try:
            item = self._queue.get_nowait()
        except Empty:
            return None
        else:
            return InputData(item)

    def _put_nowait(self, data: Any) -> bool:
        # put_nowait delegates to put(block=False)
        self._queue.put_nowait(data)
        return True

    def _running_blocking(self, provider_cnt: int) -> bool:
        # Multiprocessing.Queue.empty() can be unreliable in some platforms,
        # but is acceptable for signalling here: running while items exist or
        # providers remain.
        try:
            q_empty = self._queue.empty()
        except Exception:
            # If empty() fails for some reason, be conservative and assume running
            return provider_cnt > 0
        return (not q_empty) or (provider_cnt > 0)

    async def read(self, thread_pool) -> Optional[InputData[Any]]:
        """
        Non-blocking read: returns InputData if available, otherwise None.

        The Workable machinery expects read() to be non-blocking (it handles
        waiting for providers via its locks/conditions), so we call the
        non-blocking get_nowait inside the provided thread_pool.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(thread_pool, self._get_nowait)

    async def write(self, data: Any, thread_pool) -> bool:
        """
        Write an item into the queue. This will return False when the item
        has been accepted.
        """
        loop = asyncio.get_running_loop()
        return not await loop.run_in_executor(thread_pool, lambda: self._put_nowait(data))

    async def running(self, thread_pool, provider_cnt: int) -> bool:
        """
        Indicate whether this IO is still 'running' from the reader's view:
        i.e. there are items available or there are provider processes left.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(thread_pool, lambda: self._running_blocking(provider_cnt))


class PrintSinkIO:
    """An IO-like sink that prints incoming items when written to."""

    def __init__(self) -> None:
        self._closed = False

    def has_input(self) -> bool:
        return False

    def has_output(self) -> bool:
        return True

    def wr_on_close(self) -> None:
        self._closed = True

    def on_error(self) -> None:
        self._closed = True

    async def read(self, _thread_pool) -> Optional[InputData[Any]]:
        raise NotImplementedError("Sink cannot be read from")

    async def write(self, data: Any, _thread_pool) -> bool:
        # Print the final value (the worker will call this in child process)
        print(f"[sink] received: {data!r}")
        return False

    async def running(self, _thread_pool, _provider_cnt: int) -> bool:
        # Sink itself does not drive readers
        return False


def main() -> None:
    # Build the spawn context used by Workable to create shared primitives
    factory_ctx = get_context("spawn")

    # 1) Create IO / Work instances
    # Source with items we want to process
    source_io = MemorySource(["hello", "world", "mpyflow"])
    source_work = PassthroughWork()  # yields items unchanged

    # Processor: queue IO + uppercase work
    queue_io = MemoryQueue(factory_ctx)
    upper_work = UpperCaseWork()

    # Final sink IO (prints values)
    sink_io = PrintSinkIO()
    sink_work = NoopWork()

    # 2) Wrap them into Workable objects (the library expects Workable instances)
    #    Note: Workable requires the spawn context (ctx) as first parameter
    provider_workable = Workable(factory_ctx, source_work, source_io)
    processor_workable = Workable(factory_ctx, upper_work, queue_io)
    sink_workable = Workable(factory_ctx, sink_work, sink_io)

    # 3) Create Worker definitions:
    # - reader: reads from provider -> works via PassthroughWork -> writes to processor
    # - writer: reads from processor -> (processor's work yields uppercase) -> writes to sink
    reader_worker = Worker("reader", (provider_workable,), (processor_workable,))
    writer_worker = Worker("writer", (processor_workable,), (sink_workable,))

    # 4) Logs directory (runner will create a timestamped subdirectory)
    log_base = Path("/tmp/mpyflow_example")

    # 5) Start the flow
    start_worker(
        log_base,
        "readme_example",
        factory_ctx,
        ((1, reader_worker), (1, writer_worker)),
        (provider_workable, processor_workable, sink_workable),
    )


if __name__ == "__main__":
    main()
```
