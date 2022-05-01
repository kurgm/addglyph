#!/usr/bin/env python
import argparse
import logging
import os
import re
import sys
from tempfile import TemporaryFile
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple, cast

from fontTools.ttLib import TTFont, reorderFontTables
from fontTools.ttLib.tables import _c_m_a_p, _g_l_y_f, otTables


version = "2.1"

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


hexEntityRe = re.compile(r"&#x([\da-fA-F]+);")
decEntityRe = re.compile(r"&#(\d+);")


def decodeEntity(s: str) -> str:
    return hexEntityRe.sub(
        lambda m: chr(int(m.group(1), 16)),
        decEntityRe.sub(
            lambda m: chr(int(m.group(1), 10)),
            s
        )
    )


def get_chars_set(textfiles: Sequence[str]) -> Set[str]:
    chars: Set[str] = set()

    for f in textfiles:
        try:
            with open(f, encoding="utf-8-sig") as infile:
                dat = decodeEntity(infile.read())
        except Exception:
            logger.error("Error while loading text file '{}'".format(f))
            raise
        chars.update(dat)

    chars -= {"\t", "\r", "\n"}
    return chars


def parse_vs_line(line: str) -> Optional[Tuple[Tuple[int, int], bool]]:
    row = [decodeEntity(col) for col in line.split()]
    if not row:
        # empty line
        return None

    if len(row) > 2:
        raise SyntaxError("invalid number of columns: {}".format(len(row)))
    elif len(row) == 2:
        seq_str, is_default_str = row
    else:
        seq_str = row[0]
        is_default_str = ""

    seq = tuple([ord(c) for c in seq_str])
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


def get_vs_dict(vsfiles: Sequence[str]) -> Dict[Tuple[int, int], bool]:
    vs: Dict[Tuple[int, int], bool] = {}

    for f in vsfiles:
        try:
            with open(f, encoding="utf-8-sig") as infile:
                for lineno, line in enumerate(infile):
                    try:
                        dat = parse_vs_line(line)
                        if dat is None:
                            # empty line
                            continue
                        seq, is_default = dat
                    except SyntaxError:
                        logger.error(
                            "Error while parsing VS text file line {}".format(lineno + 1))
                        raise
                    vs[seq] = is_default
        except Exception:
            logger.error("Error while loading VS text file '{}'".format(f))
            raise

    return vs


def add_blank_glyph(glyphname: str, hmtx, vmtx, glyf) -> None:
    hmtx[glyphname] = vmtx[glyphname] = (1024, 0)

    glyph = _g_l_y_f.Glyph()
    glyph.xMin = glyph.yMin = glyph.xMax = glyph.yMax = 0
    glyf[glyphname] = glyph


def get_cmap(ttf: TTFont, vs: bool = False):
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
        logger.info("cmap subtable (format=12) created")

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
        cmap.tables.append(sub14)
        logger.info("cmap subtable (format=14) created")

    return sub4, subt, sub14


def get_glyphname(codepoint: int) -> str:
    if codepoint < 0x10000:
        glyphname = "uni{:04X}".format(codepoint)
    else:
        glyphname = "u{:04X}".format(codepoint)
    return glyphname


def add_to_cmap(codepoint: int, glyphname: str, sub4, subt) -> None:
    if codepoint < 0x10000 and sub4 is not None:
        sub4.cmap.setdefault(codepoint, glyphname)
    subt.cmap[codepoint] = glyphname


def add_to_cmap_vs(base: int, selector: int, glyphname: str, sub14) -> None:
    sub14.uvsDict.setdefault(selector, []).append([base, glyphname])


def check_vs(ttf: TTFont):
    # Check for VS font requirements on Windows 7
    # Reference: http://glyphwiki.org/wiki/User:emk

    _sub4, subt, sub14 = get_cmap(ttf, vs=True)

    if 0x20 not in subt.cmap:
        logger.info(
            "U+0020 should be added for VS to work on Windows 7")

    if all(codepoint < 0x10000 for codepoint in subt.cmap.keys()):
        logger.info(
            "at least one non-BMP character should be added for VS to work on Windows 7")

    # Don't use Default UVS Table
    for selector, uvList in sub14.uvsDict.items():
        if any(glyphname is None for base, glyphname in uvList):
            newUvList = []
            for base, glyphname in uvList:
                if glyphname is None:
                    assert base in subt.cmap, \
                        "base character (U+{:04X}) not in font".format(base)
                    newUvList.append([base, subt.cmap[base]])
                else:
                    newUvList.append([base, glyphname])
            sub14.uvsDict[selector] = newUvList

    # set 57th bit of ulUnicodeRange in OS/2 table
    os2 = ttf["OS/2"]
    os2.ulUnicodeRange2 |= 1 << (57 - 32)

    gsub = ttf["GSUB"]
    records = gsub.table.ScriptList.ScriptRecord
    if not any(record.ScriptTag == "hani" for record in records):
        # pylint: disable=E1101
        scriptrecord = otTables.ScriptRecord()
        scriptrecord.ScriptTag = "hani"
        scriptrecord.Script = otTables.Script()
        scriptrecord.Script.DefaultLangSys = otTables.DefaultLangSys()
        scriptrecord.Script.DefaultLangSys.ReqFeatureIndex = 65535
        scriptrecord.Script.DefaultLangSys.FeatureCount = 1
        feature_index = gsub.table.FeatureList.FeatureCount
        scriptrecord.Script.DefaultLangSys.FeatureIndex = [feature_index]
        records.append(scriptrecord)
        gsub.table.ScriptList.ScriptCount += 1

        featurerecord = otTables.FeatureRecord()
        featurerecord.FeatureTag = "aalt"
        featurerecord.Feature = otTables.Feature()
        featurerecord.Feature.FeatureParams = None
        featurerecord.Feature.LookupCount = 0
        featurerecord.Feature.LookupListIndex = []
        gsub.table.FeatureList.FeatureRecord.append(featurerecord)
        gsub.table.FeatureList.FeatureCount += 1
        # pylint: enable=E1101


def addglyph(
        fontfile: str, chars: Iterable[str],
        vs: Dict[Tuple[int, int], bool] = {},
        outfont: Optional[str] = None) -> None:
    try:
        ttf = TTFont(
            fontfile,
            recalcBBoxes=False  # Adding blank glyphs will not change bboxes
        )
    except Exception:
        logger.error("Error while loading font file")
        raise

    sub4, subt, sub14 = get_cmap(ttf, vs=bool(vs))

    hmtx = ttf["hmtx"]
    vmtx = ttf["vmtx"]
    glyf = ttf["glyf"]
    glyf.padding = 4

    added_count = 0

    for char in chars:
        codepoint = ord(char)
        if codepoint in subt.cmap:
            logger.info("already in font: U+{:04X}".format(codepoint))
            continue

        glyphname = get_glyphname(codepoint)

        add_to_cmap(codepoint, glyphname, sub4, subt)
        add_blank_glyph(glyphname, hmtx, vmtx, glyf)

        logger.info("added: U+{:04X}".format(codepoint))
        added_count += 1

    for seq, is_default in vs.items():
        base, selector = seq
        if any(uv == base for uv, gname in sub14.uvsDict.get(selector, [])):
            logger.info(
                "already in font: U+{:04X} U+{:04X}".format(base, selector))
            continue

        if is_default:
            # Windows 7 seems not to support default UVS table
            if base in subt.cmap:
                glyphname = subt.cmap[base]
            else:
                glyphname = get_glyphname(base)

                add_to_cmap(base, glyphname, sub4, subt)
                add_blank_glyph(glyphname, hmtx, vmtx, glyf)

                logger.info("added base character: U+{:04X}".format(base))
                added_count += 1

            add_to_cmap_vs(base, selector, glyphname, sub14)
            logger.info(
                "added: U+{:04X} U+{:04X} as default".format(base, selector))
        else:
            glyphname = "u{:04X}u{:04X}".format(base, selector)

            add_to_cmap_vs(base, selector, glyphname, sub14)
            add_blank_glyph(glyphname, hmtx, vmtx, glyf)

            logger.info(
                "added: U+{:04X} U+{:04X} as non-default".format(base, selector))
            added_count += 1

    if vs:
        check_vs(ttf)

    logger.info("{} glyphs added!".format(added_count))
    logger.info("saving...")

    if outfont is None:
        outfont = fontfile[:-4] + "_new" + fontfile[-4:]

    try:
        with TemporaryFile(prefix="add-glyphs") as tmp:
            ttf.save(tmp, reorderTables=False)

            # Bring `glyf` table to the last so that the font can be edited with TTEdit
            logger.info("reordering...")
            tmp.flush()
            tmp.seek(0)
            with open(outfont, "wb") as outfile:
                reorderFontTables(tmp, outfile, tableOrder=[
                    "head", "hhea", "maxp", "post", "OS/2", "name", "gasp", "cvt ", "fpgm",
                    "prep", "cmap", "loca", "hmtx", "mort", "GSUB", "vhea", "vmtx",
                    "glyf"
                ])
    except Exception:
        logger.error("Error while saving font file")
        raise

    logger.info("saved successfully: {}".format(outfont))


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

    fontfiles: List[str] = list(argset.fontfiles)
    textfiles: List[str] = list(argset.textfiles)
    vsfiles: List[str] = list(argset.vsfiles)
    outfont: Optional[str] = argset.outfile

    for other_file in cast(List[str], argset.other_files):
        if other_file[-4:].lower() in (".ttf", ".otf"):
            fontfiles.append(other_file)
        elif os.path.basename(other_file)[:2].lower() == "vs":
            textfiles.append(other_file)
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


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("An error occurred")
        sys.exit(1)
    finally:
        pause()
