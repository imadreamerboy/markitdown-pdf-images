from pathlib import Path
from typing import BinaryIO

from .models import ImageMode, PathMode, PdfConversionResult
from .pipeline import run_pdf_conversion_pipeline


def convert_pdf(
    source: str | Path | bytes | BinaryIO,
    *,
    image_mode: ImageMode = "external",
    artifacts_dir: str | Path | None = None,
    path_mode: PathMode = "relative",
) -> PdfConversionResult:
    normalized_image_mode = _validate_choice(
        image_mode,
        valid_values={"external", "data-uri"},
        field_name="image_mode",
    )
    normalized_path_mode = _validate_choice(
        path_mode,
        valid_values={"relative", "absolute"},
        field_name="path_mode",
    )
    normalized_artifacts_dir = _normalize_artifacts_dir(artifacts_dir)

    effective_image_mode: ImageMode = normalized_image_mode
    if normalized_image_mode == "external" and normalized_artifacts_dir is None:
        effective_image_mode = "data-uri"

    return run_pdf_conversion_pipeline(
        source,
        image_mode=effective_image_mode,
        artifacts_dir=normalized_artifacts_dir,
        path_mode=normalized_path_mode,
    )


def _normalize_artifacts_dir(artifacts_dir: str | Path | None) -> Path | None:
    if artifacts_dir is None:
        return None

    normalized = Path(artifacts_dir).expanduser().resolve()
    if normalized.exists() and not normalized.is_dir():
        raise ValueError(f"artifacts_dir must be a directory path: {normalized}")
    return normalized


def _validate_choice(
    value: str,
    *,
    valid_values: set[str],
    field_name: str,
) -> str:
    if value not in valid_values:
        valid = ", ".join(sorted(valid_values))
        raise ValueError(f"{field_name} must be one of: {valid}")
    return value
