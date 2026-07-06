# Re:PhiEdit Format Analysis

## Sources Read

- `/Users/jiayihuang/Downloads/phigrosfanmadecharteditor/!) HelpDocument.pdf`
- `/Users/jiayihuang/Downloads/phigrosfanmadecharteditor/Resources/16266666.pez`
- `/Users/jiayihuang/Downloads/phigrosfanmadecharteditor/Resources/16266666/16266666.json`
- `/Users/jiayihuang/Downloads/phigrosfanmadecharteditor/Chartlist.txt`
- Re:PhiEdit executable strings

## HelpDocument Finding

HelpDocument.pdf page 2 says Import imports `.pez` packaged charts, and Export writes packaged `.pez` files under `/Resources`.

Therefore `chart.json` is not the direct Import format. It is the chart data inside a `.pez` package or inside an unpacked Resources folder.

## Real PEZ Sample

`Resources/16266666.pez` is a ZIP archive using deflate compression.

Root members:

```text
16266666.mp3
16266666.png
16266666.json
info.txt
```

There is no outer folder in the archive.

`info.txt`:

```text
#
Name: Astaroth
Path: 16266666
Song: 16266666.mp3
Picture: 16266666.png
Chart: 16266666.json
Level: VeryHard - Lv.31
Composer: Team Grimoire
Charter: 紫叶
```

The chart JSON `META` references the same song and background file names.

## RPE JSON Schema Summary

Top-level keys:

- `BPMList`
- `META`
- `judgeLineGroup`
- `judgeLineList`

`META` includes:

- `RPEVersion`
- `background`
- `charter`
- `composer`
- `id`
- `level`
- `name`
- `offset`
- `song`

Judge line keys:

- `Group`
- `Name`
- `Texture`
- `alphaControl`
- `bpmfactor`
- `eventLayers`
- `extended`
- `father`
- `isCover`
- `notes`
- `numOfNotes`
- `posControl`
- `sizeControl`
- `skewControl`
- `yControl`
- `zOrder`

Note keys:

- `above`
- `alpha`
- `endTime`
- `isFake`
- `positionX`
- `size`
- `speed`
- `startTime`
- `type`
- `visibleTime`
- `yOffset`

Observed note types:

- `1`: Tap
- `2`: Hold
- `3`: Flick
- `4`: Drag

## V2 Export Rule

For Import compatibility, V2 exports `.pez` as ZIP/deflate with root files:

- `<safe_id>.<audio_ext>`
- `<safe_id>.png`
- `<safe_id>.json`
- `info.txt`

The normal folder export remains available only as a debugging and manual-inspection output.

