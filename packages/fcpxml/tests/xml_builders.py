"""Small FCPXML documents for the tests that look at one thing at a time."""

from __future__ import annotations

from pathlib import Path

RESOURCES = """
    <format id="r1" name="FFVideoFormat1080p25" frameDuration="1/25s"
            width="1920" height="1080"/>
    <asset id="a1" name="MIC A" start="0s" duration="7200s" hasAudio="1"
           audioSources="1" audioChannels="1" audioRate="48000"/>
    <asset id="a2" name="MIC B" start="0s" duration="7200s" hasAudio="1"
           audioSources="1" audioChannels="1" audioRate="48000"/>
    <asset id="v1" name="CAM" start="0s" duration="7200s" hasVideo="1"
           videoSources="1" format="r1"/>
    <effect id="fx1" name="Colour" uid=".../Generators/Colour"/>
"""


def project(
    spine: str,
    *,
    version: str = "1.10",
    tc_start: str = "0s",
    name: str | None = "P",
    resources: str = RESOURCES,
    sequence_format: str = "r1",
) -> str:
    """A project with the given spine content, as the text of an ``.fcpxml``."""
    name_attr = "" if name is None else f' name="{name}"'
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="{version}">
  <resources>{resources}</resources>
  <library>
    <event name="E">
      <project{name_attr}>
        <sequence format="{sequence_format}" duration="7200s" tcStart="{tc_start}">
          <spine>{spine}</spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>"""


def write(tmp_path: Path, xml: str, name: str = "t.fcpxml") -> str:
    path = tmp_path / name
    path.write_text(xml, encoding="utf-8")
    return str(path)
