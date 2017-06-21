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
        assert len(s) == 2 and "\uD800" <= s[0] < "\uDC00"
        return int(s.encode("utf-32_be").encode("hex_codec"), 16)

else:
    myunichr = unichr
    iterstr = iter
    myord = ord


def decodeEntity(s):
    return hexEntityRe.sub(
        lambda m: myunichr(int(m.group(1), 16)),
        decEntityRe.sub(
            lambda m: myunichr(int(m.group(1), 10)),
            s
        )
    )


def pause():
    if os.name == "nt":
        os.system("pause")
    else:
        raw_input("Press Enter to continue . . .")


def get_chars_set(textfiles):
    chars = set()

    for f in textfiles:
        try:
            with codecs.open(f, encoding="utf-8-sig") as infile:
                dat = decodeEntity(infile.read())
        except:
            logging.error("Error while loading text file '{}'".format(f))
            raise
        chars.update(iterstr(dat))

    chars -= {"\t", "\r", "\n"}
    return chars


def get_ivs_dict(ivsfiles):
    ivs = {}

    for f in ivsfiles:
        try:
            with codecs.open(f, encoding="utf-8-sig") as infile:
                for line in infile:
                    line = decodeEntity(line)
                    # TODO
        except:
            logging.error("Error while loading IVS text file '{}'".format(f))
            raise

    return ivs


def addglyph(fontfile, chars, ivs=[]):
    try:
        ttf = TTFont(fontfile)
    except:
        logging.error("Error while loading font file")
        raise

    cmap = ttf["cmap"]
    sub4 = cmap.getcmap(platformID=3, platEncID=1)
    subt = cmap.getcmap(platformID=3, platEncID=10)
    if subt is None:
        assert sub4 is not None, "cmap subtable (format=4) not found"
        subt = _c_m_a_p.cmap_format_12(12)
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

        hmtx[glyphname] = vmtx[glyphname] = (1024, 0)

        glyph = _g_l_y_f.Glyph()
        glyph.xMin = glyph.yMin = glyph.xMax = glyph.yMax = 0
        glyf[glyphname] = glyph

        logging.info("added: U+{:04X}".format(codepoint))
        added_count += 1

    logging.info("{} glyphs added!".format(added_count))
    logging.info("saving...")

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
    except:
        logging.error("Error while saving font file")
        raise

    logging.info("saved successfully: {}".format(outfont))


def main():
    fontfile = None
    textfiles = []
    ivsfiles = []

    args = iter(sys.argv[1:])
    for arg in args:
        if arg[:2] == "--":
            argtype = arg[2:]
            f = next(args)
        elif arg[0] == "-":
            argtype = {
                "f": "font",
                "t": "text",
                "i": "ivs",
            }.get(arg[1], arg[1])
            if len(arg) == 2:
                f = next(args)
            else:
                f = arg[2:]
        else:
            f = arg
            if arg[-4:].lower() in (".ttf", ".otf"):
                argtype = "font"
            elif arg[:3].lower() == "ivs":
                argtype = "ivs"
            else:
                argtype = "text"

        if argtype == "font":
            assert fontfile is None, "multiple font files specified"
            fontfile = f
        elif argtype == "text":
            textfiles.append(f)
        elif argtype == "ivs":
            ivsfiles.append(f)
        else:
            raise "unknown option: {}".format(argtype)

    assert fontfile is not None, "no font file specified"
    assert textfiles, "no text files specified"

    logging.debug("font file = {}".format(fontfile))
    logging.debug("text file(s) = {}".format(", ".join(textfiles)))
    if ivsfiles:
        logging.debug("ivs file(s) = {}".format(", ".join(ivsfiles)))

    chars = get_chars_set(textfiles)
    ivs = get_ivs_dict(ivsfiles)
    addglyph(fontfile, chars, ivs)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    try:
        main()
    except:
        logging.exception("An error occurred")
        pause()
        sys.exit(1)
    pause()
