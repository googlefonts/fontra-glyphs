import pathlib

import glyphsLib
import pytest
from fontra.backends import getFileSystemBackend

from fontra_glyphs.utils import (
    getAssociatedMasterId,
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


async def test_getLocationFromSources(testFont):
    glyph = await testFont.getGlyph("a")
    location = getLocationFromSources(
        glyph.sources, "1FA54028-AD2E-4209-AA7B-72DF2DF16264"
    )
    assert location == {"weight": 155}


def test_getAssociatedMasterId(testGSFont):
    # TODO: need more complex test with at least two axes,
    # then improvement getAssociatedMasterId
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
321,
700,
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
    [
        """pos = (
-113,
574
);""",
        "pos = (-113,574);",
    ],
    ["pos = (524,-122);", "pos = (524,-122);"],
    [
        "anchors = ();",
        """anchors = (
);""",
    ],
    [
        "unicode = ();",
        """unicode = (
);""",
    ],
    [
        "lib = {};",
        """lib = {
};""",
    ],
    [
        "verticalStems = (17,19);",
        """verticalStems = (
17,
19
);""",
    ],
    # TODO: The following does not fail in the unittest: diff \n vs \012
    [
        """code = "feature c2sc;
feature smcp;
";""",
        """code = "feature c2sc;\012feature smcp;\012";""",
    ],
]


@pytest.mark.parametrize("content,expected", contentSnippets)
def test_gsFormatting(content, expected):
    assert gsFormatting(content) == expected
