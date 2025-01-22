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
    GlyphSource,
    Layer,
    StaticGlyph,
    structure,
)

dataDir = pathlib.Path(__file__).resolve().parent / "data"

glyphs2Path = dataDir / "GlyphsUnitTestSans.glyphs"
glyphs3Path = dataDir / "GlyphsUnitTestSans3.glyphs"
glyphsPackagePath = dataDir / "GlyphsUnitTestSans3.glyphspackage"
referenceFontPath = dataDir / "GlyphsUnitTestSans3.fontra"


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

    referenceGlyph = await referenceFont.getGlyph(glyphName)
    # TODO: This unit test fails currently, because the fontra referenceFont
    # does not contain the customData "com.glyphsapp.seenLayerIDs".
    # Before I update the fontra file, I would like to discuss with Just,
    # if this is the right approach. test_putGlyph works now.
    assert referenceGlyph == glyph


@pytest.mark.asyncio
@pytest.mark.parametrize("glyphName", list(expectedGlyphMap))
async def test_putGlyph(writableTestFont, testFont, glyphName):
    glyphMap = await writableTestFont.getGlyphMap()
    glyph = await writableTestFont.getGlyph(glyphName)

    # for testing change every coordinate by 10 units
    for layerName, layer in iter(glyph.layers.items()):
        layer.glyph.xAdvance = 500  # for testing change xAdvance
        for i, coordinate in enumerate(layer.glyph.path.coordinates):
            layer.glyph.path.coordinates[i] = coordinate + 10

    await writableTestFont.putGlyph(glyphName, glyph, glyphMap[glyphName])

    savedGlyph = await writableTestFont.getGlyph(glyphName)
    referenceGlyph = await testFont.getGlyph(glyphName)

    for layerName, layer in iter(referenceGlyph.layers.items()):
        assert savedGlyph.layers[layerName].glyph.xAdvance == 500

        for i, coordinate in enumerate(layer.glyph.path.coordinates):
            assert (
                savedGlyph.layers[layerName].glyph.path.coordinates[i]
                == coordinate + 10
            )

        assert len(layer.glyph.path.coordinates) == len(
            savedGlyph.layers[layerName].glyph.path.coordinates
        )


async def test_deleteLayer(writableTestFont):
    glyphName = "A"
    glyphMap = await writableTestFont.getGlyphMap()
    glyph = await writableTestFont.getGlyph(glyphName)

    layerName = "3E7589AA-8194-470F-8E2F-13C1C581BE24"
    del glyph.layers[layerName]

    await writableTestFont.putGlyph(glyphName, glyph, glyphMap[glyphName])

    savedGlyph = await writableTestFont.getGlyph(glyphName)

    assert layerName in savedGlyph.layers


async def test_addLayer(writableTestFont):
    glyphName = "a"
    glyphMap = await writableTestFont.getGlyphMap()
    glyph = await writableTestFont.getGlyph(glyphName)
    numGlyphLayers = len(glyph.layers)

    layerName = str(uuid.uuid4()).upper()
    glyph.sources.append(
        GlyphSource(name="SemiBold", location={"weight": 166}, layerName=layerName)
    )
    # Copy StaticGlyph of Bold:
    glyph.layers[layerName] = Layer(
        glyph=deepcopy(glyph.layers["BFFFD157-90D3-4B85-B99D-9A2F366F03CA"].glyph)
    )

    await writableTestFont.putGlyph(glyphName, glyph, glyphMap[glyphName])

    savedGlyph = await writableTestFont.getGlyph(glyphName)
    assert len(savedGlyph.layers) > numGlyphLayers
    assert layerName in savedGlyph.layers.keys()


async def test_addLayerWithComponent(writableTestFont):
    glyphName = "n"  # n is made from components
    glyphMap = await writableTestFont.getGlyphMap()
    glyph = await writableTestFont.getGlyph(glyphName)
    numGlyphLayers = len(glyph.layers)

    layerName = str(uuid.uuid4()).upper()
    glyph.sources.append(
        GlyphSource(name="SemiBold", location={"weight": 166}, layerName=layerName)
    )
    # Copy StaticGlyph of Bold:
    glyph.layers[layerName] = Layer(
        glyph=deepcopy(glyph.layers["BFFFD157-90D3-4B85-B99D-9A2F366F03CA"].glyph)
    )

    await writableTestFont.putGlyph(glyphName, glyph, glyphMap[glyphName])

    savedGlyph = await writableTestFont.getGlyph(glyphName)
    assert len(savedGlyph.layers) > numGlyphLayers
    assert layerName in savedGlyph.layers.keys()


async def test_deleteMasterLayer(writableTestFont):
    # Removing a "master" layer breaks compatibility within a .glyphs file.
    # Therefore we need to make sure, that it will be added afterwords.
    glyphName = "a"
    glyphMap = await writableTestFont.getGlyphMap()
    glyph = await writableTestFont.getGlyph(glyphName)
    numGlyphLayers = len(glyph.layers)

    del glyph.layers["BFFFD157-90D3-4B85-B99D-9A2F366F03CA"]

    await writableTestFont.putGlyph(glyphName, glyph, glyphMap[glyphName])

    savedGlyph = await writableTestFont.getGlyph(glyphName)
    assert len(savedGlyph.layers) == numGlyphLayers


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


async def test_getKerning(testFont, referenceFont):
    assert await testFont.getKerning() == await referenceFont.getKerning()


async def test_getSources(testFont, referenceFont):
    assert await testFont.getSources() == await referenceFont.getSources()
