#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from urllib.request import urlopen

SOURCE_URL = "https://www.unicode.org/Public/emoji/latest/emoji-test.txt"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "src/disports_discord/emoji_cldr_order.py"

UNICODE_GROUP_TO_PICKER_CATEGORY = {
    "Smileys & Emotion": "faces",
    "People & Body": "people",
    "Animals & Nature": "nature",
    "Food & Drink": "food",
    "Travel & Places": "travel",
    "Activities": "activities",
    "Objects": "objects",
    "Symbols": "symbols",
    "Flags": "flags",
}


def parse_emoji_test(text: str) -> tuple[str, str, list[tuple[str, str, str]]]:
    version = ""
    date = ""
    category = "symbols"
    rows: list[tuple[str, str, str]] = []

    for line in text.splitlines():
        if line.startswith("# Version:"):
            version = line.split(":", 1)[1].strip()
            continue
        if line.startswith("# Date:"):
            date = line.split(":", 1)[1].strip()
            continue
        if line.startswith("# group:"):
            unicode_group = line.split(":", 1)[1].strip()
            category = UNICODE_GROUP_TO_PICKER_CATEGORY.get(unicode_group, "symbols")
            continue
        if "; fully-qualified" not in line:
            continue

        before_comment, comment = line.split("#", 1)
        codepoints = before_comment.split(";", 1)[0].strip().split()
        emoji = "".join(chr(int(codepoint, 16)) for codepoint in codepoints)

        # Comment format is "<emoji> E<version> <CLDR short name>".
        comment_parts = comment.strip().split(" ", 2)
        label = comment_parts[2].strip() if len(comment_parts) >= 3 else comment.strip()
        rows.append((emoji, category, label))

    return version, date, rows


def render_module(version: str, date: str, rows: list[tuple[str, str, str]]) -> str:
    rendered_rows = "".join(f"    {row!r},\n" for row in rows)
    return (
        "# Generated from Unicode emoji-test.txt. Do not edit by hand.\n"
        f"# Run: python3 {Path(__file__).as_posix()}\n"
        f"# Source: {SOURCE_URL}\n"
        f"# Version: {version}; Date: {date}\n"
        "from __future__ import annotations\n\n"
        "EMOJI_CLDR_ORDER = (\n"
        f"{rendered_rows}"
        ")\n"
    )


def main() -> None:
    text = urlopen(SOURCE_URL, timeout=30).read().decode("utf-8")
    version, date, rows = parse_emoji_test(text)
    OUTPUT_PATH.write_text(render_module(version, date, rows), encoding="utf-8")
    print(f"Wrote {len(rows)} emoji rows from Unicode Emoji {version} to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
