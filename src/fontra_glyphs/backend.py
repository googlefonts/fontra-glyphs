import glyphsLib
from fontra.core.classes import (
    Component,
    GlobalAxis,
    Layer,
    Source,
    StaticGlyph,
    VariableGlyph,
)
from fontra.core.packedpath import PackedPathPointPen
from fontTools.designspaceLib import DesignSpaceDocument
from fontTools.misc.transform import DecomposedTransform
from glyphsLib.builder.axes import get_axis_definitions, to_designspace_axes


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
        sources = []
        layers = {}
        for i, gsLayer in enumerate(gsGlyph.layers):
            if not gsLayer.associatedMasterId:
                continue

            masterName = self.gsFont.masters[gsLayer.associatedMasterId].name
            sourceName = gsLayer.name or masterName
            layerName = f"{sourceName} {i}"
            location = {
                **self.locationByMasterID[gsLayer.associatedMasterId],
                **self._getBraceLayerLocation(gsLayer),
            }

            sources.append(
                Source(name=sourceName, location=location, layerName=layerName)
            )
            layers[layerName] = gsLayerToFontraLayer(gsLayer)

        glyph = VariableGlyph(glyphName, sources=sources, layers=layers)
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


def gsLayerToFontraLayer(gsLayer):
    pen = PackedPathPointPen()
    gsLayer.drawPoints(pen)
    components = [
        Component(
            name=compo.name,
            transformation=DecomposedTransform.fromTransform(compo.transform),
        )
        for compo in gsLayer.components
    ]
    return Layer(
        glyph=StaticGlyph(
            xAdvance=gsLayer.width, path=pen.getPath(), components=components
        )
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
