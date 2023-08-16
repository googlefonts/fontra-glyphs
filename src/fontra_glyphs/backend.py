import pathlib

import glyphsLib
import openstep_plist
from fontra.core.classes import (
    Component,
    GlobalAxis,
    Layer,
    LocalAxis,
    Source,
    StaticGlyph,
    VariableGlyph,
)
from fontra.core.packedpath import PackedPathPointPen
from fontTools.designspaceLib import DesignSpaceDocument
from fontTools.misc.transform import DecomposedTransform
from glyphsLib.builder.axes import get_axis_definitions, to_designspace_axes
from glyphsLib.builder.smart_components import Pole


class GlyphsBackend:
    @classmethod
    def fromPath(cls, path):
        self = cls()
        self._setupFromPath(path)
        return self

    def _setupFromPath(self, path):
        gsFont = glyphsLib.classes.GSFont()

        rawFontData, rawGlyphsData = self._loadFiles(path)

        parser = glyphsLib.parser.Parser(current_type=gsFont.__class__)
        parser.parse_into_object(gsFont, rawFontData)

        self.gsFont = gsFont

        # Fill the glyphs list with dummy placeholder glyphs
        self.gsFont.glyphs = [
            glyphsLib.classes.GSGlyph() for i in range(len(rawGlyphsData))
        ]
        self.rawGlyphsData = rawGlyphsData

        self.glyphNameToIndex = {
            glyphData["glyphname"]: i for i, glyphData in enumerate(rawGlyphsData)
        }
        self.parsedGlyphNames = set()

        dsAxes = gsAxesToDesignSpaceAxes(self.gsFont)
        if len(dsAxes) == 1 and dsAxes[0].minimum == dsAxes[0].maximum:
            # This is a fake noop axis to make the designspace happy: we don't need it
            dsAxes = []

        self.axisNames = {axis.name for axis in dsAxes}

        self.locationByMasterID = {}
        for master in self.gsFont.masters:
            location = {}
            for axisDef in get_axis_definitions(self.gsFont):
                if axisDef.name in self.axisNames:
                    location[axisDef.name] = axisDef.get_design_loc(master)
            self.locationByMasterID[master.id] = location

        self.glyphMap = self._readGlyphMap(rawGlyphsData)

        axes = []
        for dsAxis in dsAxes:
            axis = GlobalAxis(
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

    @staticmethod
    def _loadFiles(path):
        with open(path, "r", encoding="utf-8") as fp:
            rawFontData = openstep_plist.load(fp, use_numbers=True)

        rawGlyphsData = rawFontData["glyphs"]
        rawFontData["glyphs"] = []
        return rawFontData, rawGlyphsData

    async def getGlyphMap(self):
        return self.glyphMap

    async def getGlobalAxes(self):
        return self.axes

    async def getUnitsPerEm(self):
        return self.gsFont.upm

    async def getFontLib(self):
        return {}

    async def getGlyph(self, glyphName):
        if glyphName not in self.glyphNameToIndex:
            return None

        self._ensureGlyphIsParsed(glyphName)

        gsGlyph = self.gsFont.glyphs[glyphName]

        localAxes = gsLocalAxesToFontraLocalAxes(gsGlyph)
        localAxesByName = {axis.name: axis for axis in localAxes}
        sources = []
        layers = {}
        seenLocations = []
        for i, gsLayer in enumerate(gsGlyph.layers):
            if not gsLayer.associatedMasterId:
                continue

            masterName = self.gsFont.masters[gsLayer.associatedMasterId].name
            sourceName = gsLayer.name or masterName
            layerName = f"{sourceName} {i}"

            location = {
                **self.locationByMasterID[gsLayer.associatedMasterId],
                **self._getBraceLayerLocation(gsLayer),
                **self._getSmartLocation(gsLayer, localAxesByName),
            }

            if location in seenLocations:
                inactive = True
            else:
                seenLocations.append(location)
                inactive = False

            sources.append(
                Source(
                    name=sourceName,
                    location=location,
                    layerName=layerName,
                    inactive=inactive,
                )
            )
            layers[layerName] = gsLayerToFontraLayer(gsLayer, self.axisNames)

        glyph = VariableGlyph(glyphName, axes=localAxes, sources=sources, layers=layers)
        return glyph

    def _readGlyphMap(self, rawGlyphsData):
        formatVersion = self.gsFont.format_version
        glyphMap = {}

        for glyphData in rawGlyphsData:
            glyphName = glyphData["glyphname"]
            codePoints = glyphData.get("unicode")
            if codePoints is None:
                codePoints = []
            elif formatVersion == 2:
                if isinstance(codePoints, str):
                    codePoints = [
                        int(codePoint, 16) for codePoint in codePoints.split(",")
                    ]
                else:
                    assert isinstance(codePoints, int)
                    # The plist parser turned it into an int, but it was a hex string
                    codePoints = [int(str(codePoints), 16)]
            elif isinstance(codePoints, int):
                codePoints = [codePoints]
            else:
                assert all(isinstance(codePoint, int) for codePoint in codePoints)
            glyphMap[glyphName] = codePoints

        return glyphMap

    def _ensureGlyphIsParsed(self, glyphName):
        if glyphName in self.parsedGlyphNames:
            return

        glyphIndex = self.glyphNameToIndex[glyphName]
        rawGlyphData = self.rawGlyphsData[glyphIndex]
        self.rawGlyphsData[glyphIndex] = None
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
        return {
            disambiguateLocalAxisName(name, self.axisNames): localAxesByName[
                name
            ].minValue
            if poleValue == Pole.MIN
            else localAxesByName[name].maxValue
            for name, poleValue in gsLayer.smartComponentPoleMapping.items()
        }

    def close(self):
        pass


class GlyphsPackageBackend(GlyphsBackend):
    @staticmethod
    def _loadFiles(path):
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


def gsLayerToFontraLayer(gsLayer, globalAxisNames):
    pen = PackedPathPointPen()
    gsLayer.drawPoints(pen)

    components = [
        gsComponentToFontraComponent(gsComponent, gsLayer, globalAxisNames)
        for gsComponent in gsLayer.components
    ]

    return Layer(
        glyph=StaticGlyph(
            xAdvance=gsLayer.width, path=pen.getPath(), components=components
        )
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
    return component


def disambiguateLocalAxisName(axisName, globalAxisNames):
    return f"{axisName} (local)" if axisName in globalAxisNames else axisName


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
        LocalAxis(
            name=axis.name,
            minValue=axis.bottomValue,
            defaultValue=axis.bottomValue
            if basePoleMapping[axis.name] == Pole.MIN
            else axis.topValue,
            maxValue=axis.topValue,
        )
        for axis in gsGlyph.smartComponentAxes
    ]
