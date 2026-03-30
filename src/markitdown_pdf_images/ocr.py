from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from PIL import Image as PILImage

DEFAULT_OCR_TIMEOUT_SECONDS = 60
MISSING_OCR_BACKEND_MESSAGE = (
    "OCR is enabled but no OCR backend is available. Install pytesseract or provide ocr_engine."
)


@runtime_checkable
class PdfOcrEngine(Protocol):
    def ocr_image(self, image: PILImage.Image) -> str: ...


class TesseractOcrEngine:
    def __init__(
        self,
        *,
        tesseract_path: str | Path | None = None,
        languages: str = "",
        timeout_seconds: int = DEFAULT_OCR_TIMEOUT_SECONDS,
        pytesseract_module: Any | None = None,
    ) -> None:
        self._tesseract_path = str(tesseract_path) if tesseract_path is not None else None
        self._languages = languages.strip()
        self._timeout_seconds = timeout_seconds
        self._pytesseract = pytesseract_module

    def ocr_image(self, image: PILImage.Image) -> str:
        pytesseract = self._pytesseract or _import_pytesseract()
        pytesseract_module = getattr(pytesseract, "pytesseract", pytesseract)
        previous_tesseract_path = getattr(pytesseract_module, "tesseract_cmd", None)

        if self._tesseract_path is not None:
            pytesseract_module.tesseract_cmd = self._tesseract_path

        try:
            return str(
                pytesseract.image_to_string(
                    image,
                    lang=self._languages or None,
                    timeout=self._timeout_seconds,
                )
            )
        finally:
            if self._tesseract_path is not None:
                pytesseract_module.tesseract_cmd = previous_tesseract_path


def resolve_ocr_engine(
    *,
    ocr_enabled: bool,
    tesseract_path: str | Path | None = None,
    ocr_languages: str = "",
    ocr_timeout_seconds: int = DEFAULT_OCR_TIMEOUT_SECONDS,
    ocr_engine: PdfOcrEngine | Any | None = None,
) -> PdfOcrEngine | None:
    if not ocr_enabled:
        return None

    if ocr_engine is not None:
        if not callable(getattr(ocr_engine, "ocr_image", None)):
            raise TypeError("ocr_engine must define a callable ocr_image(image) method")
        return ocr_engine

    pytesseract = _import_pytesseract()
    return TesseractOcrEngine(
        tesseract_path=tesseract_path,
        languages=ocr_languages,
        timeout_seconds=ocr_timeout_seconds,
        pytesseract_module=pytesseract,
    )


def _import_pytesseract() -> Any:
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError(MISSING_OCR_BACKEND_MESSAGE) from exc

    return pytesseract
