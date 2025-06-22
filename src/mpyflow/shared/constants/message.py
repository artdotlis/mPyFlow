import re
from re import Pattern

from typing import Final

NEW_LINE_REG: Final[Pattern[str]] = re.compile(r"\n")
TIME_FORMAT_REG: Final[Pattern[str]] = re.compile(r"(.*\d+:\d+:\d+)\..*$")
