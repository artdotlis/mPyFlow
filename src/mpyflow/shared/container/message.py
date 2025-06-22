from dataclasses import dataclass
from mpyflow.shared.container.process import ValueP
from typing import final


@final
@dataclass(slots=True, kw_only=True)
class SyncOutMsg:
    s_id: str
    msg: str
    status: float
    done: bool


@final
@dataclass(slots=True, frozen=True, kw_only=True)
class LMOutputWaitingProcessTypes:
    run: ValueP[int]
    status: ValueP[int]
    logger_cnt: ValueP[int]
    id_cnt: ValueP[int]
    started: float
