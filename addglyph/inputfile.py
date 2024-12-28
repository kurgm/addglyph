from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Sequence

from .error import AddGlyphUserError

logger = logging.getLogger(__name__)


class VSFileSyntaxError(Exception):
    def __init__(
        self,
        *args,
        filename: str | None = None,
        lineno: int | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.filename = filename
        self.lineno = lineno

    def __str__(self) -> str:
        if self.filename is None or self.lineno is None:
            return super().__str__()

        return (
            f"file {self.filename!r}, line {self.lineno}: {super().__str__()}"
        )


entity_re = re.compile(r"&#(?:x([0-9a-f]+)|([0-9]+));", re.IGNORECASE)


def decode_entity(s: str) -> str:
    return entity_re.sub(
        lambda m: (
            chr(int(m.group(1), 16))
            if m.group(1)
            else chr(int(m.group(2), 10))
        ),
        s,
    )


@contextlib.contextmanager
def open_text(path: str, *args, err_hint: str = "", **kwargs):
    try:
        with open(path, *args, encoding="utf-8-sig", **kwargs) as file:
            yield file
    except Exception as exc:
        logger.error(
            "Error while loading {err_hint}{path!r}".format(
                err_hint=err_hint + " " if err_hint else "", path=path
            )
        )
        if isinstance(exc, OSError | UnicodeError | VSFileSyntaxError):
            raise AddGlyphUserError() from exc
        else:
            raise


def get_chars_set(textfiles: Sequence[str]) -> set[str]:
    chars: set[str] = set()

    for f in textfiles:
        with open_text(f, err_hint="text file") as file:
            for line in file:
                chars.update(decode_entity(line))

    chars -= {"\t", "\r", "\n"}
    return chars


def parse_vs_line(line: str) -> tuple[tuple[int, int], bool] | None:
    row = [decode_entity(col) for col in line.split()]
    if not row:
        # empty line
        return None

    if len(row) > 2:
        raise VSFileSyntaxError(f"invalid number of columns: {len(row)}")
    elif len(row) == 2:
        seq_str, is_default_str = row
    else:
        seq_str = row[0]
        is_default_str = ""

    seq = tuple([ord(c) for c in seq_str])
    if len(seq) != 2:
        raise VSFileSyntaxError(
            f"invalid variation sequence length: {len(seq)}"
        )

    if is_default_str == "D":
        is_default = True
    elif is_default_str == "":
        is_default = False
    else:
        raise VSFileSyntaxError(
            f"invalid default variation sequence option: {is_default_str}"
        )

    return seq, is_default


def get_vs_dict(vsfiles: Sequence[str]) -> dict[tuple[int, int], bool]:
    vs: dict[tuple[int, int], bool] = {}

    for f in vsfiles:
        with open_text(f, err_hint="VS text file") as file:
            for lineno, line in enumerate(file):
                try:
                    dat = parse_vs_line(line)
                except VSFileSyntaxError as exc:
                    exc.lineno = lineno + 1
                    exc.filename = f
                    raise
                if dat is None:
                    # empty line
                    continue
                seq, is_default = dat
                vs[seq] = is_default

    return vs
