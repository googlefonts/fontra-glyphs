import os
import pathlib
import shutil
import uuid
from copy import deepcopy

import openstep_plist
import pytest
from fontra.backends import getFileSystemBackend
from fontra.core.classes import (
    Anchor,
    Axes,
    FontInfo,
    GlyphAxis,
    GlyphSource,
    Guideline,
    Layer,
    StaticGlyph,
    VariableGlyph,
    structure,
)

dataDir = pathlib.Path(__file__).resolve().parent / "data"

glyphs2Path = dataDir / "GlyphsUnitTestSans.glyphs"
glyphs3Path = dataDir / "GlyphsUnitTestSans3.glyphs"
glyphsPackagePath = dataDir / "GlyphsUnitTestSans3.glyphspackage"
referenceFontPath = dataDir / "GlyphsUnitTestSans3.fontra"


def sourceNameMappingFromSources(fontSources):
    return {
        source.name: sourceIdentifier
        for sourceIdentifier, source in fontSources.items()
    }


@pytest.fixture(scope="module", params=[glyphs2Path, glyphs3Path, glyphsPackagePath])
def testFont(request):
    return getFileSystemBackend(request.param)


@pytest.fixture(scope="module")
def referenceFont(request):
    return getFileSystemBackend(referenceFontPath)


@pytest.fixture(params=[glyphs2Path, glyphs3Path, glyphsPackagePath])
def writableTestFont(tmpdir, request):
    srcPath = request.param
    dstPath = tmpdir / os.path.basename(srcPath)
    if os.path.isdir(srcPath):
        shutil.copytree(srcPath, dstPath)
    else:
        shutil.copy(srcPath, dstPath)
    return getFileSystemBackend(dstPath)


expectedAxes = structure(
    {
        "axes": [
            {
                "defaultValue": 400,
                "hidden": False,
                "label": "Weight",
                "mapping": [
                    [100, 17],
                    [200, 30],
                    [300, 55],
                    [357, 75],
                    [400, 90],
                    [500, 133],
                    [700, 179],
                    [900, 220],
                ],
                "maxValue": 900,
                "minValue": 100,
                "name": "Weight",
                "tag": "wght",
            },
        ]
    },
    Axes,
)


@pytest.mark.asyncio
async def test_getAxes(testFont):
    axes = await testFont.getAxes()
    assert expectedAxes == axes


expectedGlyphMap = {
    "A": [65],
    "Adieresis": [196],
    "_part.shoulder": [],
    "_part.stem": [],
    "a": [97],
    "a.sc": [],
    "adieresis": [228],
    "dieresis": [168],
    "h": [104],
    "m": [109],
    "n": [110],
    "V": [86],
    "A-cy": [1040],
}


@pytest.mark.asyncio
async def test_getGlyphMap(testFont):
    glyphMap = await testFont.getGlyphMap()
    assert expectedGlyphMap == glyphMap


expectedFontInfo = FontInfo(
    familyName="Glyphs Unit Test Sans",
    versionMajor=1,
    versionMinor=0,
    copyright=None,
    trademark=None,
    description=None,
    sampleText=None,
    designer=None,
    designerURL=None,
    manufacturer=None,
    manufacturerURL=None,
    licenseDescription=None,
    licenseInfoURL=None,
    vendorID=None,
    customData={},
)


@pytest.mark.asyncio
async def test_getFontInfo(testFont):
    fontInfo = await testFont.getFontInfo()
    assert expectedFontInfo == fontInfo


@pytest.mark.asyncio
@pytest.mark.parametrize("glyphName", list(expectedGlyphMap))
async def test_getGlyph(testFont, referenceFont, glyphName):
    glyph = await testFont.getGlyph(glyphName)
    if glyphName == "A" and "com.glyphsapp.glyph-color" not in glyph.customData:
        # glyphsLib doesn't read the color attr from Glyphs-2 files,
        # so let's monkeypatch the data
        glyph.customData["com.glyphsapp.glyph-color"] = [120, 220, 20, 4]

    if (
        glyphName in ["h", "m", "n"]
        and "com.glyphsapp.glyph-color" not in glyph.customData
    ):
        # glyphsLib doesn't read the component alignment from Glyphs-2 files,
        # so let's monkeypatch the data
        for layerName in glyph.layers:
            for component in glyph.layers[layerName].glyph.components:
                if "com.glyphsapp.component.alignment" not in component.customData:
                    component.customData["com.glyphsapp.component.alignment"] = -1

    referenceGlyph = await referenceFont.getGlyph(glyphName)
    assert referenceGlyph == glyph


@pytest.mark.asyncio
@pytest.mark.parametrize("glyphName", list(expectedGlyphMap))
async def test_putGlyph(writableTestFont, glyphName):
    glyphMap = await writableTestFont.getGlyphMap()
    glyph = await writableTestFont.getGlyph(glyphName)

    # for testing change every coordinate by 10 units
    for layerName, layer in iter(glyph.layers.items()):
        layer.glyph.xAdvance = 500  # for testing change xAdvance
        for i, coordinate in enumerate(layer.glyph.path.coordinates):
            layer.glyph.path.coordinates[i] = coordinate + 10

    await writableTestFont.putGlyph(glyphName, glyph, glyphMap[glyphName])

    savedGlyph = await writableTestFont.getGlyph(glyphName)
    assert glyph == savedGlyph

    reopened = getFileSystemBackend(writableTestFont.gsFilePath)
    reopenedGlyph = await reopened.getGlyph(glyphName)
    assert glyph == reopenedGlyph


@pytest.mark.asyncio
@pytest.mark.parametrize("gName", ["a", "A"])
async def test_duplicateGlyph(writableTestFont, gName):
    glyphName = f"{gName}.ss01"
    glyph = deepcopy(await writableTestFont.getGlyph(gName))
    glyph.name = glyphName
    await writableTestFont.putGlyph(glyphName, glyph, [])

    savedGlyph = await writableTestFont.getGlyph(glyphName)

    # glyphsLib doesn't read the color attr from Glyphs-2 files,
    # so let's monkeypatch the data
    glyph.customData["com.glyphsapp.glyph-color"] = [120, 220, 20, 4]
    savedGlyph.customData["com.glyphsapp.glyph-color"] = [120, 220, 20, 4]

    assert glyph == savedGlyph

    if os.path.isdir(writableTestFont.gsFilePath):
        # This is a glyphspackage:
        # check if the order.plist has been updated as well.
        packagePath = pathlib.Path(writableTestFont.gsFilePath)
        orderPath = packagePath / "order.plist"
        with open(orderPath, "r", encoding="utf-8") as fp:
            glyphOrder = openstep_plist.load(fp, use_numbers=True)
            assert glyphName == glyphOrder[-1]


async def test_updateGlyphCodePoints(writableTestFont):
    # Use case: all uppercase font via double encodeding
    # for example: A -> A, a [0x0041, 0x0061]
    glyphName = "A"
    glyph = await writableTestFont.getGlyph(glyphName)
    codePoints = [0x0041, 0x0061]
    await writableTestFont.putGlyph(glyphName, glyph, codePoints)

    reopened = getFileSystemBackend(writableTestFont.gsFilePath)
    reopenedGlyphMap = await reopened.getGlyphMap()
    assert reopenedGlyphMap["A"] == [0x0041, 0x0061]


async def test_createNewGlyph(writableTestFont):
    glyphName = "a.ss02"
    glyph = VariableGlyph(name=glyphName)

    layerName = str(uuid.uuid4()).upper()
    glyph.sources.append(GlyphSource(name="Default", location={}, layerName=layerName))
    glyph.layers[layerName] = Layer(glyph=StaticGlyph(xAdvance=333))

    await writableTestFont.putGlyph(glyphName, glyph, [])

    savedGlyph = await writableTestFont.getGlyph(glyphName)
    assert glyph == savedGlyph


async def test_createNewSmartGlyph(writableTestFont):
    fontSources = await writableTestFont.getSources()
    sourceNameMappingToIDs = sourceNameMappingFromSources(fontSources)
    glyphName = "a.smart"
    glyphAxis = GlyphAxis(name="Height", minValue=0, maxValue=100, defaultValue=0)
    glyph = VariableGlyph(name=glyphName, axes=[glyphAxis])

    # create a glyph with glyph axis
    for sourceName, location in {
        "Light": {"Weight": 17},
        "Light-Height": {"Weight": 17, "Height": 100},
        "Regular": {},
        "Regular-Height": {"Height": 100},
        "Bold": {"Weight": 220},
        "Bold-Height": {"Weight": 220, "Height": 100},
    }.items():
        layerName = sourceNameMappingToIDs.get(sourceName) or str(uuid.uuid4()).upper()
        glyph.sources.append(
            GlyphSource(name=sourceName, location=location, layerName=layerName)
        )
        glyph.layers[layerName] = Layer(glyph=StaticGlyph(xAdvance=100))

    await writableTestFont.putGlyph(glyphName, glyph, [])

    savedGlyph = await writableTestFont.getGlyph(glyphName)
    assert glyph == savedGlyph


async def test_extendSmartGlyphWithIntermedaiteLayer(writableTestFont):
    # This should fail, because not yet implemented.
    glyphName = "_part.shoulder"
    glyph = await writableTestFont.getGlyph(glyphName)

    layerName = str(uuid.uuid4()).upper()
    glyph.sources.append(
        GlyphSource(
            name="Intermediate Layer", location={"Weight": 99}, layerName=layerName
        )
    )
    glyph.layers[layerName] = Layer(glyph=StaticGlyph(xAdvance=100))

    with pytest.raises(
        NotImplementedError,
        match="Intermediate layers within smart glyphs are not yet implemented",
    ):
        await writableTestFont.putGlyph(glyphName, glyph, [])


async def test_smartGlyphAddGlyphAxisWithDefaultNotMinOrMax(writableTestFont):
    # This should fail, because not yet implemented.
    glyphName = "_part.shoulder"
    glyph = await writableTestFont.getGlyph(glyphName)
    glyphAxis = GlyphAxis(name="Height", minValue=0, maxValue=100, defaultValue=50)
    glyph.axes.append(glyphAxis)

    with pytest.raises(
        TypeError,
        match="Glyph axis 'Height' defaultValue must be at MIN or MAX.",
    ):
        await writableTestFont.putGlyph(glyphName, glyph, [])


async def test_smartGlyphUpdateGlyphAxisWithDefaultNotMinOrMax(writableTestFont):
    # This should fail, because not yet implemented.
    glyphName = "_part.shoulder"
    glyph = await writableTestFont.getGlyph(glyphName)
    glyphAxis = glyph.axes[0]
    glyphAxis.defaultValue = 50

    with pytest.raises(
        TypeError,
        match="defaultValue must be at MIN or MAX.",
    ):
        await writableTestFont.putGlyph(glyphName, glyph, [])


async def test_smartGlyphAddGlyphAxisWithDefaultAtMinOrMax(writableTestFont):
    glyphName = "_part.shoulder"
    glyph = await writableTestFont.getGlyph(glyphName)
    glyphAxis = GlyphAxis(name="Height", minValue=0, maxValue=100, defaultValue=100)
    glyph.axes.append(glyphAxis)

    await writableTestFont.putGlyph(glyphName, glyph, [])

    savedGlyph = await writableTestFont.getGlyph(glyphName)
    assert glyph == savedGlyph


async def test_smartGlyphRemoveGlyphAxis(writableTestFont):
    glyphName = "_part.shoulder"
    glyph = await writableTestFont.getGlyph(glyphName)
    del glyph.axes[0]

    # We expect we cannot roundtrip a glyph when removing a glyph axis,
    # because then some layers locations are not unique anymore.
    for i in [8, 5, 2]:
        del glyph.layers[glyph.sources[i].layerName]
        del glyph.sources[i]

    await writableTestFont.putGlyph(glyphName, glyph, [])

    savedGlyph = await writableTestFont.getGlyph(glyphName)
    assert glyph == savedGlyph


async def test_smartGlyphChangeGlyphAxisValue(writableTestFont):
    glyphName = "_part.shoulder"
    glyph = await writableTestFont.getGlyph(glyphName)

    glyph.axes[1].maxValue = 200
    # We expect we cannot roundtrip a glyph when changing a glyph axis min or
    # max value without changing the default, because in GlyphsApp there is
    # no defaultValue-concept. Therefore we need to change the defaultValue as well.
    glyph.axes[1].defaultValue = 200
    await writableTestFont.putGlyph(glyphName, glyph, [])

    savedGlyph = await writableTestFont.getGlyph(glyphName)
    assert glyph == savedGlyph


async def test_deleteLayer(writableTestFont):
    glyphName = "a"
    glyphMap = await writableTestFont.getGlyphMap()
    glyph = await writableTestFont.getGlyph(glyphName)
    numGlyphLayers = len(glyph.layers)

    # delete intermediate layer
    sourceIndex = 1
    del glyph.layers[glyph.sources[sourceIndex].layerName + "^background"]
    del glyph.layers[glyph.sources[sourceIndex].layerName]
    del glyph.sources[sourceIndex]

    await writableTestFont.putGlyph(glyphName, glyph, glyphMap[glyphName])

    savedGlyph = await writableTestFont.getGlyph(glyphName)
    assert len(savedGlyph.layers) < numGlyphLayers


async def test_addLayer(writableTestFont):
    glyphName = "a"
    glyphMap = await writableTestFont.getGlyphMap()
    glyph = await writableTestFont.getGlyph(glyphName)

    layerName = str(uuid.uuid4()).upper()
    glyph.sources.append(
        GlyphSource(name="SemiBold", location={"Weight": 166}, layerName=layerName)
    )
    # Copy StaticGlyph from Bold:
    glyph.layers[layerName] = Layer(
        glyph=deepcopy(glyph.layers["BFFFD157-90D3-4B85-B99D-9A2F366F03CA"].glyph)
    )

    await writableTestFont.putGlyph(glyphName, glyph, glyphMap[glyphName])

    savedGlyph = await writableTestFont.getGlyph(glyphName)
    assert glyph == savedGlyph


async def test_addBackgroundLayer(writableTestFont):
    fontSources = await writableTestFont.getSources()
    sourceNameMappingToIDs = sourceNameMappingFromSources(fontSources)
    glyphName = "a"
    glyphMap = await writableTestFont.getGlyphMap()
    glyph = await writableTestFont.getGlyph(glyphName)

    # add background layer:
    glyph.layers[sourceNameMappingToIDs.get("Regular") + "^background"] = Layer(
        glyph=deepcopy(glyph.layers[sourceNameMappingToIDs.get("Regular")].glyph)
    )

    await writableTestFont.putGlyph(glyphName, glyph, glyphMap[glyphName])

    savedGlyph = await writableTestFont.getGlyph(glyphName)
    assert glyph == savedGlyph


async def test_addBackgroundLayerToLayer(writableTestFont):
    # This is a nested behaviour.
    fontSources = await writableTestFont.getSources()
    sourceNameMappingToIDs = sourceNameMappingFromSources(fontSources)
    glyphName = "A"
    glyphMap = await writableTestFont.getGlyphMap()
    glyph = await writableTestFont.getGlyph(glyphName)

    # add layout layer:
    glyph.layers[sourceNameMappingToIDs.get("Regular") + "^Testing"] = Layer(
        glyph=deepcopy(glyph.layers[sourceNameMappingToIDs.get("Regular")].glyph)
    )

    # add background to layout layer:
    glyph.layers[sourceNameMappingToIDs.get("Regular") + "^Testing/background"] = Layer(
        glyph=deepcopy(glyph.layers[sourceNameMappingToIDs.get("Regular")].glyph)
    )

    await writableTestFont.putGlyph(glyphName, glyph, glyphMap[glyphName])

    savedGlyph = await writableTestFont.getGlyph(glyphName)
    assert glyph == savedGlyph


async def test_addLayoutLayer(writableTestFont):
    fontSources = await writableTestFont.getSources()
    sourceNameMappingToIDs = sourceNameMappingFromSources(fontSources)
    glyphName = "A"
    glyphMap = await writableTestFont.getGlyphMap()
    glyph = await writableTestFont.getGlyph(glyphName)

    # add layout layer:
    glyph.layers[sourceNameMappingToIDs.get("Regular") + "^Layout Layer"] = Layer(
        glyph=deepcopy(glyph.layers["BFFFD157-90D3-4B85-B99D-9A2F366F03CA"].glyph)
    )

    await writableTestFont.putGlyph(glyphName, glyph, glyphMap[glyphName])

    savedGlyph = await writableTestFont.getGlyph(glyphName)
    assert glyph == savedGlyph


async def test_readBackgroundLayer(writableTestFont):
    glyphName = "a"
    glyph = await writableTestFont.getGlyph(glyphName)

    # every master layer of /a should have a background layer.
    for glyphSource in glyph.sources:
        assert f"{glyphSource.layerName}^background" in glyph.layers


async def test_addLayerWithoutSource(writableTestFont):
    glyphName = "a"
    glyphMap = await writableTestFont.getGlyphMap()
    glyph = await writableTestFont.getGlyph(glyphName)

    layerName = str(uuid.uuid4()).upper()
    # Copy StaticGlyph from Bold:
    glyph.layers[layerName] = Layer(
        glyph=deepcopy(glyph.layers["BFFFD157-90D3-4B85-B99D-9A2F366F03CA"].glyph)
    )

    with pytest.raises(
        NotImplementedError, match="Layer without glyph source is not yet implemented"
    ):
        await writableTestFont.putGlyph(glyphName, glyph, glyphMap[glyphName])


async def test_addLayerWithComponent(writableTestFont):
    glyphName = "n"  # n is made from components
    glyphMap = await writableTestFont.getGlyphMap()
    glyph = await writableTestFont.getGlyph(glyphName)

    layerName = str(uuid.uuid4()).upper()
    glyph.sources.append(
        GlyphSource(name="SemiBold", location={"Weight": 166}, layerName=layerName)
    )
    # Copy StaticGlyph of Bold:
    glyph.layers[layerName] = Layer(
        glyph=deepcopy(glyph.layers["BFFFD157-90D3-4B85-B99D-9A2F366F03CA"].glyph)
    )

    # add background layer
    glyph.layers[layerName + "^background"] = Layer(
        glyph=deepcopy(glyph.layers["BFFFD157-90D3-4B85-B99D-9A2F366F03CA"].glyph)
    )

    await writableTestFont.putGlyph(glyphName, glyph, glyphMap[glyphName])

    savedGlyph = await writableTestFont.getGlyph(glyphName)
    assert glyph == savedGlyph


expectedSkewErrors = [
    # skewValue, expectedErrorMatch
    [20, "Does not support skewing of components"],
    [-0.001, "Does not support skewing of components"],
]


@pytest.mark.parametrize("skewValue,expectedErrorMatch", expectedSkewErrors)
async def test_skewComponent(writableTestFont, skewValue, expectedErrorMatch):
    fontSources = await writableTestFont.getSources()
    sourceNameMappingToIDs = sourceNameMappingFromSources(fontSources)
    glyphName = "Adieresis"  # Adieresis is made from components
    glyphMap = await writableTestFont.getGlyphMap()
    glyph = await writableTestFont.getGlyph(glyphName)

    glyph.layers[sourceNameMappingToIDs.get("Light")].glyph.components[
        0
    ].transformation.skewX = skewValue
    with pytest.raises(TypeError, match=expectedErrorMatch):
        await writableTestFont.putGlyph(glyphName, glyph, glyphMap[glyphName])


async def test_addAnchor(writableTestFont):
    glyphName = "a"
    glyphMap = await writableTestFont.getGlyphMap()
    glyph = await writableTestFont.getGlyph(glyphName)

    layerName = str(uuid.uuid4()).upper()
    glyph.sources.append(
        GlyphSource(name="SemiBold", location={"Weight": 166}, layerName=layerName)
    )
    glyph.layers[layerName] = Layer(glyph=StaticGlyph(xAdvance=0))
    glyph.layers[layerName].glyph.anchors.append(Anchor(name="top", x=207, y=746))

    await writableTestFont.putGlyph(glyphName, glyph, glyphMap[glyphName])

    savedGlyph = await writableTestFont.getGlyph(glyphName)

    assert (
        glyph.layers[layerName].glyph.anchors
        == savedGlyph.layers[layerName].glyph.anchors
    )


async def test_addGuideline(writableTestFont):
    glyphName = "a"
    glyphMap = await writableTestFont.getGlyphMap()
    glyph = await writableTestFont.getGlyph(glyphName)

    layerName = str(uuid.uuid4()).upper()
    glyph.sources.append(
        GlyphSource(name="SemiBold", location={"Weight": 166}, layerName=layerName)
    )
    glyph.layers[layerName] = Layer(glyph=StaticGlyph(xAdvance=0))
    glyph.layers[layerName].glyph.guidelines.append(Guideline(name="top", x=207, y=746))

    await writableTestFont.putGlyph(glyphName, glyph, glyphMap[glyphName])

    savedGlyph = await writableTestFont.getGlyph(glyphName)

    assert (
        glyph.layers[layerName].glyph.guidelines
        == savedGlyph.layers[layerName].glyph.guidelines
    )


async def test_getKerning(testFont, referenceFont):
    assert await testFont.getKerning() == await referenceFont.getKerning()


async def test_getSources(testFont, referenceFont):
    assert await testFont.getSources() == await referenceFont.getSources()


async def test_locationBaseWrite(writableTestFont):
    # TODO: This will have to be adjusted (simplified) once the backend emits
    # glyphs that use locationBase. Some of this test code is about accounting
    # for the before/after differences. We _write_ a glyph using locationBase,
    # we _read_ one without it. Round-tripping should be perfect after
    # https://github.com/googlefonts/fontra-glyphs/issues/89 has been implemented
    # fully.
    glyphName = "q"  # Any glyph that doesn't exist yet

    defaultLocation = {"Weight": 90}  # hard-coded because of axis.mapping laziness

    fontSources = await writableTestFont.getSources()

    glyph = VariableGlyph(name=glyphName)

    for sourceIdentifier in fontSources.keys():
        glyph.sources.append(
            GlyphSource(
                name="", locationBase=sourceIdentifier, layerName=sourceIdentifier
            )
        )
        glyph.layers[sourceIdentifier] = Layer(glyph=StaticGlyph(xAdvance=333))

    await writableTestFont.putGlyph(glyphName, glyph, [])

    savedGlyph = await writableTestFont.getGlyph(glyphName)

    for (sourceIdentifier, fontSource), glyphSource in zip(
        fontSources.items(), savedGlyph.sources, strict=True
    ):
        assert glyphSource.name == fontSource.name
        assert (
            defaultLocation | glyphSource.location == fontSource.location
        ), glyphSource

    assert glyph.layers == savedGlyph.layers
