# monkey patch based on fontTools version 4.55.8

# ruff: noqa: UP031

from __future__ import annotations

import array
import struct
import sys
from typing import TYPE_CHECKING, Any, cast

from fontTools.misc.roundTools import otRound
from fontTools.ttLib import TTLibError
from fontTools.ttLib.tables import _h_m_t_x, _l_o_c_a

if TYPE_CHECKING:
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.tables import _m_a_x_p


def apply_monkey_patch():
    # Make sure head.indexToLocFormat = 1
    def loca_compile(self: _l_o_c_a.table__l_o_c_a, ttFont: TTFont) -> bytes:
        try:
            self.locations
        except AttributeError:
            self.set([])
        locations = array.array("I", self.locations)
        cast("Any", ttFont["head"]).indexToLocFormat = 1
        if sys.byteorder != "big":
            locations.byteswap()
        return locations.tobytes()

    _l_o_c_a.table__l_o_c_a.compile = loca_compile

    # Make hhea.numberOfHMetrics = vhea.numOfLongVerMetrics = numGlyphs
    def hmtx_compile(self: _h_m_t_x.table__h_m_t_x, ttFont: TTFont) -> bytes:
        metrics = []
        hasNegativeAdvances = False
        for glyphName in ttFont.getGlyphOrder():
            advanceWidth, sideBearing = self.metrics[glyphName]
            if advanceWidth < 0:
                _h_m_t_x.log.error(
                    "Glyph %r has negative advance %s"
                    % (glyphName, self.advanceName)
                )
                hasNegativeAdvances = True
            metrics.append([advanceWidth, sideBearing])

        numberOfMetrics = (
            cast("_m_a_x_p.table__m_a_x_p", ttFont["maxp"])
        ).numGlyphs

        headerTable = ttFont.get(self.headerTag)
        if headerTable is not None:
            setattr(headerTable, self.numberOfMetricsName, numberOfMetrics)

        allMetrics = []
        for advance, sb in metrics:
            allMetrics.extend([otRound(advance), otRound(sb)])
        metricsFmt = ">" + self.longMetricFormat * numberOfMetrics
        try:
            data = struct.pack(metricsFmt, *allMetrics)
        except struct.error as e:
            if "out of range" in str(e) and hasNegativeAdvances:
                raise TTLibError(
                    "'%s' table can't contain negative advance %ss"
                    % (self.tableTag, self.advanceName)
                )
            else:
                raise
        return data

    _h_m_t_x.table__h_m_t_x.compile = hmtx_compile
