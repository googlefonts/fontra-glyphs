import re
from collections import OrderedDict


def getGlyphspackageGlyphFileName(glyphName):
    # Get the right glyph file name might be challenging, because for example
    # the glyph "A-cy" is stored in the package as A_-cy.glyph.
    # I could not find any documentation about this, yet. We may need to figure
    # this out over time and extend the unittest.
    nameParts = glyphName.split("-")
    firstPart = (
        f"{nameParts[0]}_"
        if len(nameParts[0]) == 1 and nameParts[0].isupper()
        else nameParts[0]
    )
    nameParts[0] = firstPart

    return "-".join(nameParts)


# The following is obsolete once this is merged:
# https://github.com/fonttools/openstep-plist/pull/35
def toOrderedDict(obj):
    if isinstance(obj, dict):
        return OrderedDict({k: toOrderedDict(v) for k, v in obj.items()})
    elif isinstance(obj, list):
        return [toOrderedDict(item) for item in obj]
    else:
        return obj


def getLocationFromLayerName(layerName, gsAxes):
    # Get the location based on name,
    # for example: Light / {166, 100} (layer #4)
    match = re.search(r"\{([^}]+)\}", layerName)
    if not match:
        return None
    listLocation = match.group(1).replace(" ", "").split(",")
    listLocationValues = [float(v) for v in listLocation]
    return {
        gsAxes[i].name.lower(): value
        for i, value in enumerate(listLocationValues)
        if i < len(gsAxes)
    }


def getLocationFromSources(sources, layerName):
    s = None
    for source in sources:
        if source.layerName == layerName:
            s = source
            break
    if s is not None:
        return {k.lower(): v for k, v in s.location.items()}


def getLocation(glyph, layerName, gsAxes):
    location = getLocationFromSources(glyph.sources, layerName)
    if location:
        return location
    # This layerName is not used by any source:
    return getLocationFromLayerName(layerName, gsAxes)


def getAssociatedMasterId(gsGlyph, gsLocation):
    # Best guess for associatedMasterId
    closestMaster = None
    closestDistance = float("inf")
    for gsLayer in gsGlyph.layers:
        gsMaster = gsLayer.master
        distance = sum(
            abs(gsMaster.axes[i] - gsLocation[i])
            for i in range(len(gsMaster.axes))
            if i < len(gsLocation)
        )
        if distance < closestDistance:
            closestDistance = distance
            closestMaster = gsMaster
    return closestMaster.id if closestMaster else None


def gsFormatting(content):
    # openstep_plist.dump changes the whole formatting, therefore
    # it's very diffucute to see what has changed.
    # This function is a very bad try to get close to how the formatting
    # looks like for a .glyphs file.
    # There must be a better solution, but this is better than nothing.

    patterns = [
        (
            r"customBinaryData = <\s*([0-9a-fA-F\s]+)\s*>;",
            lambda m: f"customBinaryData = <{m.group(1).replace(' ', '')}>;",
        ),
        (r"\(\s*(-?[\d.]+),\s*(-?[\d.]+)\s*\);", r"(\1,\2);"),
        (r"\(\s*(-?[\d.]+),\s*(-?[\d.]+),\s*([a-zA-Z]+)\s*\)", r"(\1,\2,\3)"),
        (r"origin = \(\s*(-?[\d.]+),\s*(-?[\d.]+)\s*\);", r"origin = (\1,\2);"),
        (r"target = \(\s*(-?[\d.]+),\s*(-?[\d.]+)\s*\);", r"target = (\1,\2);"),
        (
            r"color = \(\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\s*\);",
            r"color = (\1,\2,\3,\4);",
        ),
        (r"\(\s*(-?[\d.]+),\s*(-?[\d.]+),\s*([a-zA-Z]+)\s*\)", r"(\1,\2,\3)"),
        (r"\(\s*(-?[\d.]+),\s*(-?[\d.]+),\s*([a-zA-Z]+),\s*\{", r"(\1,\2,\3,{"),
        (r"\}\s*\),", r"}),"),
        (r"anchors = \(\);", r"anchors = (\n);"),
        (r"unicode = \(\);", r"unicode = (\n);"),
        (r"lib = \{\};", r"lib = {\n};"),
        (
            r"verticalStems = \(\s*(-?[\d.]+),(-?[\d.]+)\);",
            r"verticalStems = (\n\1,\n\2\n);",
        ),
    ]

    for pattern, replacement in patterns:
        content = re.sub(pattern, replacement, content)

    return content
