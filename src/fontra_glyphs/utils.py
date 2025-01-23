import re


def getLocationFromSources(sources, layerName):
    s = sources[0]
    for source in sources:
        if source.layerName == layerName:
            s = source
            break
    return {k.lower(): v for k, v in s.location.items()}


def getAssociatedMasterId(gsFont, gsLocation):
    # Best guess for associatedMasterId
    closestMasterID = gsFont.masters[0].id  # default first master.
    closestDistance = float("inf")
    for gsMaster in gsFont.masters:
        distance = sum(
            abs(gsMaster.axes[i] - gsLocation[i])
            for i in range(len(gsMaster.axes))
            if i < len(gsLocation)
        )
        if distance < closestDistance:
            closestDistance = distance
            closestMasterID = gsMaster.id

    return closestMasterID


LEAF = object()


def patternsToMatchTree(patterns):
    tree = {}
    for pattern in patterns:
        subtree = tree
        for item in pattern[:-1]:
            if item not in subtree:
                subtree[item] = {}
            subtree = subtree[item]
        subtree[pattern[-1]] = LEAF
    return tree


def convertMatchesToTuples(obj, matchTree, path=()):
    if isinstance(obj, dict):
        assert matchTree is not LEAF, path
        return {
            k: convertMatchesToTuples(
                v, matchTree.get(k, matchTree.get(None, {})), path + (k,)
            )
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        convertToTuple = False
        if matchTree is LEAF:
            convertToTuple = True
            matchTree = {}
        seq = [
            convertMatchesToTuples(item, matchTree.get(None, {}), path + (i,))
            for i, item in enumerate(obj)
        ]
        if convertToTuple:
            seq = tuple(seq)
        return seq
    else:
        return obj


patterns = [
    ["fontMaster", None, "guides", None, "pos"],
    ["glyphs", None, "color"],
    ["glyphs", None, "layers", None, "anchors", None, "pos"],
    ["glyphs", None, "layers", None, "annotations", None, "pos"],
    ["glyphs", None, "layers", None, "background", "shapes", None, "nodes", None],
    ["glyphs", None, "layers", None, "guides", None, "pos"],
    ["glyphs", None, "layers", None, "hints", None, "origin"],
    ["glyphs", None, "layers", None, "hints", None, "target"],
    ["glyphs", None, "layers", None, "shapes", None, "nodes", None],
    ["glyphs", None, "layers", None, "shapes", None, "pos"],
]


matchTreeFont = patternsToMatchTree(patterns)
matchTreeGlyph = matchTreeFont["glyphs"][None]


def fixCustomBinaryDataFormatting(content):
    return re.sub(
        r"customBinaryData = <\s*([0-9a-fA-F\s]+)\s*>;",
        lambda m: f"customBinaryData = <{m.group(1).replace(' ', '')}>;",
        content,
    )
