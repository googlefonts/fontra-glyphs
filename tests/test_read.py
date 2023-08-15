import contextlib
import json
import pathlib
import pytest
from dataclasses import asdict
from fontTools.misc.filenames import userNameToFileName
from fontra.backends import getFileSystemBackend


dataDir = pathlib.Path(__file__).resolve().parent / "data"

glyphs2Path = dataDir / "GlyphsUnitTestSans.glyphs"
glyphs3Path = dataDir / "GlyphsUnitTestSans3.glyphs"
glyphsPackagePath = dataDir / "GlyphsUnitTestSans3.glyphspackage"

expectedGlyphDataDir = dataDir / "fontra-glyphs"


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
@pytest.mark.parametrize("fontPath", [glyphs2Path, glyphs3Path, glyphsPackagePath])
async def test_read(fontPath):
    font = getFileSystemBackend(fontPath)
    with contextlib.closing(font):
        glyphMap = await font.getGlyphMap()
        assert expectedGlyphMap == glyphMap
        for glyphName in glyphMap:
            glyph = await font.getGlyph(glyphName)
            glyphPath = expectedGlyphDataDir / userNameToFileName(
                glyphName, suffix=".json"
            )
            expectedGlyphDict = json.loads(glyphPath.read_text())
            glyphDict = json.loads(json.dumps(asdict(glyph)))
            assert expectedGlyphDict == glyphDict
            # glyphPath.write_text(json.dumps(glyphDict, indent=2))
