from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any, Literal, cast

from fontTools.misc.textTools import Tag
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables import otTables as otTables_

from .error import AddGlyphUserError

if TYPE_CHECKING:
    from fontTools.ttLib.tables import G_S_U_B_


logger = logging.getLogger(__name__)

otTables = cast("Any", otTables_)


class GSUBInvariantViolation(AddGlyphUserError):
    pass


def _merge_alternates(left: list[str], right: Iterable[str]) -> list[str]:
    return left + [e for e in dict.fromkeys(right) if e not in left]


class GSUBLookupRuleAdder(ABC):
    def __init__(self, feature_tag: str) -> None:
        self._feature_tag = feature_tag

    @abstractmethod
    def try_add_rule(self, target: str, replacements: list[str]) -> bool:
        pass

    def _log_added(self, target: str, replacements: list[str]) -> None:
        logger.info(
            f"added: {self._feature_tag}: "
            f"{target} -> {', '.join(replacements)}"
        )

    def _log_already_in_font(
        self, target: str, replacements: list[str]
    ) -> None:
        logger.info(
            f"already in font: {self._feature_tag}: "
            f"{target} -> {', '.join(replacements)}"
        )


class GSUBSingleSubstRuleAdder(GSUBLookupRuleAdder):
    @abstractmethod
    def _get_subtables(self) -> list[otTables_.SingleSubst]:
        pass

    @abstractmethod
    def _add_subtable(self, subtable: otTables_.SingleSubst) -> None:
        pass

    def _new_subtable(self) -> otTables_.SingleSubst:
        subtable = otTables_.SingleSubst()
        subtable.mapping = {}
        self._add_subtable(subtable)
        return subtable

    def try_add_rule(self, target: str, replacements: list[str]) -> bool:
        if len(replacements) > 1:
            return False
        if not replacements:
            return True

        subtables = self._get_subtables()
        for subtable in subtables:
            mapping = cast("dict[str, str]", subtable.mapping)
            if target not in mapping:
                continue
            merged = _merge_alternates([mapping[target]], replacements)
            if merged == [mapping[target]]:
                self._log_already_in_font(target, merged)
                return True
            assert len(merged) > 1
            return False

        if subtables:
            subtable = subtables[0]
        else:
            subtable = self._new_subtable()

        mapping = cast("dict[str, str]", subtable.mapping)
        assert target not in mapping
        mapping[target] = replacements[0]
        self._log_added(target, replacements)
        return True

    def get_merged_mapping(self) -> dict[str, str]:
        mapping = {}
        for subtable in reversed(self._get_subtables()):
            mapping.update(subtable.mapping)
        return mapping


class GSUBAlternateSubstRuleAdder(GSUBLookupRuleAdder):
    @abstractmethod
    def _get_subtables(self) -> list[otTables_.AlternateSubst]:
        pass

    @abstractmethod
    def _add_subtable(self, subtable: otTables_.AlternateSubst) -> None:
        pass

    def _new_subtable(self) -> otTables_.AlternateSubst:
        subtable = otTables_.AlternateSubst()
        subtable.alternates = {}
        self._add_subtable(subtable)
        return subtable

    def try_add_rule(
        self, target: str, replacements: list[str]
    ) -> Literal[True]:
        if not replacements:
            return True

        subtables = self._get_subtables()
        for subtable in subtables:
            alternates = cast("dict[str, list[str]]", subtable.alternates)
            if target not in alternates:
                continue
            existing = alternates[target]
            new_alternates = _merge_alternates(existing, replacements)
            alternates[target] = new_alternates
            if existing != new_alternates:
                self._log_added(target, new_alternates)
            else:
                self._log_already_in_font(target, new_alternates)
            return True

        if subtables:
            subtable = subtables[0]
        else:
            subtable = self._new_subtable()

        alternates = cast("dict[str, list[str]]", subtable.alternates)
        assert target not in alternates
        alternates[target] = replacements
        self._log_added(target, replacements)
        return True


class GSUBLookupType1RuleAdder(GSUBSingleSubstRuleAdder):
    def __init__(self, feature_tag: str, lookup) -> None:
        super().__init__(feature_tag)
        self._lookup = lookup

    def _get_subtables(self) -> list[otTables_.SingleSubst]:
        subtables = self._lookup.SubTable
        assert all(
            isinstance(subtable, otTables_.SingleSubst)
            for subtable in subtables
        )
        return cast("list[otTables_.SingleSubst]", subtables)

    def _add_subtable(self, subtable: otTables_.SingleSubst) -> None:
        self._lookup.SubTable.append(subtable)
        self._lookup.SubTableCount += 1


class GSUBLookupType7SingleSubstRuleAdder(GSUBSingleSubstRuleAdder):
    def __init__(self, feature_tag: str, lookup) -> None:
        super().__init__(feature_tag)
        assert all(st.ExtensionLookupType == 1 for st in lookup.SubTable)
        self._lookup = lookup

    def _get_subtables(self) -> list[otTables_.SingleSubst]:
        subtables = [st.ExtSubTable for st in self._lookup.Subtable]
        assert all(
            isinstance(subtable, otTables_.SingleSubst)
            for subtable in subtables
        )
        return cast("list[otTables_.SingleSubst]", subtables)

    def _add_subtable(self, subtable: otTables_.SingleSubst) -> None:
        st = otTables.ExtensionSubst()
        st.Format = 1
        st.ExtensionLookupType = 1
        st.ExtSubTable = subtable
        self._lookup.SubTable.append(st)
        self._lookup.SubTableCount += 1


class GSUBLookupType3RuleAdder(GSUBAlternateSubstRuleAdder):
    def __init__(self, feature_tag: str, lookup) -> None:
        super().__init__(feature_tag)
        self._lookup = lookup

    def _get_subtables(self) -> list[otTables_.AlternateSubst]:
        subtables = self._lookup.SubTable
        assert all(
            isinstance(subtable, otTables_.AlternateSubst)
            for subtable in subtables
        )
        return cast("list[otTables_.AlternateSubst]", subtables)

    def _add_subtable(self, subtable: otTables_.AlternateSubst) -> None:
        self._lookup.SubTable.append(subtable)
        self._lookup.SubTableCount += 1


class GSUBLookupType7AlternateSubstRuleAdder(GSUBAlternateSubstRuleAdder):
    def __init__(self, feature_tag: str, lookup) -> None:
        super().__init__(feature_tag)
        assert all(st.ExtensionLookupType == 3 for st in lookup.SubTable)
        self._lookup = lookup

    def _get_subtables(self) -> list[otTables_.AlternateSubst]:
        subtables = [st.ExtSubTable for st in self._lookup.Subtable]
        assert all(
            isinstance(subtable, otTables_.AlternateSubst)
            for subtable in subtables
        )
        return cast("list[otTables_.AlternateSubst]", subtables)

    def _add_subtable(self, subtable: otTables_.AlternateSubst) -> None:
        st = otTables.ExtensionSubst()
        st.Format = 1
        st.ExtensionLookupType = 3
        st.ExtSubTable = subtable
        self._lookup.SubTable.append(st)
        self._lookup.SubTableCount += 1


class GSUBFeatureRuleAdder:
    def __init__(
        self,
        gsub: G_S_U_B_.table_G_S_U_B_,
        feature_index: int,
        lookup_adders: dict[int, GSUBLookupRuleAdder],
    ) -> None:
        self._gsub = gsub
        feature_record = gsub.table.FeatureList.FeatureRecord[feature_index]
        self._feature_tag = feature_record.FeatureTag
        self._feature = feature_record.Feature
        lookup_indices = cast("list[int]", self._feature.LookupListIndex)
        if len(lookup_indices) > 1:
            raise GSUBInvariantViolation(
                f"feature {self._feature_tag!r} has multiple lookups: "
                f"{lookup_indices!r}"
            )
        if lookup_indices:
            lookup_index = lookup_indices[0]
            lookup = gsub.table.LookupList.Lookup[lookup_index]
        else:
            lookup = otTables.Lookup()
            lookup.LookupType = 1
            lookup.LookupFlag = 0
            lookup.SubTableCount = 0
            lookup.SubTable = []
            lookup_index = len(gsub.table.LookupList.Lookup)
            gsub.table.LookupList.Lookup.append(lookup)
            gsub.table.LookupList.LookupCount += 1
            lookup_indices.append(lookup_index)
            self._feature.LookupCount += 1

        self._lookup_adders = lookup_adders
        self._lookup_index = lookup_index

        if lookup_index in lookup_adders:
            return

        if lookup.LookupType == 1:
            lookup_adder = GSUBLookupType1RuleAdder(self._feature_tag, lookup)
        elif lookup.LookupType == 3:
            lookup_adder = GSUBLookupType3RuleAdder(self._feature_tag, lookup)
        elif lookup.LookupType == 7:
            if lookup.SubTable:
                lookup_type = lookup.SubTable[0].ExtensionLookupType
            else:
                lookup_type = 1
            if lookup_type == 1:
                lookup_adder = GSUBLookupType7SingleSubstRuleAdder(
                    self._feature_tag, lookup
                )
            elif lookup_type == 3:
                lookup_adder = GSUBLookupType7AlternateSubstRuleAdder(
                    self._feature_tag, lookup
                )
            else:
                raise GSUBInvariantViolation(
                    f"feature {self._feature_tag!r} has lookup "
                    f"of unsupported type: {lookup_type}"
                )
        else:
            raise GSUBInvariantViolation(
                f"feature {self._feature_tag!r} has lookup "
                f"of unsupported type: {lookup.LookupType}"
            )

        lookup_adders[lookup_index] = lookup_adder

    def _upgrade_lookup_to_alternate(self) -> None:
        lookup_adder = self._lookup_adders[self._lookup_index]
        assert isinstance(lookup_adder, GSUBSingleSubstRuleAdder)
        mapping = lookup_adder.get_merged_mapping()

        new_subtable = otTables_.AlternateSubst()
        new_subtable.alternates = {
            target: [replacement] for target, replacement in mapping.items()
        }

        old_lookup = self._gsub.table.LookupList.Lookup[self._lookup_index]
        if old_lookup.LookupType == 1:
            new_lookup = otTables.Lookup()
            new_lookup.LookupType = 3
            new_lookup.LookupFlag = old_lookup.LookupFlag
            if old_lookup.LookupFlag & 0x0010:
                new_lookup.MarkFilteringSet = old_lookup.MarkFilteringSet
            new_lookup.SubTableCount = 1
            new_lookup.SubTable = [new_subtable]

            self._gsub.table.LookupList.Lookup[self._lookup_index] = new_lookup
            lookup_adder = GSUBLookupType3RuleAdder(
                self._feature_tag, new_lookup
            )
        elif old_lookup.LookupType == 7:
            new_st = otTables.ExtensionSubst()
            new_st.Format = 1
            new_st.ExtensionLookupType = 3
            new_st.ExtSubTable = new_subtable

            old_lookup.SubTableCount = 1
            old_lookup.SubTable = [new_st]
            lookup_adder = GSUBLookupType7AlternateSubstRuleAdder(
                self._feature_tag, old_lookup
            )
        else:
            assert False, f"unexpected lookup type: {old_lookup.LookupType}"

        self._lookup_adders[self._lookup_index] = lookup_adder

    def add_rule(self, target: str, replacements_: Iterable[str]) -> None:
        replacements = _merge_alternates([], replacements_)
        success = self._lookup_adders[self._lookup_index].try_add_rule(
            target, replacements
        )
        if success:
            return
        self._upgrade_lookup_to_alternate()
        success = self._lookup_adders[self._lookup_index].try_add_rule(
            target, replacements
        )
        assert success


class GSUBRuleAdder:
    def __init__(
        self, ttf: TTFont, language_systems: list[tuple[Tag, Tag]]
    ) -> None:
        self._gsub = cast("G_S_U_B_.table_G_S_U_B_", ttf["GSUB"])
        self._feature_indices_by_tag: dict[Tag, set[int]] = {}
        self._feature_adders: dict[int, GSUBFeatureRuleAdder] = {}
        self._lookup_adders: dict[int, GSUBLookupRuleAdder] = {}

        self._dflt_langsys = self._get_dflt_langsys(
            self._gsub, language_systems
        )

        self._initial_lookup_count: int = (
            self._gsub.table.LookupList.LookupCount
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
                self._gsub, feature_index, self._lookup_adders
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

    def reorder_lookups(self):
        # If the original font has lookups for "vert" or "vrt2" features at
        # the end of the lookup list, keep them at the end.

        initial_lookup_count = self._initial_lookup_count

        # If no lookup was added, do nothing
        if self._gsub.table.LookupList.LookupCount == initial_lookup_count:
            return

        to_be_final_lookup_indices: set[int] = set()
        for feature_record in self._gsub.table.FeatureList.FeatureRecord:
            if feature_record.FeatureTag in ("vert", "vrt2"):
                to_be_final_lookup_indices.update(
                    cast("list[int]", feature_record.Feature.LookupListIndex)
                )

        insertion_position = initial_lookup_count
        while insertion_position - 1 in to_be_final_lookup_indices:
            insertion_position -= 1

        if insertion_position == initial_lookup_count:
            return

        self._lookup_adders.clear()

        index_lookup = list(enumerate(self._gsub.table.LookupList.Lookup))
        index_lookup[insertion_position:] = (
            index_lookup[initial_lookup_count:]
            + index_lookup[insertion_position:initial_lookup_count]
        )
        self._gsub.table.LookupList.Lookup[:] = [
            lookup for _, lookup in index_lookup
        ]

        index_mapping = {
            old_index: new_index
            for new_index, (old_index, _) in enumerate(index_lookup)
        }

        # Remap lookup indices in lookups
        for st in [
            st
            for lookup in self._gsub.table.LookupList.Lookup
            for st in lookup.SubTable
        ]:
            if isinstance(st, otTables.ExtensionSubst):
                st = st.ExtSubTable

            subst_lookup_records = []
            if isinstance(st, otTables.ContextSubst):
                if st.Format == 1:
                    subst_lookup_records = [
                        lr
                        for rs in st.SubRuleSet
                        for r in rs.SubRule
                        for lr in r.SubstLookupRecord
                    ]
                elif st.Format == 2:
                    subst_lookup_records = [
                        lr
                        for rs in st.SubClassSet
                        for r in rs.SubClassRule
                        for lr in r.SubstLookupRecord
                    ]
                elif st.Format == 3:
                    subst_lookup_records = st.SubstLookupRecord
            if isinstance(st, otTables.ChainContextSubst):
                if st.Format == 1:
                    subst_lookup_records = [
                        lr
                        for rs in st.ChainSubRuleSet
                        for r in rs.ChainSubRule
                        for lr in r.SubstLookupRecord
                    ]
                elif st.Format == 2:
                    subst_lookup_records = [
                        lr
                        for rs in st.ChainSubClassSet
                        for r in rs.ChainSubClassRule
                        for lr in r.SubstLookupRecord
                    ]
                elif st.Format == 3:
                    subst_lookup_records = st.SubstLookupRecord
            for lr in subst_lookup_records:
                lr.LookupListIndex = index_mapping[lr.LookupListIndex]

        # Remap lookup indices in features
        features = [
            feature_record.Feature
            for feature_record in self._gsub.table.FeatureList.FeatureRecord
        ]
        if hasattr(self._gsub.table, "FeatureVariations"):
            feature_variations = self._gsub.table.FeatureVariations
            features += [
                sr.Feature
                for vr in feature_variations.FeatureVariationRecord
                for sr in vr.FeatureTableSubstitution.SubstitutionRecord
            ]
        for feature in features:
            feature.LookupListIndex = [
                index_mapping[lookup_index]
                for lookup_index in feature.LookupListIndex
            ]
