from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING, cast

from fontTools.misc.textTools import Tag
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables import _c_m_a_p, _g_l_y_f

from .error import AddGlyphUserError
from .gsub import GSUBRuleAdder
from .inputfile import GlyphSpec, GSUBSpec, stringify_glyphspec
from .monkeypatch import apply_monkey_patch

if TYPE_CHECKING:
    from fontTools.ttLib.tables import G_S_U_B_, O_S_2f_2, _h_m_t_x, _v_m_t_x

    CMap = dict[int, str]
    UVSMap = dict[int, list[tuple[int, str | None]]]


logger = logging.getLogger(__name__)

apply_monkey_patch()


class FontGlyphAdder:
    def __init__(self, ttf: TTFont) -> None:
        self._hmtx = cast("_h_m_t_x.table__h_m_t_x", ttf["hmtx"])
        self._vmtx = cast("_v_m_t_x.table__v_m_t_x", ttf["vmtx"])
        self._glyf = cast("_g_l_y_f.table__g_l_y_f", ttf["glyf"])
        self._glyf.padding = 4

        self.added_count = 0

    def add_blank_glyph(
        self, glyphname: str, description: str | None = None
    ) -> None:
        self._hmtx[glyphname] = self._vmtx[glyphname] = (1024, 0)

        glyph = _g_l_y_f.Glyph()
        glyph.xMin = glyph.yMin = glyph.xMax = glyph.yMax = 0
        self._glyf[glyphname] = glyph

        self.added_count += 1
        logger.info(f"added: {description or glyphname}")


class FontCMap:
    def __init__(self, ttf: TTFont) -> None:
        cmap = cast("_c_m_a_p.table__c_m_a_p", ttf["cmap"])
        self._sub4 = cast(
            "_c_m_a_p.cmap_format_4 | None",
            cmap.getcmap(platformID=3, platEncID=1),
        )
        subt = cast(
            "_c_m_a_p.cmap_format_12 | None",
            cmap.getcmap(platformID=3, platEncID=10),
        )
        if subt is None:
            assert self._sub4 is not None, "cmap subtable (format=4) not found"
            subt = self._create_subt_from_sub4(self._sub4)
            cmap.tables.append(subt)
            logger.info("cmap subtable (format=12) created")
        self._subt: _c_m_a_p.cmap_format_12 = subt

    def lookup_glyphname(self, codepoint: int) -> str | None:
        return cast("CMap", self._subt.cmap).get(codepoint)

    def add(self, codepoint: int, glyphname: str) -> None:
        if codepoint < 0x10000 and self._sub4 is not None:
            cast("CMap", self._sub4.cmap).setdefault(codepoint, glyphname)
        cast("CMap", self._subt.cmap)[codepoint] = glyphname

    @staticmethod
    def _create_subt_from_sub4(
        sub4: _c_m_a_p.cmap_format_4,
    ) -> _c_m_a_p.cmap_format_12:
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
        return subt


class FontVSCmap:
    def __init__(self, ttf: TTFont) -> None:
        self._cmap = cast("_c_m_a_p.table__c_m_a_p", ttf["cmap"])
        sub14 = cast(
            "_c_m_a_p.cmap_format_14 | None",
            self._cmap.getcmap(platformID=0, platEncID=5),
        )
        self._sub14 = sub14
        if sub14 is not None:
            self._vs_in_font: dict[tuple[int, int], str | None] = {
                (uv, selector): gname
                for selector, uvList in cast("UVSMap", sub14.uvsDict).items()
                for uv, gname in uvList
            }
        else:
            self._vs_in_font = {}

    def _ensure_sub14(self) -> _c_m_a_p.cmap_format_14:
        if self._sub14 is not None:
            return self._sub14

        sub14 = cast(
            "_c_m_a_p.cmap_format_14",
            _c_m_a_p.CmapSubtable.newSubtable(14),
        )
        sub14.platformID = 0  # type: ignore
        sub14.platEncID = 5  # type: ignore
        sub14.format = 14
        sub14.length = 0  # will be recalculated by compiler
        sub14.numVarSelectorRecords = 0  # will be recalculated by compiler
        sub14.language = 0xFF
        sub14.cmap = cast("CMap", {})
        sub14.uvsDict = cast("UVSMap", {})
        self._cmap.tables.append(sub14)
        logger.info("cmap subtable (format=14) created")
        self._sub14 = sub14
        return sub14

    def lookup_glyphname(self, base: int, selector: int) -> str | None:
        return self._vs_in_font.get((base, selector))

    def add(self, base: int, selector: int, glyphname: str) -> None:
        uvsDict = cast("UVSMap", self._ensure_sub14().uvsDict)
        uvsDict.setdefault(selector, []).append((base, glyphname))
        self._vs_in_font[(base, selector)] = glyphname


def generate_glyphname(codepoint: int, selector: int | None = None) -> str:
    if selector is not None:
        return f"u{codepoint:04X}u{selector:04X}"

    if codepoint < 0x10000:
        return f"uni{codepoint:04X}"
    else:
        return f"u{codepoint:04X}"


def undo_gsub_win7_fix(ttf: TTFont) -> None:
    """Remove the unnecessary Windows 7 fix in the GSUB table.

    In versions of `addglyph` before 3.0, a dummy feature was added to the GSUB
    table to support VSes on Windows 7. However, this dummy feature is not
    actually needed because the presence of the GSUB table itself is
    sufficient, and `addglyph` did not add a GSUB table on its own.
    Additionally, this dummy feature interferes with the new functionality for
    adding substitution rules.
    This function removes the dummy feature from the GSUB table, if it exists.
    """
    gsub = cast("G_S_U_B_.table_G_S_U_B_", ttf["GSUB"])
    for script_index, script_record in enumerate(
        gsub.table.ScriptList.ScriptRecord
    ):
        if script_record.ScriptTag != "hani":
            continue
        if script_record.Script.LangSysCount != 0:
            continue
        if script_record.Script.DefaultLangSys is None:
            continue
        if script_record.Script.DefaultLangSys.LookupOrder is not None:
            continue
        if script_record.Script.DefaultLangSys.ReqFeatureIndex != 0xFFFF:
            continue
        if script_record.Script.DefaultLangSys.FeatureCount != 1:
            continue
        feature_index: int = script_record.Script.DefaultLangSys.FeatureIndex[
            0
        ]
        feature_record = gsub.table.FeatureList.FeatureRecord[feature_index]
        if feature_record.FeatureTag != "aalt":
            continue
        if feature_record.Feature.FeatureParams is not None:
            continue
        if feature_record.Feature.LookupCount != 0:
            continue
        break
    else:
        return
    del gsub.table.ScriptList.ScriptRecord[script_index]
    gsub.table.ScriptList.ScriptCount -= 1

    # Confirm that the feature is not used in other langsys before deleting it
    if not any(
        feature_index in langsys.FeatureIndex
        for script_record in gsub.table.ScriptList.ScriptRecord
        for langsys in [
            script_record.Script.DefaultLangSys,
            *(
                langsys_record.LangSys
                for langsys_record in script_record.Script.LangSysRecord
            ),
        ]
        if langsys is not None
    ):
        del gsub.table.FeatureList.FeatureRecord[feature_index]
        gsub.table.FeatureList.FeatureCount -= 1
        logger.debug(
            "Removed the dummy feature and script from the GSUB table"
        )
    else:
        logger.debug("Removed the dummy feature from the GSUB table")


class AddGlyphHandler:
    def __init__(self, fontfile: str, gsub_spec: GSUBSpec) -> None:
        try:
            self.ttf = TTFont(
                fontfile,
                # Adding blank glyphs will not change bboxes
                recalcBBoxes=False,
            )
        except Exception as exc:
            logger.error("Error while loading font file")
            raise AddGlyphUserError() from exc

        self._font_cmap = FontCMap(self.ttf)
        self._adder = FontGlyphAdder(self.ttf)
        self._font_vs_cmap: FontVSCmap | None = None
        self._gsub_adder: GSUBRuleAdder | None = None
        self._gsub_spec = gsub_spec

    def _get_font_vs_cmap(self) -> FontVSCmap:
        if self._font_vs_cmap is None:
            self._font_vs_cmap = FontVSCmap(self.ttf)
        return self._font_vs_cmap

    def _ensure_glyph(
        self, codepoint: int, description: str | None = None
    ) -> tuple[str, bool]:
        """Ensure that the glyph for the given codepoint exists in the font.

        Returns a tuple of the glyph name and a boolean indicating whether the
        glyph was newly added.
        """
        glyphname = self._font_cmap.lookup_glyphname(codepoint)
        if glyphname is not None:
            return glyphname, False

        glyphname = generate_glyphname(codepoint)

        self._font_cmap.add(codepoint, glyphname)
        self._adder.add_blank_glyph(glyphname, description)
        return glyphname, True

    def add_glyph(self, codepoint: int) -> None:
        _glyphname, added = self._ensure_glyph(codepoint, f"U+{codepoint:04X}")
        if not added:
            logger.info(f"already in font: U+{codepoint:04X}")

    def add_vs_glyph(self, base: int, selector: int, is_default: bool) -> None:
        font_vs_cmap = self._get_font_vs_cmap()
        if font_vs_cmap.lookup_glyphname(base, selector) is not None:
            logger.info(f"already in font: U+{base:04X} U+{selector:04X}")
            return

        if is_default:
            # Windows 7 seems not to support default UVS table
            # Reference: http://glyphwiki.org/wiki/User:emk
            glyphname, _added = self._ensure_glyph(
                base, f"U+{base:04X} (base of U+{base:04X} U+{selector:04X})"
            )

            font_vs_cmap.add(base, selector, glyphname)
            logger.info(f"added: U+{base:04X} U+{selector:04X} as default")
        else:
            glyphname = generate_glyphname(base, selector)

            font_vs_cmap.add(base, selector, glyphname)
            self._adder.add_blank_glyph(
                glyphname,
                f"U+{base:04X} U+{selector:04X} as non-default",
            )

    def get_glyphname_from_gspec(self, gspec: GlyphSpec) -> str | None:
        if isinstance(gspec, int):
            glyph_order = cast("list[str]", self.ttf.getGlyphOrder())
            if gspec >= len(glyph_order):
                return None
            return glyph_order[gspec]

        base, selector = gspec
        if selector is None:
            return self._font_cmap.lookup_glyphname(base)

        font_vs_cmap = self._get_font_vs_cmap()
        return font_vs_cmap.lookup_glyphname(base, selector)

    def _get_gsub_adder(self) -> GSUBRuleAdder:
        if self._gsub_adder is None:
            self._gsub_adder = GSUBRuleAdder(
                self.ttf, self._gsub_spec.language_systems
            )
        return self._gsub_adder

    def add_gsub_rules(
        self, feature_tag: Tag, target: str, replacements: list[str]
    ) -> None:
        gsub_adder = self._get_gsub_adder()
        gsub_adder.add_rule(feature_tag, target, replacements)

    def save(self, path: str) -> None:
        os2 = cast("O_S_2f_2.table_O_S_2f_2", self.ttf["OS/2"])

        old_uniranges: set[int] = os2.getUnicodeRanges()
        new_uniranges: set[int] = os2.recalcUnicodeRanges(self.ttf)
        # Retain old uniranges
        os2.setUnicodeRanges(old_uniranges | new_uniranges)

        old_codepages: set[int] = os2.getCodePageRanges()
        new_codepages: set[int] = os2.recalcCodePageRanges(self.ttf)
        # Retain old codepages
        os2.setCodePageRanges(old_codepages | new_codepages)

        if self._gsub_adder is not None:
            self._gsub_adder.reorder_lookups()

        logger.info(f"{self._adder.added_count} glyphs added!")
        logger.info("saving...")

        try:
            self.ttf.save(path, reorderTables=False)
        except Exception as exc:
            logger.error("Error while saving font file")
            raise AddGlyphUserError() from exc

        logger.info(f"saved successfully: {path}")


def addglyph(
    fontfile: str,
    chars: Iterable[str],
    vs: dict[tuple[int, int], bool],
    gsub_spec: GSUBSpec,
    outfont: str | None = None,
) -> None:
    handler = AddGlyphHandler(fontfile, gsub_spec)
    for char in chars:
        codepoint = ord(char)
        handler.add_glyph(codepoint)
    for (base, selector), is_default in vs.items():
        handler.add_vs_glyph(base, selector, is_default)

    if gsub_spec:
        undo_gsub_win7_fix(handler.ttf)

    for feature_tag, gspec_list in gsub_spec.entries_by_tag.items():
        alternate_by_input: dict[str, list[str]] = {}
        for input_glyph, alternate_glyph in gspec_list:
            input_name = handler.get_glyphname_from_gspec(input_glyph)
            if input_name is None:
                str_input_glyph = stringify_glyphspec(input_glyph)
                logger.info(f"input glyph not found: {str_input_glyph}")
                continue
            alternate_name = handler.get_glyphname_from_gspec(alternate_glyph)
            if alternate_name is None:
                str_alternate_glyph = stringify_glyphspec(alternate_glyph)
                logger.info(
                    f"alternate glyph not found: {str_alternate_glyph}"
                )
                continue
            if input_name == alternate_name:
                logger.info(f"input and alternate are the same: {input_name}")
                continue
            alternate_by_input.setdefault(input_name, []).append(
                alternate_name
            )
        for input_name, alternate_list in alternate_by_input.items():
            handler.add_gsub_rules(feature_tag, input_name, alternate_list)

    if outfont is None:
        outfont = fontfile[:-4] + "_new" + fontfile[-4:]

    handler.save(outfont)
