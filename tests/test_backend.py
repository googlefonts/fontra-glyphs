import os
import pathlib
import shutil
import uuid
from copy import deepcopy

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


mappingMasterIDs = {
    "Light": "C4872ECA-A3A9-40AB-960A-1DB2202F16DE",
    "Regular": "3E7589AA-8194-470F-8E2F-13C1C581BE24",
    "Bold": "BFFFD157-90D3-4B85-B99D-9A2F366F03CA",
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


async def test_duplicateGlyph(writableTestFont):
    glyphName = "a.ss01"
    glyph = deepcopy(await writableTestFont.getGlyph("a"))
    glyph.name = glyphName
    await writableTestFont.putGlyph(glyphName, glyph, [])

    savedGlyph = await writableTestFont.getGlyph(glyphName)
    assert glyph == savedGlyph


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
        layerName = mappingMasterIDs.get(sourceName) or str(uuid.uuid4()).upper()
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

    await writableTestFont.putGlyph(glyphName, glyph, [])

    savedGlyph = await writableTestFont.getGlyph(glyphName)
    assert glyph == savedGlyph


async def test_deleteLayer(writableTestFont):
    glyphName = "a"
    glyphMap = await writableTestFont.getGlyphMap()
    glyph = await writableTestFont.getGlyph(glyphName)
    numGlyphLayers = len(glyph.layers)

    # delete intermediate layer
    del glyph.layers["1FA54028-AD2E-4209-AA7B-72DF2DF16264"]

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
    glyphName = "Adieresis"  # Adieresis is made from components
    glyphMap = await writableTestFont.getGlyphMap()
    glyph = await writableTestFont.getGlyph(glyphName)

    glyph.layers[mappingMasterIDs.get("Light")].glyph.components[
        0
    ].transformation.skewX = skewValue
    with pytest.raises(TypeError, match=expectedErrorMatch):
        await writableTestFont.putGlyph(glyphName, glyph, glyphMap[glyphName])


async def test_addAnchor(writableTestFont):
    glyphName = "a"
    glyphMap = await writableTestFont.getGlyphMap()
    glyph = await writableTestFont.getGlyph(glyphName)

    layerName = str(uuid.uuid4()).upper()
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
