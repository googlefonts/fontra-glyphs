import json
import pathlib
from dataclasses import asdict

import pytest
from fontra.backends import getFileSystemBackend
from fontTools.misc.filenames import userNameToFileName

dataDir = pathlib.Path(__file__).resolve().parent / "data"

glyphs2Path = dataDir / "GlyphsUnitTestSans.glyphs"
glyphs3Path = dataDir / "GlyphsUnitTestSans3.glyphs"
glyphsPackagePath = dataDir / "GlyphsUnitTestSans3.glyphspackage"

expectedGlyphDataDir = dataDir / "fontra-glyphs"


@pytest.fixture(scope="module", params=[glyphs2Path, glyphs3Path, glyphsPackagePath])
def testFont(request):
    return getFileSystemBackend(request.param)


expectedAxes = [
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


@pytest.mark.asyncio
async def test_axes(testFont):
    axes = await testFont.getGlobalAxes()
    assert expectedAxes == [asdict(axis) for axis in axes]


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
}


@pytest.mark.asyncio
async def test_glyphMap(testFont):
    glyphMap = await testFont.getGlyphMap()
    assert expectedGlyphMap == glyphMap


@pytest.mark.asyncio
@pytest.mark.parametrize("glyphName", list(expectedGlyphMap))
async def test_glyphRead(testFont, glyphName):
    glyph = await testFont.getGlyph(glyphName)
    if glyphName == "A" and "com.glyphsapp.glyph-color" not in glyph.customData:
        # glyphsLib doesn't read the color attr from Glyphs-2 files,
        # so let's monkeypatch the data
        glyph.customData = {"com.glyphsapp.glyph-color": [120, 220, 20, 4]}
    glyphPath = expectedGlyphDataDir / userNameToFileName(glyphName, suffix=".json")
    glyphDict = json.loads(json.dumps(asdict(glyph)))
    # glyphPath.write_text(json.dumps(glyphDict, indent=2))
    expectedGlyphDict = json.loads(glyphPath.read_text())
    assert expectedGlyphDict == glyphDict
