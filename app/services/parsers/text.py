"""Shared text normalization for command and tactical intent parsers."""

def normalize(text: str) -> str:
    return (
        text.strip()
        .lower()
        .replace("，", ",")
        .replace("。", "")
        .replace(" ", "")
    )
