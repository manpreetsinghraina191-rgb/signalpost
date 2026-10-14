"""Norwegian organisasjonsnummer validation (9 digits, MOD11 check digit)."""

import re

_WEIGHTS = (3, 2, 7, 6, 5, 4, 3, 2)


def normalize(raw: str) -> str:
    return re.sub(r"[\s.\-]", "", str(raw)).removeprefix("NO").removesuffix("MVA")


def is_valid(orgnr: str) -> bool:
    if not re.fullmatch(r"[89]\d{8}", orgnr):
        return False
    remainder = sum(int(d) * w for d, w in zip(orgnr[:8], _WEIGHTS)) % 11
    check = 0 if remainder == 0 else 11 - remainder
    return check != 10 and check == int(orgnr[8])
