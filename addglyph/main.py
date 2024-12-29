from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, cast

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables import _c_m_a_p, _g_l_y_f
from fontTools.ttLib.tables import otTables as otTables_

from .error import AddGlyphUserError
from .monkeypatch import apply_monkey_patch

otTables = cast("Any", otTables_)


if TYPE_CHECKING:
    from fontTools.ttLib.tables import G_S_U_B_, O_S_2f_2, _h_m_t_x, _v_m_t_x

    CMap = dict[int, str]
    UVSMap = dict[int, list[tuple[int, str | None]]]


logger = logging.getLogger(__name__)

apply_monkey_patch()


def add_blank_glyph(
    glyphname: str,
    hmtx: _h_m_t_x.table__h_m_t_x,
    vmtx: _v_m_t_x.table__v_m_t_x,
    glyf: _g_l_y_f.table__g_l_y_f,
) -> None:
    hmtx[glyphname] = vmtx[glyphname] = (1024, 0)

    glyph = _g_l_y_f.Glyph()
    glyph.xMin = glyph.yMin = glyph.xMax = glyph.yMax = 0
    glyf[glyphname] = glyph


def get_cmap(ttf: TTFont, vs: bool = False):
    cmap = cast("_c_m_a_p.table__c_m_a_p", ttf["cmap"])
    sub4: _c_m_a_p.cmap_format_4 | None = cmap.getcmap(
        platformID=3, platEncID=1
    )
    subt: _c_m_a_p.cmap_format_12 | None = cmap.getcmap(
        platformID=3, platEncID=10
    )
    if subt is None:
        assert sub4 is not None, "cmap subtable (format=4) not found"
        subt = cast(
            "_c_m_a_p.cmap_format_12", _c_m_a_p.CmapSubtable.newSubtable(12)
        )
        subt.platformID = 3  # type: ignore
        subt.platEncID = 10  # type: ignore
        subt.format = 12
        subt.reserved = 0
        subt.length = 0  # will be recalculated by compiler
        subt.language = 0
        subt.nGroups = 0  # will be recalculated by compiler
        if not hasattr(subt, "cmap"):
            subt.cmap = cast("CMap", {})
        subt.cmap.update(cast("CMap", sub4.cmap))
        cmap.tables.append(subt)
        logger.info("cmap subtable (format=12) created")

    sub14: _c_m_a_p.cmap_format_14 | None = cmap.getcmap(
        platformID=0, platEncID=5
    )
    if vs and sub14 is None:
        sub14 = cast(
            "_c_m_a_p.cmap_format_14", _c_m_a_p.CmapSubtable.newSubtable(14)
        )
        sub14.platformID = 0  # type: ignore
        sub14.platEncID = 5  # type: ignore
        sub14.format = 14
        sub14.length = 0  # will be recalculated by compiler
        sub14.numVarSelectorRecords = 0  # will be recalculated by compiler
        sub14.language = 0xFF
        sub14.cmap = cast("CMap", {})
        sub14.uvsDict = cast("UVSMap", {})
        cmap.tables.append(sub14)
        logger.info("cmap subtable (format=14) created")

    return sub4, subt, sub14


def get_glyphname(codepoint: int) -> str:
    if codepoint < 0x10000:
        glyphname = f"uni{codepoint:04X}"
    else:
        glyphname = f"u{codepoint:04X}"
    return glyphname


def add_to_cmap(
    codepoint: int,
    glyphname: str,
    sub4: _c_m_a_p.cmap_format_4 | None,
    subt: _c_m_a_p.cmap_format_12,
) -> None:
    if codepoint < 0x10000 and sub4 is not None:
        cast("CMap", sub4.cmap).setdefault(codepoint, glyphname)
    cast("CMap", subt.cmap)[codepoint] = glyphname


def add_to_cmap_vs(
    base: int, selector: int, glyphname: str, sub14: _c_m_a_p.cmap_format_14
) -> None:
    cast("UVSMap", sub14.uvsDict).setdefault(selector, []).append(
        (base, glyphname)
    )


def check_vs(ttf: TTFont) -> None:
    # Check for VS font requirements on Windows 7
    # Reference: http://glyphwiki.org/wiki/User:emk

    _sub4, subt, sub14 = get_cmap(ttf, vs=True)
    assert sub14 is not None  # vs=True

    subt.cmap = cast("CMap", subt.cmap)
    sub14.uvsDict = cast("UVSMap", sub14.uvsDict)

    if 0x20 not in subt.cmap:
        logger.info("U+0020 should be added for VS to work on Windows 7")

    if all(codepoint < 0x10000 for codepoint in subt.cmap.keys()):
        logger.info(
            "at least one non-BMP character should be added for VS to work "
            "on Windows 7"
        )

    # Don't use Default UVS Table
    for selector, uvList in sub14.uvsDict.items():
        if any(glyphname is None for base, glyphname in uvList):
            newUvList = []
            for base, glyphname in uvList:
                if glyphname is None:
                    assert (
                        base in subt.cmap
                    ), f"base character (U+{base:04X}) not in font"
                    newUvList.append([base, subt.cmap[base]])
                else:
                    newUvList.append([base, glyphname])
            sub14.uvsDict[selector] = newUvList

    # set 57th bit of ulUnicodeRange in OS/2 table
    os2 = cast("O_S_2f_2.table_O_S_2f_2", ttf["OS/2"])
    os2.ulUnicodeRange2 |= 1 << (57 - 32)

    gsub = cast("G_S_U_B_.table_G_S_U_B_", ttf["GSUB"])
    records = gsub.table.ScriptList.ScriptRecord
    if not any(record.ScriptTag == "hani" for record in records):
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


def addglyph(
    fontfile: str,
    chars: Iterable[str],
    vs: dict[tuple[int, int], bool] = {},
    outfont: str | None = None,
) -> None:
    try:
        ttf = TTFont(
            fontfile,
            recalcBBoxes=False,  # Adding blank glyphs will not change bboxes
        )
    except Exception as exc:
        logger.error("Error while loading font file")
        raise AddGlyphUserError() from exc

    sub4, subt, sub14 = get_cmap(ttf, vs=bool(vs))

    subt.cmap = cast("CMap", subt.cmap)

    hmtx = cast("_h_m_t_x.table__h_m_t_x", ttf["hmtx"])
    vmtx = cast("_v_m_t_x.table__v_m_t_x", ttf["vmtx"])
    glyf = cast("_g_l_y_f.table__g_l_y_f", ttf["glyf"])
    glyf.padding = 4

    added_count = 0

    for char in chars:
        codepoint = ord(char)
        if codepoint in subt.cmap:
            logger.info(f"already in font: U+{codepoint:04X}")
            continue

        glyphname = get_glyphname(codepoint)

        add_to_cmap(codepoint, glyphname, sub4, subt)
        add_blank_glyph(glyphname, hmtx, vmtx, glyf)

        logger.info(f"added: U+{codepoint:04X}")
        added_count += 1

    vs_in_font: set[tuple[int, int]] = set()
    if sub14 is not None and vs:
        for selector, uvList in cast("UVSMap", sub14.uvsDict).items():
            vs_in_font.update((uv, selector) for uv, gname in uvList)

    for seq, is_default in vs.items():
        assert sub14 is not None  # sub14 is None => vs == {}
        base, selector = seq

        if seq in vs_in_font:
            logger.info(f"already in font: U+{base:04X} U+{selector:04X}")
            continue

        if is_default:
            # Windows 7 seems not to support default UVS table
            if base in subt.cmap:
                glyphname = subt.cmap[base]
            else:
                glyphname = get_glyphname(base)

                add_to_cmap(base, glyphname, sub4, subt)
                add_blank_glyph(glyphname, hmtx, vmtx, glyf)

                logger.info(f"added base character: U+{base:04X}")
                added_count += 1

            add_to_cmap_vs(base, selector, glyphname, sub14)
            logger.info(f"added: U+{base:04X} U+{selector:04X} as default")
        else:
            glyphname = f"u{base:04X}u{selector:04X}"

            add_to_cmap_vs(base, selector, glyphname, sub14)
            add_blank_glyph(glyphname, hmtx, vmtx, glyf)

            logger.info(f"added: U+{base:04X} U+{selector:04X} as non-default")
            added_count += 1

        vs_in_font.add(seq)

    os2 = cast("O_S_2f_2.table_O_S_2f_2", ttf["OS/2"])

    old_uniranges: set[int] = os2.getUnicodeRanges()
    new_uniranges: set[int] = os2.recalcUnicodeRanges(ttf)
    # Retain old uniranges
    os2.setUnicodeRanges(old_uniranges | new_uniranges)

    old_codepages: set[int] = os2.getCodePageRanges()
    new_codepages: set[int] = os2.recalcCodePageRanges(ttf)
    # Retain old codepages
    os2.setCodePageRanges(old_codepages | new_codepages)

    if vs:
        check_vs(ttf)

    logger.info(f"{added_count} glyphs added!")
    logger.info("saving...")

    if outfont is None:
        outfont = fontfile[:-4] + "_new" + fontfile[-4:]

    try:
        ttf.save(outfont, reorderTables=False)
    except Exception as exc:
        logger.error("Error while saving font file")
        raise AddGlyphUserError() from exc

    logger.info(f"saved successfully: {outfont}")
