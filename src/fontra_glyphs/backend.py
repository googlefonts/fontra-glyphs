import io
import pathlib
import uuid
from collections import defaultdict
from copy import deepcopy
from os import PathLike
from typing import Any

import glyphsLib
import openstep_plist
from fontra.core.classes import (
    Anchor,
    Axes,
    Component,
    DiscreteFontAxis,
    FontAxis,
    FontInfo,
    FontSource,
    GlyphAxis,
    GlyphSource,
    Guideline,
    ImageData,
    Kerning,
    Layer,
    LineMetric,
    OpenTypeFeatures,
    StaticGlyph,
    VariableGlyph,
)
from fontra.core.path import PackedPathPointPen
from fontra.core.protocols import WritableFontBackend
from fontra.core.varutils import makeDenseLocation, makeSparseLocation
from fontTools.designspaceLib import DesignSpaceDocument
from fontTools.misc.transform import DecomposedTransform
from fontTools.ufoLib.filenames import userNameToFileName
from glyphsLib.builder.axes import (
    AxisDefinitionFactory,
    get_axis_definitions,
    get_regular_master,
    to_designspace_axes,
)
from glyphsLib.builder.smart_components import Pole
from glyphsLib.types import Transform as GSTransform

from .utils import (
    convertMatchesToTuples,
    getAssociatedMasterId,
    matchTreeFont,
    matchTreeGlyph,
    openstepPlistDumps,
    splitLocation,
)

rootInfoNames = [
    "familyName",
    "versionMajor",
    "versionMinor",
]


infoNamesMapping = [
    # (Fontra, Glyphs)
    ("copyright", "copyrights"),
    ("designer", "designers"),
    ("designerURL", "designerURL"),
    ("licenseDescription", "licenses"),
    # ("licenseInfoURL", "licensesURL"),  # Not defined in glyphsLib
    ("manufacturer", "manufacturers"),
    ("manufacturerURL", "manufacturerURL"),
    ("trademark", "trademarks"),
    ("vendorID", "vendorID"),
]

GS_KERN_GROUP_PREFIXES = {
    side: f"@MMK_{side[0].upper()}_" for side in ["left", "right", "top", "bottom"]
}
FONTRA_KERN_GROUP_PREFIXES = {
    "left": "public.kern1.",
    "right": "public.kern2.",
    "top": "kern.top.",
    "bottom": "kern.bottom.",
}
GS_FORMAT_2_KERN_SIDES = [
    # pair side, glyph side
    ("left", "rightKerningGroup"),
    ("right", "leftKerningGroup"),
    ("top", "bottomKerningGroup"),
    ("bottom", "topKerningGroup"),
]
GS_FORMAT_3_KERN_SIDES = [
    # pair side, glyph side
    ("left", "kernRight"),
    ("right", "kernLeft"),
    ("top", "kernBottom"),
    ("bottom", "kernTop"),
]


class GlyphsBackend:
    @classmethod
    def fromPath(cls, path: PathLike) -> WritableFontBackend:
        self = cls()
        self._setupFromPath(path)
        return self

    def _setupFromPath(self, path: PathLike) -> None:
        gsFont = glyphsLib.classes.GSFont()
        self.gsFilePath = pathlib.Path(path)

        rawFontData, rawGlyphsData = self._loadFiles(path)

        parser = glyphsLib.parser.Parser(current_type=gsFont.__class__)
        parser.parse_into_object(gsFont, rawFontData)

        self.gsFont = gsFont

        # Fill the glyphs list with dummy placeholder glyphs
        self.gsFont.glyphs = [
            glyphsLib.classes.GSGlyph() for i in range(len(rawGlyphsData))
        ]
        self.rawFontData = rawFontData
        self.rawGlyphsData = rawGlyphsData

        self.glyphNameToIndex = {
            glyphData["glyphname"]: i for i, glyphData in enumerate(rawGlyphsData)
        }
        self.parsedGlyphNames: set[str] = set()

        dsAxes = [
            dsAxis
            for dsAxis in gsAxesToDesignSpaceAxes(self.gsFont)
            # Ignore axes without any range
            if dsAxis.minimum != dsAxis.maximum
        ]

        self.axisNames = {axis.name for axis in dsAxes}

        self.locationByMasterID = {}
        for master in self.gsFont.masters:
            location = {}
            for axisDef in get_axis_definitions(self.gsFont):
                if axisDef.name in self.axisNames:
                    location[axisDef.name] = axisDef.get_design_loc(master)
            self.locationByMasterID[master.id] = location

        self.glyphMap, self.kerningGroups = _readGlyphMapAndKerningGroups(
            rawGlyphsData,
            self.gsFont.format_version,
        )

        axis: FontAxis | DiscreteFontAxis
        axes: list[FontAxis | DiscreteFontAxis] = []
        for dsAxis in dsAxes:
            axis = FontAxis(
                minValue=dsAxis.minimum,
                defaultValue=dsAxis.default,
                maxValue=dsAxis.maximum,
                label=dsAxis.name,
                name=dsAxis.name,
                tag=dsAxis.tag,
                hidden=dsAxis.hidden,
            )
            if dsAxis.map:
                axis.mapping = [[a, b] for a, b in dsAxis.map]
            axes.append(axis)
        self.axes = axes

        self.defaultLocation = {}
        for axis in self.axes:
            self.defaultLocation[axis.name] = next(
                (v for k, v in axis.mapping if k == axis.defaultValue),
                axis.defaultValue,
            )

    @staticmethod
    def _loadFiles(path: PathLike) -> tuple[dict[str, Any], list[Any]]:
        with open(path, "r", encoding="utf-8") as fp:
            rawFontData = openstep_plist.load(fp, use_numbers=True)

        # We separate the "glyphs" list from the rest, so we can prevent glyphsLib
        # from eagerly parsing all glyphs
        rawGlyphsData = rawFontData["glyphs"]
        rawFontData["glyphs"] = []
        return rawFontData, rawGlyphsData

    async def getGlyphMap(self) -> dict[str, list[int]]:
        return deepcopy(self.glyphMap)

    async def putGlyphMap(self, value: dict[str, list[int]]) -> None:
        pass

    async def deleteGlyph(self, glyphName):
        raise NotImplementedError(
            "GlyphsApp Backend: Deleting glyphs is not yet implemented."
        )

    async def getFontInfo(self) -> FontInfo:
        infoDict = {}
        for name in rootInfoNames:
            value = getattr(self.gsFont, name, None)
            if value is not None:
                infoDict[name] = value

        properties = {p.key: p.value for p in self.gsFont.properties}
        for fontraName, glyphsName in infoNamesMapping:
            value = properties.get(glyphsName)
            if value is not None:
                infoDict[fontraName] = value

        return FontInfo(**infoDict)

    async def putFontInfo(self, fontInfo: FontInfo):
        raise NotImplementedError(
            "GlyphsApp Backend: Editing FontInfo is not yet implemented."
        )

    async def getSources(self) -> dict[str, FontSource]:
        return gsMastersToFontraFontSources(self.gsFont, self.locationByMasterID)

    async def putSources(self, sources: dict[str, FontSource]) -> None:
        raise NotImplementedError(
            "GlyphsApp Backend: Editing FontSources is not yet implemented."
        )

    async def getAxes(self) -> Axes:
        return Axes(axes=deepcopy(self.axes))

    async def putAxes(self, axes: Axes) -> None:
        raise NotImplementedError(
            "GlyphsApp Backend: Editing Axes is not yet implemented."
        )

    async def getUnitsPerEm(self) -> int:
        return self.gsFont.upm

    async def putUnitsPerEm(self, value: int) -> None:
        raise NotImplementedError(
            "GlyphsApp Backend: Editing UnitsPerEm is not yet implemented."
        )

    async def getKerning(self) -> dict[str, Kerning]:
        # TODO: RTL kerning: https://docu.glyphsapp.com/#GSFont.kerningRTL
        kerningLTR = gsKerningToFontraKerning(
            self.gsFont, self.kerningGroups, "kerning", "left", "right"
        )
        kerningAttr = (
            "vertKerning" if self.gsFont.format_version == 2 else "kerningVertical"
        )
        kerningVertical = gsKerningToFontraKerning(
            self.gsFont, self.kerningGroups, kerningAttr, "top", "bottom"
        )

        kerning = {}
        if kerningLTR.values:
            kerning["kern"] = kerningLTR
        if kerningVertical.values:
            kerning["vkrn"] = kerningVertical
        return kerning

    async def putKerning(self, kerning: dict[str, Kerning]) -> None:
        raise NotImplementedError(
            "GlyphsApp Backend: Editing Kerning is not yet implemented."
        )

    async def getFeatures(self) -> OpenTypeFeatures:
        # TODO: extract features
        return OpenTypeFeatures()

    async def putFeatures(self, features: OpenTypeFeatures) -> None:
        raise NotImplementedError(
            "GlyphsApp Backend: Editing OpenTypeFeatures is not yet implemented."
        )

    async def getBackgroundImage(self, imageIdentifier: str) -> ImageData | None:
        return None

    async def putBackgroundImage(self, imageIdentifier: str, data: ImageData) -> None:
        raise NotImplementedError(
            "GlyphsApp Backend: Editing BackgroundImage is not yet implemented."
        )

    async def getCustomData(self) -> dict[str, Any]:
        return {}

    async def putCustomData(self, lib):
        raise NotImplementedError(
            "GlyphsApp Backend: Editing CustomData is not yet implemented."
        )

    async def getGlyph(self, glyphName: str) -> VariableGlyph | None:
        if glyphName not in self.glyphNameToIndex:
            return None

        self._ensureGlyphIsParsed(glyphName)

        gsGlyph = self.gsFont.glyphs[glyphName]

        customData = {}
        if gsGlyph.color is not None:
            customData["com.glyphsapp.glyph-color"] = gsGlyph.color

        localAxes = gsLocalAxesToFontraLocalAxes(gsGlyph)
        localAxesByName = {axis.name: axis for axis in localAxes}
        sources = []
        layers = {}

        seenMasterIDs: dict[str, None] = {}
        gsLayers = []
        for i, gsLayer in enumerate(gsGlyph.layers):
            gsLayers.append((i, gsLayer))
            assert gsLayer.associatedMasterId
            # We use a dict as a set, because we need the insertion order
            seenMasterIDs[gsLayer.associatedMasterId] = None

        masterOrder = {masterID: i for i, masterID in enumerate(seenMasterIDs)}
        gsLayers = sorted(
            gsLayers, key=lambda i_gsLayer: masterOrder[i_gsLayer[1].associatedMasterId]
        )

        seenLocations = []
        for i, gsLayer in gsLayers:
            braceLocation = self._getBraceLayerLocation(gsLayer)
            smartLocation = self._getSmartLocation(gsLayer, localAxesByName)
            masterName = self.gsFont.masters[gsLayer.associatedMasterId].name
            if "xyz.fontra.source-name" in gsLayer.userData:
                sourceName = gsLayer.userData["xyz.fontra.source-name"]
            elif braceLocation or smartLocation:
                sourceName = f"{masterName} / {gsLayer.name}"
            else:
                sourceName = gsLayer.name or masterName
            layerName = gsLayer.userData["xyz.fontra.layer-name"] or gsLayer.layerId

            location = {
                **makeSparseLocation(
                    self.locationByMasterID[gsLayer.associatedMasterId],
                    self.defaultLocation,
                ),
                **braceLocation,
                **smartLocation,
            }

            if location in seenLocations:
                layerName = f"{gsLayer.associatedMasterId}^{gsLayer.name}"
            else:
                seenLocations.append(location)
                sources.append(
                    GlyphSource(
                        name=sourceName,
                        location=location,
                        layerName=layerName,
                    )
                )
            layers[layerName] = gsLayerToFontraLayer(
                gsLayer, self.axisNames, gsLayer.width
            )
            if gsLayer.hasBackground:
                layers[layerName + "^background"] = gsLayerToFontraLayer(
                    gsLayer.background, self.axisNames, gsLayer.width
                )

        fixSourceLocations(sources, set(smartLocation))

        glyph = VariableGlyph(
            name=glyphName,
            axes=localAxes,
            sources=sources,
            layers=layers,
            customData=customData,
        )
        return glyph

    def _ensureGlyphIsParsed(self, glyphName: str) -> None:
        if glyphName in self.parsedGlyphNames:
            return

        glyphIndex = self.glyphNameToIndex[glyphName]
        rawGlyphData = self.rawGlyphsData[glyphIndex]
        self.parsedGlyphNames.add(glyphName)

        gsGlyph = glyphsLib.classes.GSGlyph()
        p = glyphsLib.parser.Parser(
            current_type=gsGlyph.__class__, format_version=self.gsFont.format_version
        )
        p.parse_into_object(gsGlyph, rawGlyphData)
        self.gsFont.glyphs[glyphIndex] = gsGlyph

        # Load all component dependencies
        componentNames = set()
        for layer in gsGlyph.layers:
            for component in layer.components:
                componentNames.add(component.name)

        for compoName in sorted(componentNames):
            self._ensureGlyphIsParsed(compoName)

    def _getBraceLayerLocation(self, gsLayer):
        if not gsLayer._is_brace_layer():
            return {}

        return dict(
            (axis.name, value)
            for axis, value in zip(self.axes, gsLayer._brace_coordinates())
        )

    def _getSmartLocation(self, gsLayer, localAxesByName):
        location = {
            name: (
                localAxesByName[name].minValue
                if poleValue == Pole.MIN
                else localAxesByName[name].maxValue
            )
            for name, poleValue in gsLayer.smartComponentPoleMapping.items()
        }
        return {
            disambiguateLocalAxisName(name, self.axisNames): value
            for name, value in location.items()
            if value != localAxesByName[name].defaultValue
        }

    async def putGlyph(
        self, glyphName: str, glyph: VariableGlyph, codePoints: list[int]
    ) -> None:
        assert isinstance(codePoints, list)
        assert all(isinstance(cp, int) for cp in codePoints)
        self.glyphMap[glyphName] = codePoints

        isNewGlyph = glyphName not in self.gsFont.glyphs
        # Glyph does not exist: create new one.
        if isNewGlyph:
            gsGlyph = glyphsLib.classes.GSGlyph(glyphName)
            self.gsFont.glyphs.append(gsGlyph)
            self.glyphNameToIndex[glyphName] = len(self.gsFont.glyphs) - 1

        # Convert VariableGlyph to GSGlyph
        gsGlyphNew = variableGlyphToGSGlyph(
            self.defaultLocation,
            glyph,
            deepcopy(self.gsFont.glyphs[glyphName]),
            self.locationByMasterID,
        )

        # Update unicodes: need to be converted from decimal to hex strings
        gsGlyphNew.unicodes = [str(hex(codePoint)) for codePoint in codePoints]

        # Serialize to text with glyphsLib.writer.Writer(), using io.StringIO
        f = io.StringIO()
        writer = glyphsLib.writer.Writer(f)
        writer.format_version = self.gsFont.format_version
        writer.write(gsGlyphNew)

        # Parse stream into "raw" object
        f.seek(0)
        rawGlyphData = openstep_plist.load(f, use_numbers=True)

        # Replace original "raw" object with new "raw" object
        glyphIndex = self.glyphNameToIndex[glyphName]
        if isNewGlyph:
            assert glyphIndex == len(self.rawGlyphsData)
            self.rawGlyphsData.append(rawGlyphData)
        else:
            self.rawGlyphsData[glyphIndex] = rawGlyphData

        self._writeRawGlyph(glyphName, isNewGlyph)

        # Remove glyph from parsed glyph names, because we changed it.
        # Next time it needs to be parsed again.
        self.parsedGlyphNames.discard(glyphName)

    def _writeRawGlyph(self, glyphName, isNewGlyph):
        # Write whole file with openstep_plist
        # 'glyphName' and 'isNewGlyph' arguments not used, because we write the whole file,
        # but is required for the glyphspackge backend
        rawFontData = dict(self.rawFontData)
        rawFontData["glyphs"] = self.rawGlyphsData

        rawFontData = convertMatchesToTuples(rawFontData, matchTreeFont)
        out = openstepPlistDumps(rawFontData)
        self.gsFilePath.write_text(out)

    async def aclose(self) -> None:
        pass


class GlyphsPackageBackend(GlyphsBackend):
    @staticmethod
    def _loadFiles(path: PathLike) -> tuple[dict[str, Any], list[Any]]:
        packagePath = pathlib.Path(path)
        fontInfoPath = packagePath / "fontinfo.plist"
        orderPath = packagePath / "order.plist"
        glyphsPath = packagePath / "glyphs"

        glyphOrder = []
        if orderPath.exists():
            with open(orderPath, "r", encoding="utf-8") as fp:
                glyphOrder = openstep_plist.load(fp)
        glyphNameToIndex = {glyphName: i for i, glyphName in enumerate(glyphOrder)}

        with open(fontInfoPath, "r", encoding="utf-8") as fp:
            rawFontData = openstep_plist.load(fp, use_numbers=True)

        rawFontData["glyphs"] = []

        rawGlyphsData = []
        for glyphfile in glyphsPath.glob("*.glyph"):
            with open(glyphfile, "r") as fp:
                glyphData = openstep_plist.load(fp, use_numbers=True)
            rawGlyphsData.append(glyphData)

        def sortKey(glyphData):
            glyphName = glyphData["glyphname"]
            index = glyphNameToIndex.get(glyphName)
            if index is not None:
                return (0, index)
            else:
                return (1, glyphName)

        rawGlyphsData.sort(key=sortKey)

        return rawFontData, rawGlyphsData

    def _writeRawGlyph(self, glyphName, isNewGlyph):
        rawGlyphData = self.rawGlyphsData[self.glyphNameToIndex[glyphName]]
        rawGlyphData = convertMatchesToTuples(rawGlyphData, matchTreeGlyph)
        out = openstepPlistDumps(rawGlyphData)
        filePath = self.getGlyphFilePath(glyphName)
        filePath.write_text(out, encoding="utf=8")

        if isNewGlyph:
            filePathGlyphOrder = self.gsFilePath / "order.plist"
            glyphOrder = [glyph["glyphname"] for glyph in self.rawGlyphsData]
            out = openstepPlistDumps(glyphOrder)
            filePathGlyphOrder.write_text(out, encoding="utf=8")

    def getGlyphFilePath(self, glyphName):
        glyphsPath = self.gsFilePath / "glyphs"
        refFileName = userNameToFileName(glyphName, suffix=".glyph")
        return glyphsPath / refFileName


def _readGlyphMapAndKerningGroups(
    rawGlyphsData: list, formatVersion: int
) -> tuple[dict[str, list[int]], dict[str, tuple[str, str]]]:
    glyphMap = {}
    kerningGroups: dict = defaultdict(lambda: defaultdict(list))

    sideAttrs = GS_FORMAT_2_KERN_SIDES if formatVersion == 2 else GS_FORMAT_3_KERN_SIDES

    for glyphData in rawGlyphsData:
        glyphName = glyphData["glyphname"]

        # extract code points
        codePoints = glyphData.get("unicode")
        if codePoints is None:
            codePoints = []
        elif formatVersion == 2:
            if isinstance(codePoints, str):
                codePoints = [int(codePoint, 16) for codePoint in codePoints.split(",")]
            else:
                assert isinstance(codePoints, int)
                # The plist parser turned it into an int, but it was a hex string
                codePoints = [int(str(codePoints), 16)]
        elif isinstance(codePoints, int):
            codePoints = [codePoints]
        else:
            assert all(isinstance(codePoint, int) for codePoint in codePoints)
        glyphMap[glyphName] = codePoints

        # extract kern groups
        for pairSide, glyphSideAttr in sideAttrs:
            groupName = glyphData.get(glyphSideAttr)
            if groupName is not None:
                kerningGroups[pairSide][
                    FONTRA_KERN_GROUP_PREFIXES[pairSide] + groupName
                ].append(glyphName)

    return glyphMap, kerningGroups


def gsLayerToFontraLayer(gsLayer, globalAxisNames, gsLayerWidth):
    pen = PackedPathPointPen()
    gsLayer.drawPoints(pen)

    components = [
        gsComponentToFontraComponent(gsComponent, gsLayer, globalAxisNames)
        for gsComponent in gsLayer.components
    ]

    anchors = [gsAnchorToFontraAnchor(gsAnchor) for gsAnchor in gsLayer.anchors]
    guidelines = [
        gsGuidelineToFontraGuideline(gsGuideline) for gsGuideline in gsLayer.guides
    ]

    return Layer(
        glyph=StaticGlyph(
            xAdvance=gsLayerWidth,
            path=pen.getPath(),
            components=components,
            anchors=anchors,
            guidelines=guidelines,
        ),
        customData={
            "com.glyphsapp.layer.layerId": gsLayer.layerId,
        },
    )


def gsComponentToFontraComponent(gsComponent, gsLayer, globalAxisNames):
    component = Component(
        name=gsComponent.name,
        transformation=DecomposedTransform.fromTransform(gsComponent.transform),
        location={
            disambiguateLocalAxisName(name, globalAxisNames): value
            for name, value in gsComponent.smartComponentValues.items()
        },
    )
    if gsComponent.alignment:
        # The aligment can be 0, but in that case, do not set it.
        component.customData["com.glyphsapp.component.alignment"] = (
            gsComponent.alignment
        )
    return component


def disambiguateLocalAxisName(axisName, globalAxisNames):
    return f"{axisName} (local)" if axisName in globalAxisNames else axisName


def gsAnchorToFontraAnchor(gsAnchor):
    anchor = Anchor(
        name=gsAnchor.name,
        x=gsAnchor.position.x,
        y=gsAnchor.position.y,
        # TODO: gsAnchor.orientation – If the position of the anchor
        # is relative to the LSB (0), center (2) or RSB (1).
        # Details: https://docu.glyphsapp.com/#GSAnchor.orientation
        customData=gsAnchor.userData if gsAnchor.userData else dict(),
    )
    return anchor


def gsGuidelineToFontraGuideline(gsGuideline):
    return Guideline(
        x=gsGuideline.position.x,
        y=gsGuideline.position.y,
        angle=gsGuideline.angle,
        name=gsGuideline.name,
        locked=gsGuideline.locked,
    )


class MinimalUFOBuilder:
    def __init__(self, gsFont):
        self.font = gsFont
        self.designspace = DesignSpaceDocument()
        self.minimize_glyphs_diffs = False

    to_designspace_axes = to_designspace_axes


def gsAxesToDesignSpaceAxes(gsFont):
    builder = MinimalUFOBuilder(gsFont)
    builder.to_designspace_axes()
    return builder.designspace.axes


def gsLocalAxesToFontraLocalAxes(gsGlyph):
    basePoleMapping = gsGlyph.layers[0].smartComponentPoleMapping
    return [
        GlyphAxis(
            name=axis.name,
            minValue=axis.bottomValue,
            defaultValue=(
                axis.bottomValue
                if basePoleMapping[axis.name] == Pole.MIN
                else axis.topValue
            ),
            maxValue=axis.topValue,
        )
        for axis in gsGlyph.smartComponentAxes
    ]


def fixSourceLocations(sources, smartAxisNames):
    # If a set of sources is equally controlled by a font axis and a glyph axis
    # (smart axis), then the font axis should be ignored. This makes our
    # varLib-based variation model behave like Glyphs.
    sets = defaultdict(set)
    for i, source in enumerate(sources):
        for locItem in source.location.items():
            sets[locItem].add(i)

    reverseSets = defaultdict(set)
    for locItem, sourceIndices in sets.items():
        reverseSets[tuple(sorted(sourceIndices))].add(locItem)

    matches = [locItems for locItems in reverseSets.values() if len(locItems) > 1]

    locItemsToDelete = []
    for locItems in matches:
        for axis, value in locItems:
            if axis not in smartAxisNames:
                locItemsToDelete.append((axis, value))

    for axis, value in locItemsToDelete:
        for source in sources:
            if source.location.get(axis) == value:
                del source.location[axis]


def translateGroupName(name, oldPrefix, newPrefix):
    return newPrefix + name[len(oldPrefix) :] if name.startswith(oldPrefix) else name


def gsKerningToFontraKerning(
    gsFont, groupsBySide, kerningAttr, side1, side2
) -> Kerning:
    gsPrefix1 = GS_KERN_GROUP_PREFIXES[side1]
    gsPrefix2 = GS_KERN_GROUP_PREFIXES[side2]
    fontraPrefix1 = FONTRA_KERN_GROUP_PREFIXES[side1]
    fontraPrefix2 = FONTRA_KERN_GROUP_PREFIXES[side2]

    groups = dict(groupsBySide[side1] | groupsBySide[side2])

    sourceIdentifiers = []
    valueDicts: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(dict))

    defaultMasterID = get_regular_master(gsFont).id

    for gsMaster in gsFont.masters:
        kernDict = getattr(gsFont, kerningAttr, {}).get(gsMaster.id, {})
        if not kernDict and gsMaster.id != defaultMasterID:
            # Even if the default master does not contain kerning, it makes life
            # easier down the road if we include this empty kerning, lest we run
            # into "missing base master"-type interpolation errors.
            continue

        sourceIdentifiers.append(gsMaster.id)

        for name1, name2Dict in kernDict.items():
            name1 = translateGroupName(name1, gsPrefix1, fontraPrefix1)

            for name2, value in name2Dict.items():
                name2 = translateGroupName(name2, gsPrefix2, fontraPrefix2)
                valueDicts[name1][name2][gsMaster.id] = value

    values = {
        left: {
            right: [valueDict.get(key) for key in sourceIdentifiers]
            for right, valueDict in rightDict.items()
        }
        for left, rightDict in valueDicts.items()
    }

    return Kerning(groups=groups, sourceIdentifiers=sourceIdentifiers, values=values)


def gsMastersToFontraFontSources(gsFont, locationByMasterID):
    sources = {}
    for gsMaster in gsFont.masters:
        sources[gsMaster.id] = FontSource(
            name=gsMaster.name,
            italicAngle=gsMaster.italicAngle,
            location=locationByMasterID[gsMaster.id],
            lineMetricsHorizontalLayout=gsVerticalMetricsToFontraLineMetricsHorizontal(
                gsFont, gsMaster
            ),
            guidelines=[
                gsGuidelineToFontraGuideline(gsGuideline)
                for gsGuideline in gsMaster.guides
            ],
        )
    return sources


def gsToFontraZone(gsVerticalMetricsValue, gsAlignmentZones):
    for gsZone in gsAlignmentZones:
        if gsZone.position == gsVerticalMetricsValue:
            return gsZone.size
    return 0


def gsVerticalMetricsToFontraLineMetricsHorizontal(gsFont, gsMaster):
    lineMetricsHorizontal = {
        "ascender": LineMetric(
            value=gsMaster.ascender,
            zone=gsToFontraZone(gsMaster.ascender, gsMaster.alignmentZones),
        ),
        "capHeight": LineMetric(
            value=gsMaster.capHeight,
            zone=gsToFontraZone(gsMaster.capHeight, gsMaster.alignmentZones),
        ),
        "xHeight": LineMetric(
            value=gsMaster.xHeight,
            zone=gsToFontraZone(gsMaster.xHeight, gsMaster.alignmentZones),
        ),
        "baseline": LineMetric(
            value=0, zone=gsToFontraZone(0, gsMaster.alignmentZones)
        ),
        "descender": LineMetric(
            value=gsMaster.descender,
            zone=gsToFontraZone(gsMaster.descender, gsMaster.alignmentZones),
        ),
    }

    # TODO: custom metrics https://docu.glyphsapp.com/#GSFontMaster.metrics
    # Custom vertical metrics seem not to work with GlyphsLib, currently.
    # The following code works within GlyphsApp, but not with GlyphsLib.
    # for gsMetric in gsFont.metrics:
    #     if gsMetric.name:
    #         # if it has a name, it is a custom vertical metric
    #         gsMetricValue = gsMaster.metricValues[gsMetric.id]
    #         print('position: ', gsMetricValue.position)
    #         print('overshoot: ', gsMetricValue.overshoot)
    #         lineMetricsHorizontal[gsMetric.name] = LineMetric(
    #             value=gsMetricValue.position,
    #             zone=gsToFontraZone(gsMetricValue.overshoot, gsMaster.alignmentZones)
    #         )

    return lineMetricsHorizontal


def variableGlyphToGSGlyph(defaultLocation, variableGlyph, gsGlyph, locationByMasterID):
    defaultGlyphLocation = {axis.name: axis.defaultValue for axis in variableGlyph.axes}
    gsMasterAxesToIdMapping = {tuple(m.axes): m.id for m in gsGlyph.parent.masters}
    gsMasterIdToNameMapping = {m.id: m.name for m in gsGlyph.parent.masters}
    # Convert Fontra variableGlyph to GlyphsApp glyph
    layerIdsInUse = [
        variableGlyph.layers[layerName].customData.get("com.glyphsapp.layer.layerId")
        for layerName in variableGlyph.layers
    ]
    for gsLayerId in [gsLayer.layerId for gsLayer in gsGlyph.layers]:
        if gsLayerId in layerIdsInUse:
            # This layer will be modified later.
            continue
        # Removing layer:
        del gsGlyph.layers[gsLayerId]

    fontraGlyphAxesToGSSmartComponentAxes(variableGlyph, gsGlyph)
    isSmartCompGlyph = len(gsGlyph.smartComponentAxes) > 0

    nonSourceLayerNames = set()
    layerNameToGlyphSourceMapping = {
        glyphSource.layerName: glyphSource for glyphSource in variableGlyph.sources
    }
    for layerName in variableGlyph.layers:
        layer = variableGlyph.layers[layerName]
        # "^" not in layerName:
        # layerName is equal to gsLayer.layerId if it comes from Glyphsapp,
        # otherwise the layer has been newly created within Fontra.

        layerNameDescriptor = None
        associatedMasterId = None
        if "^" in layerName:
            # Example: <parent-layer-name>^<background-layer-name>
            # Example: <masterId>^background
            glyphSourceLayerName, layerNameDescriptor = layerName.split("^")
            associatedMasterId = glyphSourceLayerName
        else:
            glyphSourceLayerName = layerName

        glyphSource = layerNameToGlyphSourceMapping.get(glyphSourceLayerName)
        if glyphSource is None:
            nonSourceLayerNames.add(layerName)
            continue

        if layerNameDescriptor == "background":
            # Here it get's complicated, keyword: "nested background layers".
            # In glyphsapp every layer may have a backgrlound. This is different for Fontra.
            # A background in Fontra is a layer, only named differently.
            gsLayer = gsGlyph.layers[glyphSourceLayerName]
            if gsLayer:
                # https://github.com/googlefonts/glyphsLib/blob/c4db6b981d577f456d64ebe9993818770e170454/tests/classes_test.py#L1818
                bgLayer = gsLayer.background
                bgLayer.width = gsLayer.width
                # A background layer does not have it's own layerId,
                # because it it always part of a different layer.
                # Therefore set to empty string.
                layer.customData["com.glyphsapp.layer.layerId"] = ""
                fontraLayerToGSLayer(layer, bgLayer)
                continue
            else:
                print("something went wrong.")
                continue
        elif layerNameDescriptor:
            gsLayerId = layer.customData.get("com.glyphsapp.layer.layerId")
            gsLayer = gsGlyph.layers[gsLayerId]
        else:
            gsLayer = gsGlyph.layers[layerName]

        fontLocation, glyphLocation = splitLocation(
            glyphSource.location, variableGlyph.axes
        )

        baseLocation = (
            {}
            if glyphSource.locationBase is None
            else locationByMasterID[glyphSource.locationBase]
        )
        location = baseLocation | glyphSource.location
        fontLocation, glyphLocation = splitLocation(location, variableGlyph.axes)
        fontLocation = makeDenseLocation(fontLocation, defaultLocation)
        glyphLocation = makeDenseLocation(glyphLocation, defaultGlyphLocation)

        if gsLayer is not None:
            # gsLayer exists – modify existing gsLayer:
            fontraLayerToGSLayer(layer, gsLayer)
            # It might be, that we added a new glyph axis within Fontra
            # for an existing smart comp glyph, in that case we need to add
            # the new axis to gsLayer.smartComponentPoleMapping.
            fontraGlyphAxesToGSLayerSmartComponentPoleMapping(
                variableGlyph.axes, gsLayer, glyphLocation
            )

            gsLayer.smartComponentPoleMapping = {
                axisName: pole
                for axisName, pole in gsLayer.smartComponentPoleMapping.items()
                if axisName in defaultGlyphLocation
            }
        else:
            # gsLayer does not exist – create new layer:
            gsLayer = glyphsLib.classes.GSLayer()
            gsLayer.parent = gsGlyph

            gsFontLocation = []
            for axis in gsGlyph.parent.axes:
                if axis.name in fontLocation:
                    gsFontLocation.append(fontLocation[axis.name])
                else:
                    # This 'else' is necessary for GlyphsApp 2 files, only.
                    # 'Weight' and 'Width' are always there,
                    # even if there is no axis specified for it.
                    factory = AxisDefinitionFactory()
                    axis_def = factory.get(axis.axisTag, axis.name)
                    gsFontLocation.append(axis_def.default_user_loc)

            fontraGlyphAxesToGSLayerSmartComponentPoleMapping(
                variableGlyph.axes, gsLayer, glyphLocation
            )

            masterId = gsMasterAxesToIdMapping.get(tuple(gsFontLocation))

            isDefaultLayer = False
            # It is not enough to check if it has a masterId, because in case of a smart component,
            # the layer for each glyph axis has the same location as the master layer.
            if masterId:
                if layerNameDescriptor:
                    isDefaultLayer = False
                elif not isSmartCompGlyph:
                    isDefaultLayer = True
                elif defaultGlyphLocation == glyphLocation:
                    isDefaultLayer = True

            newLayerName = glyphSource.name
            if isDefaultLayer:
                newLayerName = gsMasterIdToNameMapping.get(masterId)
            elif layerNameDescriptor:
                newLayerName = layerNameDescriptor

            gsLayer.name = newLayerName

            if isDefaultLayer:
                gsLayer.layerId = masterId
            else:
                gsLayer.layerId = str(uuid.uuid4()).upper()
            layer.customData["com.glyphsapp.layer.layerId"] = gsLayer.layerId

            gsLayer.associatedMasterId = (
                associatedMasterId
                if associatedMasterId
                else getAssociatedMasterId(gsGlyph.parent, gsFontLocation)
            )

            if not isDefaultLayer and not isSmartCompGlyph and not layerNameDescriptor:
                # This is an intermediate layer
                gsLayer.name = "{" + ",".join(str(x) for x in gsFontLocation) + "}"
                gsLayer.attributes["coordinates"] = gsFontLocation

            if glyphSource.name:
                gsLayer.userData["xyz.fontra.source-name"] = glyphSource.name
            elif gsLayer.userData["xyz.fontra.source-name"]:
                del gsLayer.userData["xyz.fontra.source-name"]
            gsLayer.userData["xyz.fontra.layer-name"] = layerName

            raiseErrorIfIntermediateLayerInSmartComponent(
                variableGlyph, glyphLocation, masterId
            )

            fontraLayerToGSLayer(layer, gsLayer)
            gsGlyph.layers.append(gsLayer)

    if nonSourceLayerNames:
        raise NotImplementedError(
            "GlyphsApp Backend: Layer without glyph source is not yet implemented."
        )
    return gsGlyph


def raiseErrorIfIntermediateLayerInSmartComponent(
    variableGlyph, glyphLocation, masterId
):
    # We have a smart component. Check if it is an intermediate master/layer,
    # because we currently do not support writing this to GlyphsApp files.
    # This will be obsolute once we support this feature.
    if glyphLocation:
        isIntermediateLayer = False

        if not masterId:
            # If it has glyph axes (glyphLocation) and is not on any master location,
            # it must be an intermediate master.
            isIntermediateLayer = True
        else:
            # If it has glyph axes (glyphLocation) and is on a master location,
            # but any of the glyph axes are not at min or max position,
            # it must be an intermediate layer.
            if any(
                [
                    True
                    for axis in variableGlyph.axes
                    if glyphLocation[axis.name] not in [axis.minValue, axis.maxValue]
                ]
            ):
                isIntermediateLayer = True

        if isIntermediateLayer:
            raise NotImplementedError(
                "GlyphsApp Backend: Intermediate layers "
                "within smart glyphs are not yet implemented."
            )


def fontraGlyphAxesToGSSmartComponentAxes(variableGlyph, gsGlyph):
    smartComponentAxesByName = {axis.name: axis for axis in gsGlyph.smartComponentAxes}
    gsGlyph.smartComponentAxes = []
    for axis in variableGlyph.axes:
        if axis.defaultValue not in [axis.minValue, axis.maxValue]:
            # NOTE: GlyphsApp does not have axis.defaultValue,
            # therefore it must be at MIN or MAX.
            # https://docu.glyphsapp.com/#GSSmartComponentAxis
            raise TypeError(
                f"GlyphsApp Backend: Glyph axis '{axis.name}' "
                "defaultValue must be at MIN or MAX."
            )
        gsAxis = smartComponentAxesByName.get(axis.name)
        if gsAxis is None:
            gsAxis = glyphsLib.classes.GSSmartComponentAxis()
            gsAxis.name = axis.name
        gsAxis.bottomValue = axis.minValue
        gsAxis.topValue = axis.maxValue
        gsGlyph.smartComponentAxes.append(gsAxis)


def fontraGlyphAxesToGSLayerSmartComponentPoleMapping(glyphAxes, gsLayer, location):
    if len(glyphAxes) == 0:
        return
    # https://docu.glyphsapp.com/#GSLayer.smartComponentPoleMapping
    gsLayer.smartComponentPoleMapping = {}
    for axis in glyphAxes:
        pole = (
            int(Pole.MIN)  # convert to int for Python <= 3.10
            if axis.minValue == location[axis.name]
            else int(Pole.MAX)  # convert to int for Python <= 3.10
        )
        # Set pole, only MIN or MAX possible.
        # NOTE: In GlyphsApp these are checkboxes, either: on or off.
        gsLayer.smartComponentPoleMapping[axis.name] = pole


def fontraLayerToGSLayer(layer, gsLayer):
    gsLayer.paths = []

    # Draw new paths with pen
    pen = gsLayer.getPointPen()
    layer.glyph.path.drawPoints(pen)

    gsLayer.width = layer.glyph.xAdvance
    gsLayer.components = [
        fontraComponentToGSComponent(component) for component in layer.glyph.components
    ]
    gsLayer.anchors = [fontraAnchorToGSAnchor(anchor) for anchor in layer.glyph.anchors]
    gsLayer.guides = [
        fontraGuidelineToGSGuide(guideline) for guideline in layer.glyph.guidelines
    ]


EPSILON = 1e-9


def fontraComponentToGSComponent(component):
    if (
        abs(component.transformation.skewX) > EPSILON
        or abs(component.transformation.skewY) > EPSILON
    ):
        raise TypeError(
            "GlyphsApp Backend: Does not support skewing of components, yet."
        )
    gsComponent = glyphsLib.classes.GSComponent(component.name)
    transformation = component.transformation.toTransform()
    gsComponent.transform = GSTransform(*transformation)
    for axisName in component.location:
        gsComponent.smartComponentValues[axisName] = component.location[axisName]
    gsComponent.alignment = component.customData.get(
        "com.glyphsapp.component.alignment", 0
    )
    return gsComponent


def fontraAnchorToGSAnchor(anchor):
    gsAnchor = glyphsLib.classes.GSAnchor()
    gsAnchor.name = anchor.name
    gsAnchor.position.x = anchor.x
    gsAnchor.position.y = anchor.y
    if anchor.customData:
        gsAnchor.userData = anchor.customData
    # TODO: gsAnchor.orientation – If the position of the anchor
    # is relative to the LSB (0), center (2) or RSB (1).
    # Details: https://docu.glyphsapp.com/#GSAnchor.orientation
    return gsAnchor


def fontraGuidelineToGSGuide(guideline):
    gsGuide = glyphsLib.classes.GSGuide()
    gsGuide.name = guideline.name
    gsGuide.position.x = guideline.x
    gsGuide.position.y = guideline.y
    gsGuide.angle = guideline.angle
    gsGuide.locked = guideline.locked
    return gsGuide
