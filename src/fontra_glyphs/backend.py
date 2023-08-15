import glyphsLib
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
        return cls(glyphsLib.load(path))

    def __init__(self, gsFont):
        self.gsFont = gsFont

        dsAxes = gsAxesToDesignSpaceAxes(self.gsFont)
        if len(dsAxes) == 1 and dsAxes[0].minimum == dsAxes[0].maximum:
            # This is a fake noop axis to make the designspace happy: we don't need it
            dsAxes = []

        self.locationByMasterID = {}
        for master in self.gsFont.masters:
            location = {}
            for axisDef in get_axis_definitions(self.gsFont):
                location[axisDef.name] = axisDef.get_design_loc(master)
            self.locationByMasterID[master.id] = location

        glyphMap = {}
        for glyph in self.gsFont.glyphs:
            codePoints = glyph.unicode
            if not isinstance(codePoints, list):
                codePoints = [codePoints] if codePoints else []
            glyphMap[glyph.name] = [int(codePoint, 16) for codePoint in codePoints]
        self.glyphMap = glyphMap

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
        self.axisNames = {axis.name for axis in axes}

    async def getGlyphMap(self):
        return self.glyphMap

    async def getGlobalAxes(self):
        return self.axes

    async def getUnitsPerEm(self):
        return self.gsFont.upm

    async def getFontLib(self):
        return {}

    async def getGlyph(self, glyphName):
        if glyphName not in self.gsFont.glyphs:
            return None
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

            smartLocation = getSmartLocation(gsLayer, localAxesByName, self.axisNames)

            location = {
                **self.locationByMasterID[gsLayer.associatedMasterId],
                **self._getBraceLayerLocation(gsLayer),
                **smartLocation,
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

    def _getBraceLayerLocation(self, gsLayer):
        if not gsLayer._is_brace_layer():
            return {}

        return dict(
            (axis.name, value)
            for axis, value in zip(self.axes, gsLayer._brace_coordinates())
        )

    def close(self):
        pass


class GlyphsPackageBackend(GlyphsBackend):
    pass


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


def getSmartLocation(gsLayer, localAxesByName, globalAxisNames):
    return {
        disambiguateLocalAxisName(name, globalAxisNames): localAxesByName[name].minValue
        if poleValue == Pole.MIN
        else localAxesByName[name].maxValue
        for name, poleValue in gsLayer.smartComponentPoleMapping.items()
    }
