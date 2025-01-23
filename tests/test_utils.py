import pathlib

import pytest
from fontra.backends import getFileSystemBackend
from glyphsLib.classes import GSAxis, GSFont, GSFontMaster, GSGlyph, GSLayer

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


def createGSFontMaster(axes=[100, 100], id="DUMMY-MASTER-ID"):
    master = GSFontMaster()
    master.axes = axes
    master.id = id
    return master


def createGSGlyph(name="GlyphName", unicodes=[], layers=[]):
    glyph = GSGlyph()
    glyph.name = name
    glyph.unicodes = unicodes
    glyph.layers = layers
    return glyph


@pytest.fixture(scope="module")
def testGSFontWW():
    gsFont = GSFont()
    gsFont.format_version = 3
    gsFont.axes = [
        GSAxis(name="Optical Size", tag="opsz"),
        GSAxis(name="Weight", tag="wght"),
        GSAxis(name="Width", tag="wdth"),
    ]
    gsFont.masters = [
        createGSFontMaster(axes=[12, 50, 100], id="MasterID-TextCondLight"),
        createGSFontMaster(axes=[12, 50, 400], id="MasterID-TextCondRegular"),
        createGSFontMaster(axes=[12, 50, 900], id="MasterID-TextCondBold"),
        createGSFontMaster(axes=[12, 200, 100], id="MasterID-TextWideLight"),
        createGSFontMaster(axes=[12, 200, 400], id="MasterID-TextWideRegular"),
        createGSFontMaster(axes=[12, 200, 900], id="MasterID-TextWideBold"),
        createGSFontMaster(axes=[60, 50, 100], id="MasterID-PosterCondLight"),
        createGSFontMaster(axes=[60, 50, 400], id="MasterID-PosterCondRegular"),
        createGSFontMaster(axes=[60, 50, 900], id="MasterID-PosterCondBold"),
        createGSFontMaster(axes=[60, 200, 100], id="MasterID-PosterWideLight"),
        createGSFontMaster(axes=[60, 200, 400], id="MasterID-PosterWideRegular"),
        createGSFontMaster(axes=[60, 200, 900], id="MasterID-PosterWideBold"),
    ]
    gsFont.glyphs.append(
        createGSGlyph(
            name="A",
            unicodes=[
                0x0041,
            ],
            layers=[GSLayer()],
        )
    )
    return gsFont


async def test_getLocationFromSources(testFont):
    glyph = await testFont.getGlyph("a")
    location = getLocationFromSources(
        glyph.sources, "1FA54028-AD2E-4209-AA7B-72DF2DF16264"
    )
    assert location == {"weight": 155}


expectedAssociatedMasterId = [
    # gsLocation, associatedMasterId
    [[14, 155, 900], "MasterID-TextWideBold"],
    [[14, 155, 100], "MasterID-TextWideLight"],
    [[14, 55, 900], "MasterID-TextCondBold"],
    [[14, 55, 110], "MasterID-TextCondLight"],
    [[55, 155, 900], "MasterID-PosterWideBold"],
    [[55, 155, 100], "MasterID-PosterWideLight"],
    [[55, 55, 900], "MasterID-PosterCondBold"],
    [[55, 55, 110], "MasterID-PosterCondLight"],
    [[30, 100, 399], "MasterID-TextCondRegular"],
]


@pytest.mark.parametrize("gsLocation,expected", expectedAssociatedMasterId)
def test_getAssociatedMasterId(testGSFontWW, gsLocation, expected):
    assert getAssociatedMasterId(testGSFontWW, gsLocation) == expected


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
