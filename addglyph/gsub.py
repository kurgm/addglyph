from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any, cast

from fontTools.misc.textTools import Tag
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables import otTables as otTables_

if TYPE_CHECKING:
    from fontTools.ttLib.tables import G_S_U_B_


logger = logging.getLogger(__name__)

otTables = cast("Any", otTables_)


class GSUBFeatureRuleAdder:
    def __init__(
        self, gsub: G_S_U_B_.table_G_S_U_B_, feature_index: int
    ) -> None:
        self._gsub = gsub
        feature_record = gsub.table.FeatureList.FeatureRecord[feature_index]
        self._feature_tag = feature_record.FeatureTag
        self._feature = feature_record.Feature
        self._lookup_indices = cast("list[int]", self._feature.LookupListIndex)
        self._default_lookup_single_subtable: otTables_.SingleSubst | None = (
            None
        )
        self._default_lookup_alternate_subtable: (
            otTables_.AlternateSubst | None
        ) = None

    def _add_lookup(self, lookup) -> int:
        lookup_index = len(self._gsub.table.LookupList.Lookup)
        self._gsub.table.LookupList.Lookup.append(lookup)
        self._gsub.table.LookupList.LookupCount += 1
        self._lookup_indices.append(lookup_index)
        self._feature.LookupCount += 1
        return lookup_index

    def _get_default_lookup_single(self):
        for lookup_index in self._lookup_indices:
            lookup = self._gsub.table.LookupList.Lookup[lookup_index]
            if lookup.LookupType == 1:
                return lookup

        lookup = otTables.Lookup()
        lookup.LookupType = 1
        lookup.LookupFlag = 0
        lookup.SubTableCount = 0
        lookup.SubTable = []
        self._add_lookup(lookup)
        return lookup

    def _get_default_lookup_single_subtable(self) -> otTables_.SingleSubst:
        if self._default_lookup_single_subtable is not None:
            return self._default_lookup_single_subtable

        lookup = self._get_default_lookup_single()
        if lookup.SubTable:
            subtable = lookup.SubTable[0]
            assert isinstance(subtable, otTables_.SingleSubst)
        else:
            subtable = otTables.SingleSubst()
            subtable.mapping = {}
            lookup.SubTable.append(subtable)
            lookup.SubTableCount += 1
        self._default_lookup_single_subtable = subtable
        return subtable

    def _get_default_lookup_alternate(self):
        for lookup_index in self._lookup_indices:
            lookup = self._gsub.table.LookupList.Lookup[lookup_index]
            if lookup.LookupType == 3:
                return lookup

        lookup = otTables.Lookup()
        lookup.LookupType = 3
        lookup.LookupFlag = 0
        lookup.SubTableCount = 0
        lookup.SubTable = []
        self._add_lookup(lookup)
        return lookup

    def _get_default_lookup_alternate_subtable(
        self,
    ) -> otTables_.AlternateSubst:
        if self._default_lookup_alternate_subtable is not None:
            return self._default_lookup_alternate_subtable

        lookup = self._get_default_lookup_alternate()
        if lookup.SubTable:
            subtable = lookup.SubTable[0]
            assert isinstance(subtable, otTables_.AlternateSubst)
        else:
            subtable = otTables.AlternateSubst()
            subtable.alternates = {}
            lookup.SubTable.append(subtable)
            lookup.SubTableCount += 1
        self._default_lookup_alternate_subtable = subtable
        return subtable

    @staticmethod
    def _merge_alternates(left: list[str], right: Iterable[str]) -> list[str]:
        return left + [e for e in dict.fromkeys(right) if e not in left]

    def _try_add_rule_existing_single(
        self, target: str, replacements: list[str]
    ) -> list[str]:
        for lookup_index in self._lookup_indices:
            lookup = self._gsub.table.LookupList.Lookup[lookup_index]
            if lookup.LookupType != 1:
                continue
            for subtable in lookup.SubTable:
                assert isinstance(subtable, otTables_.SingleSubst)
                mapping = cast("dict[str, str]", subtable.mapping)
                if target in mapping:
                    replacements = self._merge_alternates(
                        [mapping[target]], replacements
                    )
                    if replacements == [mapping[target]]:
                        # All new alternates are already in the mapping,
                        # so we are done
                        logger.info(
                            f"already in font: {self._feature_tag}: "
                            f"{target} -> {', '.join(replacements)}"
                        )
                        return []
                    del mapping[target]
                    return replacements

        return replacements

    def _try_add_rule_existing_alternate(
        self, target: str, replacements: list[str]
    ) -> list[str]:
        for lookup_index in self._lookup_indices:
            lookup = self._gsub.table.LookupList.Lookup[lookup_index]
            if lookup.LookupType != 3:
                continue
            for subtable in lookup.SubTable:
                assert isinstance(subtable, otTables_.AlternateSubst)
                alternates = cast("dict[str, list[str]]", subtable.alternates)
                if target in alternates:
                    existing = alternates[target]
                    new_alternates = self._merge_alternates(
                        existing, replacements
                    )
                    alternates[target] = new_alternates
                    if existing != new_alternates:
                        logger.info(
                            f"added: {self._feature_tag}: "
                            f"{target} -> {', '.join(new_alternates)}"
                        )
                    else:
                        logger.info(
                            f"already in font: {self._feature_tag}: "
                            f"{target} -> {', '.join(new_alternates)}"
                        )
                    return []

        return replacements

    def add_rule(self, target: str, replacements_: Iterable[str]) -> None:
        replacements = list(replacements_)
        replacements = self._try_add_rule_existing_single(target, replacements)
        if not replacements:
            return
        replacements = self._try_add_rule_existing_alternate(
            target, replacements
        )
        if not replacements:
            return
        if len(replacements) == 1:
            subtable = self._get_default_lookup_single_subtable()
            mapping = cast("dict[str, str]", subtable.mapping)
            mapping[target] = replacements[0]
        else:
            subtable = self._get_default_lookup_alternate_subtable()
            alternates = cast("dict[str, list[str]]", subtable.alternates)
            alternates[target] = replacements

        logger.info(
            f"added: {self._feature_tag}: "
            f"{target} -> {', '.join(replacements)}"
        )


class GSUBRuleAdder:
    def __init__(
        self, ttf: TTFont, language_systems: list[tuple[Tag, Tag]]
    ) -> None:
        self._gsub = cast("G_S_U_B_.table_G_S_U_B_", ttf["GSUB"])
        self._feature_indices_by_tag: dict[Tag, set[int]] = {}
        self._feature_adders: dict[int, GSUBFeatureRuleAdder] = {}

        self._dflt_langsys = self._get_dflt_langsys(
            self._gsub, language_systems
        )

    @staticmethod
    def _get_dflt_langsys(
        gsub: G_S_U_B_.table_G_S_U_B_, langsys_tags: Sequence[tuple[Tag, Tag]]
    ):
        def create_langsys():
            langsys = otTables.LangSys()
            langsys.LookupOrder = None
            langsys.ReqFeatureIndex = 0xFFFF
            langsys.FeatureCount = 0
            langsys.FeatureIndex = []
            return langsys

        def ensure_langsys(script_tag: Tag, langsys_tag: Tag):
            for script_record in gsub.table.ScriptList.ScriptRecord:
                if script_record.ScriptTag == script_tag:
                    break
            else:
                script_record = otTables.ScriptRecord()
                script_record.ScriptTag = script_tag
                script_record.Script = otTables.Script()
                script_record.Script.DefaultLangSys = None
                script_record.Script.LangSysCount = 0
                script_record.Script.LangSysRecord = []
                gsub.table.ScriptList.ScriptRecord.append(script_record)
                gsub.table.ScriptList.ScriptRecord.sort(
                    key=lambda sr: sr.ScriptTag
                )
                gsub.table.ScriptList.ScriptCount += 1
                logger.info(f"script {script_tag!r} created")

            if langsys_tag == "dflt":
                if script_record.Script.DefaultLangSys is not None:
                    return
                script_record.Script.DefaultLangSys = create_langsys()
                logger.info(
                    f"default langsys for script {script_tag!r} created"
                )
                return

            for langsys_record in script_record.Script.LangSysRecord:
                if langsys_record.LangSysTag == langsys_tag:
                    return

            langsys_record = otTables.LangSysRecord()
            langsys_record.LangSysTag = langsys_tag
            langsys_record.LangSys = create_langsys()
            script_record.Script.LangSysRecord.append(langsys_record)
            script_record.Script.LangSysRecord.sort(
                key=lambda lsr: lsr.LangSysTag
            )
            script_record.Script.LangSysCount += 1
            logger.info(
                f"langsys {langsys_tag!r} for script {script_tag!r} created"
            )

        for script_tag, langsys_tag in langsys_tags:
            ensure_langsys(script_tag, langsys_tag)

        # Prefer the DFLT script's default langsys
        for script_record in gsub.table.ScriptList.ScriptRecord:
            if script_record.ScriptTag == "DFLT":
                dflt_langsys = script_record.Script.DefaultLangSys
                assert dflt_langsys is not None
                return dflt_langsys

        script_tag, langsys_tag = langsys_tags[0]
        for script_record in gsub.table.ScriptList.ScriptRecord:
            if script_record.ScriptTag == script_tag:
                break
        else:
            raise KeyError(script_tag)

        if langsys_tag == "dflt":
            return script_record.Script.DefaultLangSys

        for langsys_record in script_record.Script.LangSysRecord:
            if langsys_record.LangSysTag == langsys_tag:
                return langsys_record.LangSys

        raise KeyError(langsys_tag)

    def _ensure_langsys_has_feature(self, feature_tag: Tag) -> None:
        # Ensure that the DFLT script's default langsys has the feature
        for feature_index in self._dflt_langsys.FeatureIndex:
            feature_record = self._gsub.table.FeatureList.FeatureRecord[
                feature_index
            ]
            if feature_record.FeatureTag == feature_tag:
                break
        else:
            feature_record = otTables.FeatureRecord()
            feature_record.FeatureTag = feature_tag
            feature_record.Feature = otTables.Feature()
            feature_record.Feature.FeatureParams = None
            feature_record.Feature.LookupCount = 0
            feature_record.Feature.LookupListIndex = []
            feature_index = len(self._gsub.table.FeatureList.FeatureRecord)
            self._gsub.table.FeatureList.FeatureRecord.append(feature_record)
            self._gsub.table.FeatureList.FeatureCount += 1
            logger.info(f"feature {feature_tag!r} created")
            self._dflt_langsys.FeatureIndex.append(feature_index)
            self._dflt_langsys.FeatureCount += 1

        # Ensure that all langsys have the feature
        for langsys in [
            langsys
            for script_record in self._gsub.table.ScriptList.ScriptRecord
            for langsys in [
                script_record.Script.DefaultLangSys,
                *(
                    langsys_record.LangSys
                    for langsys_record in script_record.Script.LangSysRecord
                ),
            ]
            if langsys is not None
        ]:
            if any(
                self._gsub.table.FeatureList.FeatureRecord[
                    feature_index
                ].FeatureTag
                == feature_tag
                for feature_index in langsys.FeatureIndex
            ):
                continue
            langsys.FeatureIndex.append(feature_index)
            langsys.FeatureCount += 1

    def _get_feature_indices(self, feature_tag: Tag) -> set[int]:
        if feature_tag in self._feature_indices_by_tag:
            return self._feature_indices_by_tag[feature_tag]

        self._ensure_langsys_has_feature(feature_tag)
        feature_indices = {
            feature_index
            for script_record in self._gsub.table.ScriptList.ScriptRecord
            for langsys in [
                script_record.Script.DefaultLangSys,
                *(
                    langsys_record.LangSys
                    for langsys_record in script_record.Script.LangSysRecord
                ),
            ]
            if langsys is not None
            for feature_index in langsys.FeatureIndex
            if self._gsub.table.FeatureList.FeatureRecord[
                feature_index
            ].FeatureTag
            == feature_tag
        }
        self._feature_indices_by_tag[feature_tag] = feature_indices
        return feature_indices

    def _get_feature_adder(self, feature_index: int) -> GSUBFeatureRuleAdder:
        if feature_index not in self._feature_adders:
            self._feature_adders[feature_index] = GSUBFeatureRuleAdder(
                self._gsub, feature_index
            )
        return self._feature_adders[feature_index]

    def add_rule(
        self, feature_tag: Tag, target: str, replacements: list[str]
    ) -> None:
        feature_indices = self._get_feature_indices(feature_tag)
        for feature_index in feature_indices:
            self._get_feature_adder(feature_index).add_rule(
                target, replacements
            )
