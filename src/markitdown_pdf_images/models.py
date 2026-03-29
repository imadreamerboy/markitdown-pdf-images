from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ImageMode = Literal["external", "data-uri"]
PathMode = Literal["relative", "absolute"]


@dataclass(frozen=True)
class PdfAsset:
    filename: str
    path: Path | None
    markdown_path: str
    page_number: int | None


@dataclass(frozen=True)
class PdfConversionResult:
    markdown: str
    title: str | None
    assets: list[PdfAsset]
