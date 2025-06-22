from dataclasses import dataclass

from typing import final


@final
@dataclass(slots=True, frozen=True)
class InputData[T]:
    value: T
