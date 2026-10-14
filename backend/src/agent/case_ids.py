"""Shared case identifier parsing, including IDs adjacent to Chinese prose."""
import re
from typing import Annotated

from pydantic import AfterValidator, Field

MAX_CASE_IDS = 30
CaseId = Annotated[str, Field(pattern=r"^[Cc]-[0-9A-Fa-f]{16}$"), AfterValidator(str.upper)]
_PATTERN = re.compile(r"(?<![a-z0-9])C-[0-9a-f]{16}(?![a-z0-9])", re.I)


def case_ids_in(text: str) -> list[str]:
    return list(dict.fromkeys(value.upper() for value in _PATTERN.findall(text)))
