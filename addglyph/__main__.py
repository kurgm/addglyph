#!/usr/bin/env python
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Optional, cast


from . import version
from .error import AddGlyphUserError
from .inputfile import get_chars_set, get_vs_dict
from .main import addglyph


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def pause() -> None:
    if pause.batch:
        return

    if os.name == "nt":
        os.system("pause")
    else:
        input("Press Enter to continue . . .")


pause.batch = False


def main() -> None:
    argparser = argparse.ArgumentParser(description=(
        "addglyph -- version {version}\n"
        "Adds blank glyphs to a TrueType or OpenType font file."
    ).format(version=version))

    argparser.add_argument(
        "--quiet", "-q", action="store_true",
        help="will not write log message to stderr.")
    argparser.add_argument(
        "--batch", "-b", action="store_true",
        help="will not pause on exit.")

    argparser.add_argument("--version", action="version", version=version)

    argparser.add_argument(
        "-f", metavar="FONTFILE", dest="fontfiles",
        action="append", default=[],
        help="specify a font file to add glyphs to.")
    argparser.add_argument(
        "-t", metavar="TEXTFILE", dest="textfiles",
        action="append", default=[],
        help="specify text files that contain characters to add.")
    argparser.add_argument(
        "-v", metavar="VSFILE", dest="vsfiles",
        action="append", default=[],
        help="specify variation sequence data files.")

    argparser.add_argument(
        "other_files", metavar="FILE", nargs="*",
        help="specify a font file to add glyphs to.")

    argparser.add_argument(
        "-o", metavar="OUTFILE", dest="outfile",
        help="specify the a file to write the output to.")

    argset = argparser.parse_intermixed_args()

    if argset.quiet:
        logging.basicConfig(level=logging.ERROR)

    if argset.batch:
        pause.batch = True

    fontfiles: list[str] = list(argset.fontfiles)
    textfiles: list[str] = list(argset.textfiles)
    vsfiles: list[str] = list(argset.vsfiles)
    outfont: Optional[str] = argset.outfile

    for other_file in cast("list[str]", argset.other_files):
        if other_file[-4:].lower() in (".ttf", ".otf"):
            fontfiles.append(other_file)
        elif os.path.basename(other_file)[:2].lower() == "vs":
            vsfiles.append(other_file)
        else:
            textfiles.append(other_file)

    if not fontfiles:
        argparser.error("no font file specified")
    if len(fontfiles) > 1:
        argparser.error("multiple font files specified")
    fontfile = fontfiles[0]

    if not textfiles and not vsfiles:
        argparser.error("no text files or vs files specified")

    logger.debug("font file = {}".format(fontfile))
    if textfiles:
        logger.debug("text file(s) = {}".format(", ".join(textfiles)))
    if vsfiles:
        logger.debug("VS file(s) = {}".format(", ".join(vsfiles)))
    if outfont is not None:
        logger.debug("out = {}".format(outfont))

    chars = get_chars_set(textfiles)
    vs = get_vs_dict(vsfiles)
    addglyph(fontfile, chars, vs, outfont)


try:
    main()
except AddGlyphUserError as exc:
    logger.exception("An error occurred", exc_info=exc.__cause__)
    sys.exit(2)
except Exception:
    logger.exception("An unexpected error occurred!")
    logger.error("(please report this to @kurgm)")
    sys.exit(1)
finally:
    pause()
