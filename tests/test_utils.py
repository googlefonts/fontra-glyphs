import pathlib

import openstep_plist
import pytest
from fontra.backends import getFileSystemBackend
from glyphsLib.classes import GSAxis, GSFont, GSFontMaster, GSGlyph, GSLayer

from fontra_glyphs.utils import (
    convertMatchesToTuples,
    getAssociatedMasterId,
    getLocationFromSources,
    matchTreeFont,
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


@pytest.mark.parametrize("path", [glyphs2Path, glyphs3Path])
def test_roundtrip_glyphs_file_dumps(path):
    root = openstep_plist.loads(path.read_text(), use_numbers=True)
    result = convertMatchesToTuples(root, matchTreeFont)

    out = (
        openstep_plist.dumps(
            result,
            unicode_escape=False,
            indent=0,
            single_line_tuples=True,
            escape_newlines=False,
            sort_keys=False,
            single_line_empty_objects=False,
        )
        + "\n"
    )

    for root_line, out_line in zip(path.read_text().splitlines(), out.splitlines()):
        assert root_line == out_line
