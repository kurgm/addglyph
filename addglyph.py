#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import codecs
import logging
import os
import re
import sys
from tempfile import TemporaryFile

from fontTools.ttLib import TTFont, reorderFontTables
from fontTools.ttLib.tables import _c_m_a_p, _g_l_y_f


version = "2.0"

PY2 = sys.version_info < (3, 0)

hexEntityRe = re.compile(r"&#x([\da-fA-F]+);")
decEntityRe = re.compile(r"&#(\d+);")


if not PY2:
    unichr = chr
    raw_input = input

if sys.maxunicode == 0xFFFF:
    def myunichr(cp):
        if cp <= 0xFFFF:
            return unichr(cp)
        return "\\U{:08x}".format(cp).decode("unicode_escape")

    def iterstr(s):
        return codecs.iterdecode(s.encode("utf-16_be"), encoding="utf-16_be")

    def myord(s):
        if len(s) == 1:
            return ord(s)
        assert len(s) == 2 and "\uD800" <= s[0] < "\uDC00", "Invalid UTF-16 character"
        return int(s.encode("utf-32_be").encode("hex_codec"), 16)

else:
    myunichr = unichr
    iterstr = iter
    myord = ord


def print_help():
    print("""\
usage: {prog} -f fontfile [-t textfile]... [-v vsfile]...

addglyph -- version {version}
Adds blank glyphs to a TrueType or OpenType font file.

Arguments:
  -f fontfile  specify a font file to add glyphs to.
  -t textfile  specify text files that contain characters to add.
  -v vsfile    specify variation sequence data files.

Options:
  -h, --help   print this message and exit.
  --version    print the version and exit.
  -o outfile   specify the a file to write the output to.
  -q, --quiet  will not write log message to stderr.
  -b, --batch  will not pause on exit.
""".format(
        prog=sys.argv[0],
        version=version,
    ))


def decodeEntity(s):
    return hexEntityRe.sub(
        lambda m: myunichr(int(m.group(1), 16)),
        decEntityRe.sub(
            lambda m: myunichr(int(m.group(1), 10)),
            s
        )
    )


def pause():
    if pause.batch:
        return

    if os.name == "nt":
        os.system("pause")
    else:
        raw_input("Press Enter to continue . . .")


pause.batch = False


def get_chars_set(textfiles):
    chars = set()

    for f in textfiles:
        try:
            with codecs.open(f, encoding="utf-8-sig") as infile:
                dat = decodeEntity(infile.read())
        except Exception:
            logging.error("Error while loading text file '{}'".format(f))
            raise
        chars.update(iterstr(dat))

    chars -= {"\t", "\r", "\n"}
    return chars


def parse_vs_line(line):
    row = [decodeEntity(col) for col in line.split()]
    if not row:
        # empty line
        return

    if len(row) > 2:
        raise SyntaxError("invalid number of columns: {}".format(len(row)))
    elif len(row) == 2:
        seq_str, is_default_str = row
    else:
        seq_str = row[0]
        is_default_str = False

    seq = [myord(c) for c in iterstr(seq_str)]
    if len(seq) != 2:
        raise SyntaxError(
            "invalid variation sequence length: {}".format(len(seq)))

    if is_default_str == "D":
        is_default = True
    elif is_default_str == "":
        is_default = False
    else:
        raise SyntaxError(
            "invalid default variation sequence option: {}".format(is_default_str))

    return seq, is_default


def get_vs_dict(vsfiles):
    vs = {}

    for f in vsfiles:
        try:
            with codecs.open(f, encoding="utf-8-sig") as infile:
                for lineno, line in enumerate(infile):
                    try:
                        dat = parse_vs_line(line)
                        if dat is None:
                            # empty line
                            continue
                        seq, is_default = dat
                    except SyntaxError:
                        logging.error(
                            "Error while parsing VS text file line {}".format(lineno + 1))
                        raise
                    vs[seq] = is_default
        except Exception:
            logging.error("Error while loading VS text file '{}'".format(f))
            raise

    return vs


def add_blank_glyph(glyphname, hmtx, vmtx, glyf):
    hmtx[glyphname] = vmtx[glyphname] = (1024, 0)

    glyph = _g_l_y_f.Glyph()
    glyph.xMin = glyph.yMin = glyph.xMax = glyph.yMax = 0
    glyf[glyphname] = glyph


def addglyph(fontfile, chars, vs=[], outfont=None):
    try:
        ttf = TTFont(fontfile)
    except Exception:
        logging.error("Error while loading font file")
        raise

    cmap = ttf["cmap"]
    sub4 = cmap.getcmap(platformID=3, platEncID=1)
    subt = cmap.getcmap(platformID=3, platEncID=10)
    if subt is None:
        assert sub4 is not None, "cmap subtable (format=4) not found"
        subt = _c_m_a_p.CmapSubtable.newSubtable(12)
        subt.platformID = 3
        subt.platEncID = 10
        subt.format = 12
        subt.reserved = 0
        subt.length = 0   # will be recalculated by compiler
        subt.language = 0
        subt.nGroups = 0  # will be recalculated by compiler
        if not hasattr(subt, "cmap"):
            subt.cmap = {}
        subt.cmap.update(sub4.cmap)
        cmap.tables.append(subt)
        logging.info("cmap subtable (format=12) created")

    sub14 = cmap.getcmap(platformID=0, platEncID=5)
    if vs and sub14 is None:
        sub14 = _c_m_a_p.CmapSubtable.newSubtable(14)
        sub14.platformID = 0
        sub14.platEncID = 5
        sub14.format = 14
        sub14.length = 0  # will be recalculated by compiler
        sub14.numVarSelectorRecords = 0  # will be recalculated by compiler
        sub14.language = 0xFF
        sub14.cmap = {}
        sub14.uvsDict = {}

    smap = subt.cmap

    hmtx = ttf["hmtx"]
    vmtx = ttf["vmtx"]
    glyf = ttf["glyf"]

    added_count = 0

    for char in chars:
        codepoint = myord(char)
        if codepoint in smap:
            logging.info("already in font: U+{:04X}".format(codepoint))
            continue

        if codepoint < 0x10000:
            glyphname = "uni{:04X}".format(codepoint)
            if sub4 is not None:
                sub4.cmap.setdefault(codepoint, glyphname)
        else:
            glyphname = "u{:04X}".format(codepoint)

        smap[codepoint] = glyphname

        add_blank_glyph(glyphname, hmtx, vmtx, glyf)

        logging.info("added: U+{:04X}".format(codepoint))
        added_count += 1

    for seq, is_default in vs.items():
        base, selector = seq
        if any(uv == base for uv, gname in sub14.uvsDict.get(selector, [])):
            logging.info(
                "already in font: U+{:04X} U+{:04X}".format(base, selector))
            continue

        if is_default:
            glyphname = None
            logging.info(
                "added: U+{:04X} U+{:04X} as default".format(base, selector))
        else:
            glyphname = "u{:04X}u{:04X}".format(base, selector)
            add_blank_glyph(glyphname, hmtx, vmtx, glyf)

            logging.info(
                "added: U+{:04X} U+{:04X} as non-default".format(base, selector))

        sub14.uvsDict.setdefault(selector, []).append([base, glyphname])
        added_count += 1

    logging.info("{} glyphs added!".format(added_count))
    logging.info("saving...")

    if outfont is None:
        outfont = fontfile[:-4] + "_new" + fontfile[-4:]

    try:
        with TemporaryFile(prefix="add-glyphs") as tmp:
            ttf.save(tmp, reorderTables=False)

            # Bring `glyf` table to the last so that the font can be edited with TTEdit
            logging.info("reordering...")
            tmp.flush()
            tmp.seek(0)
            with open(outfont, "wb") as outfile:
                reorderFontTables(tmp, outfile, tableOrder=[
                    "head", "hhea", "maxp", "post", "OS/2", "name", "gasp", "cvt ", "fpgm",
                    "prep", "cmap", "loca", "hmtx", "mort", "GSUB", "vhea", "vmtx",
                    "glyf"
                ])
    except Exception:
        logging.error("Error while saving font file")
        raise

    logging.info("saved successfully: {}".format(outfont))


def main():
    fontfile = None
    textfiles = []
    vsfiles = []
    outfont = None

    no_arg_types = {"quiet", "batch"}

    args = iter(sys.argv[1:])
    for arg in args:
        if arg[:2] == "--":
            argtype = arg[2:]
            if argtype not in no_arg_types:
                try:
                    f = next(args)
                except StopIteration:
                    raise ValueError(
                        "arguments for the option '{}' is missing".format(argtype))
        elif arg[0] == "-":
            argtype = {
                "f": "font",
                "t": "text",
                "v": "vs",
                "o": "out",
                "q": "quiet",
                "b": "batch",
            }.get(arg[1], arg[1])
            if argtype not in no_arg_types:
                if len(arg) == 2:
                    try:
                        f = next(args)
                    except StopIteration:
                        raise ValueError(
                            "arguments for the option '{}' is missing".format(argtype))
                else:
                    f = arg[2:]
        else:
            f = arg
            if arg[-4:].lower() in (".ttf", ".otf"):
                argtype = "font"
            elif arg[:2].lower() == "vs":
                argtype = "vs"
            else:
                argtype = "text"

        if argtype == "font":
            assert fontfile is None, "multiple font files specified"
            fontfile = f
        elif argtype == "text":
            textfiles.append(f)
        elif argtype == "vs":
            vsfiles.append(f)
        elif argtype == "out":
            outfont = f
        elif argtype == "quiet":
            pass
        elif argtype == "batch":
            pass
        else:
            raise ValueError("unknown option: {}".format(argtype))

    assert fontfile is not None, "no font file specified"
    assert textfiles or vsfiles, "no text files or vs files specified"

    logging.debug("font file = {}".format(fontfile))
    if textfiles:
        logging.debug("text file(s) = {}".format(", ".join(textfiles)))
    if vsfiles:
        logging.debug("VS file(s) = {}".format(", ".join(vsfiles)))
    if outfont is not None:
        logging.debug("out = {}".format(outfont))

    chars = get_chars_set(textfiles)
    vs = get_vs_dict(vsfiles)
    addglyph(fontfile, chars, vs, outfont)


if __name__ == "__main__":
    args = sys.argv[1:]

    if {"-q", "--quiet"}.intersection(args):
        logging.basicConfig(level=logging.ERROR)
    else:
        logging.basicConfig(level=logging.DEBUG)

    if {"-b", "--batch"}.intersection(args):
        pause.batch = True

    if {"-h", "--help"}.intersection(args):
        print_help()
        pause()
        sys.exit(0)

    if "--version" in args:
        print(version)
        pause()
        sys.exit(0)

    try:
        main()
    except Exception:
        logging.exception("An error occurred")
        pause()
        sys.exit(1)
    pause()
