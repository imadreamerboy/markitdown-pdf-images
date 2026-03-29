import io
from pathlib import Path
from typing import Any, BinaryIO

from markitdown import (
    DocumentConverter,
    DocumentConverterResult,
    MarkItDown,
    StreamInfo,
)

from .converter import convert_pdf

__plugin_interface_version__ = 1

PDF_PLUGIN_PRIORITY = -1.0
ACCEPTED_MIME_TYPE_PREFIXES = [
    "application/pdf",
    "application/x-pdf",
]
ACCEPTED_FILE_EXTENSIONS = [".pdf"]


def register_converters(markitdown: MarkItDown, **kwargs: Any) -> None:
    markitdown.register_converter(PdfImagesConverter(), priority=PDF_PLUGIN_PRIORITY)


class PdfImagesConverter(DocumentConverter):
    def accepts(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,
    ) -> bool:
        mimetype = (stream_info.mimetype or "").lower()
        extension = (stream_info.extension or "").lower()

        if extension in ACCEPTED_FILE_EXTENSIONS:
            return True

        return any(mimetype.startswith(prefix) for prefix in ACCEPTED_MIME_TYPE_PREFIXES)

    def convert(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,
    ) -> DocumentConverterResult:
        source_name = _derive_source_name(file_stream, stream_info)
        buffer = _NamedBytesIO(file_stream.read(), name=source_name)
        result = convert_pdf(
            buffer,
            image_mode=kwargs.get("pdf_image_mode", "external"),
            artifacts_dir=kwargs.get("pdf_artifacts_dir"),
            path_mode=kwargs.get("pdf_path_mode", "relative"),
        )
        return DocumentConverterResult(markdown=result.markdown, title=result.title)


class _NamedBytesIO(io.BytesIO):
    def __init__(self, data: bytes, *, name: str):
        super().__init__(data)
        self.name = name


def _derive_source_name(file_stream: BinaryIO, stream_info: StreamInfo) -> str:
    if stream_info.filename:
        return Path(stream_info.filename).name
    if stream_info.local_path:
        return Path(stream_info.local_path).name

    stream_name = getattr(file_stream, "name", None)
    if stream_name:
        return Path(str(stream_name)).name

    return "document.pdf"
