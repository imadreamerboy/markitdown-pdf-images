import io
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import pypdfium2
from docling_core.types.doc import DoclingDocument
from docling_core.types.doc.base import BoundingBox, CoordOrigin, Size
from docling_core.types.doc.document import ImageRef, ProvenanceItem
from docling_core.types.doc.labels import DocItemLabel
from docling_parse.pdf_parser import DoclingPdfParser, PdfDocument

from .export import PictureRecord, build_conversion_result, extension_from_data_uri
from .models import AssetKind, ImageMode, PathMode, PdfConversionResult
from .ocr import DEFAULT_OCR_TIMEOUT_SECONDS, PdfOcrEngine, resolve_ocr_engine
from .vector import extract_vector_figures


@dataclass(frozen=True)
class PreparedPdfSource:
    source_bytes: bytes
    source_name: str


@dataclass(frozen=True)
class PageContentElement:
    top: float
    left: float
    bbox: BoundingBox
    kind: str
    text: str | None = None
    extension: str | None = None
    image_ref: ImageRef | None = None
    asset_kind: AssetKind | None = None


def run_pdf_conversion_pipeline(
    source: str | Path | bytes | BinaryIO,
    *,
    preserve_images: bool,
    image_mode: ImageMode,
    artifacts_dir: Path | None,
    path_mode: PathMode,
    ocr_enabled: bool = False,
    tesseract_path: str | Path | None = None,
    ocr_languages: str = "",
    ocr_timeout_seconds: int = DEFAULT_OCR_TIMEOUT_SECONDS,
    ocr_engine: PdfOcrEngine | None = None,
) -> PdfConversionResult:
    prepared = prepare_pdf_source(source)
    pdf_document = DoclingPdfParser().load(io.BytesIO(prepared.source_bytes))
    title = extract_title(pdf_document)
    resolved_ocr_engine = resolve_ocr_engine(
        ocr_enabled=ocr_enabled,
        tesseract_path=tesseract_path,
        ocr_languages=ocr_languages,
        ocr_timeout_seconds=ocr_timeout_seconds,
        ocr_engine=ocr_engine,
    )
    document, pictures = build_docling_document(
        pdf_document,
        source_name=prepared.source_name,
        source_bytes=prepared.source_bytes,
        preserve_images=preserve_images,
        ocr_engine=resolved_ocr_engine,
    )
    return build_conversion_result(
        document,
        title=title,
        source_name=prepared.source_name,
        source_bytes=prepared.source_bytes,
        pictures=pictures,
        preserve_images=preserve_images,
        image_mode=image_mode,
        artifacts_dir=artifacts_dir,
        path_mode=path_mode,
    )


def prepare_pdf_source(source: str | Path | bytes | BinaryIO) -> PreparedPdfSource:
    if isinstance(source, bytes):
        return PreparedPdfSource(source_bytes=source, source_name="document.pdf")

    if isinstance(source, (str, Path)):
        path = Path(source)
        return PreparedPdfSource(
            source_bytes=path.read_bytes(),
            source_name=_normalize_source_name(path.name),
        )

    if hasattr(source, "read") and callable(source.read):
        source_bytes = _read_stream_bytes(source)
        return PreparedPdfSource(
            source_bytes=source_bytes,
            source_name=_normalize_source_name(getattr(source, "name", None)),
        )

    raise TypeError(f"Unsupported PDF source type: {type(source)!r}")


def extract_title(pdf_document: PdfDocument) -> str | None:
    metadata = pdf_document.get_meta()
    if metadata is None:
        return None

    data = getattr(metadata, "data", None)
    if isinstance(data, dict):
        for key in ("Title", "title"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def build_docling_document(
    pdf_document: PdfDocument,
    *,
    source_name: str,
    source_bytes: bytes,
    preserve_images: bool,
    ocr_engine: PdfOcrEngine | None,
) -> tuple[DoclingDocument, list[PictureRecord]]:
    document = DoclingDocument(name=Path(source_name).stem or source_name)
    pictures: list[PictureRecord] = []
    pdfium_document = pypdfium2.PdfDocument(source_bytes)
    include_visual_elements = preserve_images or ocr_engine is not None

    try:
        for page_number, page in pdf_document.iterate_pages():
            page_box = page.dimension.crop_bbox
            page_width = float(page_box.r - page_box.l)
            page_height = float(page_box.t - page_box.b)
            document.add_page(page_no=page_number, size=Size(width=page_width, height=page_height))

            pdfium_page = pdfium_document.get_page(page_number - 1)
            try:
                vector_figures = []
                if include_visual_elements:
                    vector_figures = extract_vector_figures(
                        page=page,
                        page_width=page_width,
                        page_height=page_height,
                        pdfium_page=pdfium_page,
                    )

                consumed_text_indices = {
                    index for figure in vector_figures for index in figure.consumed_text_indices
                }
                page_elements = _build_page_elements(
                    page,
                    page_height=page_height,
                    consumed_text_indices=consumed_text_indices,
                    vector_figures=vector_figures,
                    include_visual_elements=include_visual_elements,
                )

                native_text_found = False
                for element in page_elements:
                    if element.kind == "text" and element.text:
                        native_text_found = True
                        _add_paragraph(document, page_number=page_number, bbox=element.bbox, text=element.text)
                        continue

                    if element.kind != "image" or element.image_ref is None or element.extension is None:
                        continue

                    ocr_text = _ocr_image_element(element.image_ref, ocr_engine)
                    if preserve_images:
                        document.add_picture(
                            image=element.image_ref,
                            prov=_make_provenance(page_number, element.bbox, ""),
                        )
                        pictures.append(
                            PictureRecord(
                                page_number=page_number,
                                extension=element.extension,
                                kind=element.asset_kind or "bitmap",
                                ocr_text=ocr_text,
                            )
                        )
                        if ocr_text:
                            _add_paragraph(
                                document,
                                page_number=page_number,
                                bbox=element.bbox,
                                text=ocr_text,
                            )
                    elif ocr_text:
                        _add_paragraph(document, page_number=page_number, bbox=element.bbox, text=ocr_text)

                if ocr_engine is not None and not native_text_found:
                    page_ocr_text = _ocr_page(pdfium_page, ocr_engine)
                    if page_ocr_text:
                        _add_paragraph(
                            document,
                            page_number=page_number,
                            bbox=_page_bbox(page_width=page_width, page_height=page_height),
                            text=page_ocr_text,
                        )
            finally:
                pdfium_page.close()
    finally:
        pdfium_document.close()

    return document, pictures


def _build_page_elements(
    page: object,
    *,
    page_height: float,
    consumed_text_indices: set[int],
    vector_figures: list[object],
    include_visual_elements: bool,
) -> list[PageContentElement]:
    text_elements = _group_text_lines(
        page.textline_cells,
        page_height=page_height,
        consumed_text_indices=consumed_text_indices,
    )

    if not include_visual_elements:
        return text_elements

    image_elements = _build_image_elements(page.bitmap_resources, page_height=page_height)
    vector_elements = _build_vector_elements(vector_figures, page_height=page_height)
    elements = text_elements + image_elements + vector_elements
    return sorted(elements, key=lambda element: (element.top, element.left, 0 if element.kind == "text" else 1))


def _group_text_lines(
    lines: list[object],
    *,
    page_height: float,
    consumed_text_indices: set[int],
) -> list[PageContentElement]:
    sorted_lines: list[tuple[BoundingBox, str, float, float]] = []

    for line in lines:
        line_index = int(getattr(line, "index", -1))
        if line_index in consumed_text_indices:
            continue
        text = str(getattr(line, "text", "") or "").strip()
        if not text:
            continue
        bbox = line.rect.to_bounding_box()
        sorted_lines.append((bbox, text, _top_key(bbox, page_height), float(bbox.l)))

    sorted_lines.sort(key=lambda item: (item[2], item[3]))
    if not sorted_lines:
        return []

    groups: list[PageContentElement] = []
    current_bbox, current_text, current_top, current_left = sorted_lines[0]
    text_parts = [current_text]
    previous_bbox = current_bbox

    for bbox, text, top, left in sorted_lines[1:]:
        if _should_merge_paragraph(previous_bbox, bbox):
            text_parts.append(text)
            current_bbox = _merge_boxes(current_bbox, bbox)
            previous_bbox = _merge_boxes(previous_bbox, bbox)
            continue

        groups.append(
            PageContentElement(
                top=current_top,
                left=current_left,
                bbox=current_bbox,
                kind="text",
                text="\n".join(text_parts),
            )
        )
        current_bbox = bbox
        current_text = text
        current_top = top
        current_left = left
        text_parts = [current_text]
        previous_bbox = bbox

    groups.append(
        PageContentElement(
            top=current_top,
            left=current_left,
            bbox=current_bbox,
            kind="text",
            text="\n".join(text_parts),
        )
    )
    return groups


def _build_image_elements(images: list[object], *, page_height: float) -> list[PageContentElement]:
    elements: list[PageContentElement] = []
    for image in images:
        bbox = image.rect.to_bounding_box()
        image_ref = getattr(image, "image", None)
        if image_ref is None:
            continue
        extension = extension_from_data_uri(str(getattr(image_ref, "uri", "") or ""))
        elements.append(
            PageContentElement(
                top=_top_key(bbox, page_height),
                left=float(bbox.l),
                bbox=bbox,
                kind="image",
                extension=extension,
                image_ref=image_ref,
                asset_kind="bitmap",
            )
        )
    return elements


def _build_vector_elements(vector_figures: list[object], *, page_height: float) -> list[PageContentElement]:
    elements: list[PageContentElement] = []
    for figure in vector_figures:
        elements.append(
            PageContentElement(
                top=_top_key(figure.bbox, page_height),
                left=float(figure.bbox.l),
                bbox=figure.bbox,
                kind="image",
                extension=".png",
                image_ref=figure.image_ref,
                asset_kind="vector",
            )
        )
    return elements


def _ocr_image_element(image_ref: ImageRef, ocr_engine: PdfOcrEngine | None) -> str | None:
    if ocr_engine is None:
        return None

    image = image_ref.pil_image
    if image is None:
        return None

    return _normalize_ocr_text(ocr_engine.ocr_image(image))


def _ocr_page(pdfium_page: pypdfium2.PdfPage, ocr_engine: PdfOcrEngine) -> str | None:
    bitmap = pdfium_page.render(scale=3.0)
    try:
        image = bitmap.to_pil().convert("RGB")
    finally:
        close = getattr(bitmap, "close", None)
        if callable(close):
            close()

    return _normalize_ocr_text(ocr_engine.ocr_image(image))


def _normalize_ocr_text(text: str | None) -> str | None:
    normalized = str(text or "").strip()
    return normalized or None


def _add_paragraph(
    document: DoclingDocument,
    *,
    page_number: int,
    bbox: BoundingBox,
    text: str,
) -> None:
    document.add_text(
        label=DocItemLabel.PARAGRAPH,
        text=text,
        orig=text,
        prov=_make_provenance(page_number, bbox, text),
    )


def _page_bbox(*, page_width: float, page_height: float) -> BoundingBox:
    return BoundingBox(
        l=0.0,
        t=page_height,
        r=page_width,
        b=0.0,
        coord_origin=CoordOrigin.BOTTOMLEFT,
    )


def _make_provenance(page_number: int, bbox: BoundingBox, text: str) -> ProvenanceItem:
    return ProvenanceItem(
        page_no=page_number,
        bbox=bbox,
        charspan=(0, len(text)),
    )


def _should_merge_paragraph(previous_bbox: BoundingBox, current_bbox: BoundingBox) -> bool:
    previous_height = _box_height(previous_bbox)
    current_height = _box_height(current_bbox)
    vertical_gap = abs(float(previous_bbox.b) - float(current_bbox.t))
    left_delta = abs(float(previous_bbox.l) - float(current_bbox.l))
    threshold = max(previous_height, current_height) * 0.9
    return vertical_gap <= threshold and left_delta <= max(previous_height, current_height) * 2.0


def _merge_boxes(first: BoundingBox, second: BoundingBox) -> BoundingBox:
    return BoundingBox(
        l=min(float(first.l), float(second.l)),
        t=max(float(first.t), float(second.t)),
        r=max(float(first.r), float(second.r)),
        b=min(float(first.b), float(second.b)),
        coord_origin=first.coord_origin,
    )


def _box_height(box: BoundingBox) -> float:
    return abs(float(box.t) - float(box.b))


def _top_key(box: BoundingBox, page_height: float) -> float:
    if box.coord_origin == CoordOrigin.BOTTOMLEFT:
        return page_height - float(box.t)
    return float(box.t)


def _normalize_source_name(name: str | None) -> str:
    if name:
        candidate = Path(str(name)).name
        if candidate:
            if candidate.lower().endswith(".pdf"):
                return candidate
            return f"{candidate}.pdf"
    return "document.pdf"


def _read_stream_bytes(stream: BinaryIO) -> bytes:
    position: int | None = None
    if hasattr(stream, "tell") and hasattr(stream, "seek"):
        try:
            position = stream.tell()
        except (OSError, io.UnsupportedOperation):
            position = None

    data = stream.read()
    if position is not None:
        stream.seek(position)

    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("PDF streams must return bytes")

    return bytes(data)
