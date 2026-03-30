from pathlib import Path
from typing import BinaryIO

from .models import ImageMode, PathMode, PdfConversionResult
from .ocr import DEFAULT_OCR_TIMEOUT_SECONDS, PdfOcrEngine
from .pipeline import run_pdf_conversion_pipeline


def convert_pdf(
    source: str | Path | bytes | BinaryIO,
    *,
    preserve_images: bool = False,
    image_mode: ImageMode = "external",
    artifacts_dir: str | Path | None = None,
    path_mode: PathMode = "relative",
    ocr_enabled: bool = False,
    tesseract_path: str | Path | None = None,
    ocr_languages: str = "",
    ocr_timeout_seconds: int = DEFAULT_OCR_TIMEOUT_SECONDS,
    ocr_engine: PdfOcrEngine | None = None,
) -> PdfConversionResult:
    if preserve_images:
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
    else:
        normalized_artifacts_dir = None
        normalized_path_mode = "relative"
        effective_image_mode = "data-uri"

    return run_pdf_conversion_pipeline(
        source,
        preserve_images=preserve_images,
        image_mode=effective_image_mode,
        artifacts_dir=normalized_artifacts_dir,
        path_mode=normalized_path_mode,
        ocr_enabled=ocr_enabled,
        tesseract_path=tesseract_path,
        ocr_languages=ocr_languages,
        ocr_timeout_seconds=ocr_timeout_seconds,
        ocr_engine=ocr_engine,
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
