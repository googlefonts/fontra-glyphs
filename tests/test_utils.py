import pathlib

import glyphsLib
import pytest
from fontra.backends import getFileSystemBackend

from fontra_glyphs.utils import (
    getAssociatedMasterId,
    getLocationFromLayerName,
    getLocationFromSources,
    gsFormatting,
)

dataDir = pathlib.Path(__file__).resolve().parent / "data"

glyphs2Path = dataDir / "GlyphsUnitTestSans.glyphs"
glyphs3Path = dataDir / "GlyphsUnitTestSans3.glyphs"
glyphsPackagePath = dataDir / "GlyphsUnitTestSans3.glyphspackage"


@pytest.fixture(scope="module", params=[glyphs2Path, glyphs3Path, glyphsPackagePath])
def testFont(request):
    return getFileSystemBackend(request.param)


@pytest.fixture(scope="module", params=[glyphs2Path, glyphs3Path, glyphsPackagePath])
def testGSFont(request):
    return glyphsLib.GSFont(request.param)


layerNamesToLocation = [
    ["Light / {166, 100} (layer #4)", {"weight": 166}],
    ["{ 166 } (layer #3)", {"weight": 166}],
    ["Light / (layer #4)", None],
]


@pytest.mark.parametrize("layerName,expected", layerNamesToLocation)
def test_getLocationFromLayerName(layerName, expected):
    gsFont = glyphsLib.classes.GSFont()
    gsFont.axes = [glyphsLib.classes.GSAxis(name="Weight", tag="wght")]
    location = getLocationFromLayerName(layerName, gsFont.axes)
    assert location == expected


async def test_getLocationFromSources(testFont):
    glyphName = "a"
    glyph = await testFont.getGlyph(glyphName)
    location = getLocationFromSources(glyph.sources, "Regular / {155, 100} (layer #3)")
    assert location == {"weight": 155}


def test_getAssociatedMasterId(testGSFont):
    gsGlyph = testGSFont.glyphs["a"]
    associatedMasterId = getAssociatedMasterId(gsGlyph, [155])
    associatedMaster = gsGlyph.layers[associatedMasterId]
    assert associatedMaster.name == "Regular"


contentSnippets = [
    [
        """pos = (
524,
141
);""",
        "pos = (524,141);",
    ],
    [
        """pos = (
-113,
765
);""",
        "pos = (-113,765);",
    ],
    [
        "customBinaryData = <74686520 62797465 73>;",
        "customBinaryData = <746865206279746573>;",
    ],
    [
        """color = (
120,
220,
20,
4
);""",
        "color = (120,220,20,4);",
    ],
    [
        """(
566.99,
700,
l
),""",
        "(566.99,700,l),",
    ],
    [
        """(
191,
700,
l
),""",
        "(191,700,l),",
    ],
    [
        """origin = (
1,
1
);""",
        "origin = (1,1);",
    ],
    [
        """target = (
1,
0
);""",
        "target = (1,0);",
    ],
    [
        """pos = (
45,
0
);""",
        "pos = (45,0);",
    ],
    [
        """pos = (
-45,
0
);""",
        "pos = (-45,0);",
    ],
    [
        """(
341,
720,
l,
{""",
        "(321,700,l,{",
    ],
    [
        """(
268,
153,
ls
),""",
        "(268,153,ls),",
    ],
    [
        """(
268,
153,
o
),""",
        "(268,153,o),",
    ],
    [
        """(
268,
153,
cs
),""",
        "(268,153,cs),",
    ],
    [
        """(
184,
-8,
c
),""",
        "(184,-8,c),",
    ],
    [
        """pos = (
334.937,
407.08
);""",
        "pos = (334.937,407.08);",
    ],
]


@pytest.mark.parametrize("content,expected", contentSnippets)
def test_gsFormatting(content, expected):
    assert gsFormatting(content) != expected
