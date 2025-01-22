import re
from collections import OrderedDict


# The following is obsolete once this is merged:
# https://github.com/fonttools/openstep-plist/pull/35
def toOrderedDict(obj):
    if isinstance(obj, dict):
        return OrderedDict({k: toOrderedDict(v) for k, v in obj.items()})
    elif isinstance(obj, list):
        return [toOrderedDict(item) for item in obj]
    else:
        return obj


def getLocationFromSources(sources, layerName):
    s = sources[0]
    for source in sources:
        if source.layerName == layerName:
            s = source
            break
    return {k.lower(): v for k, v in s.location.items()}


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
    # TODO: This need a different solution.
    # Should be solved in the raw data not via regular expressions.
    # The raw data is made out of list. We need to convert some part into tuples.
    # For more please see: https://github.com/fonttools/openstep-plist/issues/33

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
