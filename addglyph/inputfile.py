from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Iterable, Sequence

from .error import AddGlyphUserError

logger = logging.getLogger(__name__)


class InputFileSyntaxError(Exception):
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
        if isinstance(exc, OSError | UnicodeError | InputFileSyntaxError):
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


class VSFileSyntaxError(InputFileSyntaxError):
    pass


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


GlyphSpec = tuple[int, int | None] | int


class GSUBFileSyntaxError(InputFileSyntaxError):
    pass


def is_vs_char(c: str) -> bool:
    if c in "\u180b\u180c\u180d\u180f":
        return True

    if "\ufe00" <= c <= "\ufe0f":
        return True

    if "\U000e0100" <= c <= "\U000e01ef":
        return True

    return False


glyphspec_gid_re = re.compile(r"\\([0-9]+)")


def parse_glyphspecs(s: str) -> Iterable[GlyphSpec]:
    def tokenize(s: str) -> Iterable[str | int]:
        i = 0
        while i < len(s):
            if m := glyphspec_gid_re.match(s, i):
                yield int(m.group(1))
                i = m.end()
            elif m := entity_re.match(s, i):
                yield decode_entity(m.group(0))
                i = m.end()
            else:
                yield s[i]
                i += 1

    def str_to_glyphspecs(s: str) -> Iterable[tuple[int, int | None]]:
        i = 0
        while i < len(s):
            if i + 1 < len(s) and is_vs_char(s[i + 1]):
                yield ord(s[i]), ord(s[i + 1])
                i += 2
            else:
                yield ord(s[i]), None
                i += 1

    buf = ""
    for token in tokenize(s):
        if isinstance(token, str):
            buf += token
        else:
            if buf:
                yield from str_to_glyphspecs(buf)
                buf = ""
            yield token

    if buf:
        yield from str_to_glyphspecs(buf)


feature_tag_re = re.compile(r"[\x20-\x7f]{4}")


def parse_gsub_line(line: str) -> Iterable[tuple[str, GlyphSpec, GlyphSpec]]:
    row = [decode_entity(col) for col in line.split()]
    if not row:
        # empty line
        return

    if len(row) != 3:
        raise GSUBFileSyntaxError(f"invalid number of columns: {len(row)}")

    feature_tag, input_glyph_str, alternate_glyphs_str = row

    if not feature_tag_re.fullmatch(feature_tag):
        raise GSUBFileSyntaxError(f"invalid feature tag: {feature_tag}")

    input_glyphs = list(parse_glyphspecs(input_glyph_str))
    if len(input_glyphs) != 1:
        raise GSUBFileSyntaxError(f"invalid input glyph: {input_glyph_str}")
    (input_glyph,) = input_glyphs

    for alternate_glyph in parse_glyphspecs(alternate_glyphs_str):
        yield feature_tag, input_glyph, alternate_glyph


def get_gsub_spec(
    gsubfiles: Sequence[str],
) -> dict[str, list[tuple[GlyphSpec, GlyphSpec]]]:
    gsub: dict[str, list[tuple[GlyphSpec, GlyphSpec]]] = {}

    for f in gsubfiles:
        with open_text(f, err_hint="GSUB text file") as file:
            for lineno, line in enumerate(file):
                try:
                    for (
                        feature_tag,
                        input_glyph,
                        alternate_glyph,
                    ) in parse_gsub_line(line):
                        gsub.setdefault(feature_tag, []).append(
                            (input_glyph, alternate_glyph)
                        )
                except GSUBFileSyntaxError as exc:
                    exc.lineno = lineno + 1
                    exc.filename = f
                    raise

    return gsub
