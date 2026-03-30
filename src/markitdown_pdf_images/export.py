import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from docling_core.types.doc.base import ImageRefMode
from docling_core.types.doc.document import DoclingDocument

from .models import AssetKind, PathMode, PdfAsset, PdfConversionResult

IMAGE_LINK_PATTERN = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<path>[^)]+)\)")
SAFE_STEM_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
DATA_URI_PATTERN = re.compile(r"^data:(?P<mime>[-\w.+/]+);")


@dataclass(frozen=True)
class PictureRecord:
    page_number: int
    extension: str
    kind: AssetKind
    ocr_text: str | None = None


def build_doc_id(source_name: str, source_bytes: bytes) -> str:
    stem = Path(source_name).stem
    safe_stem = SAFE_STEM_PATTERN.sub("-", stem).strip("-.") or "document"
    digest = hashlib.sha256(source_bytes).hexdigest()[:8]
    return f"{safe_stem}-{digest}"


def build_conversion_result(
    document: DoclingDocument,
    *,
    title: str | None,
    source_name: str,
    source_bytes: bytes,
    pictures: list[PictureRecord],
    preserve_images: bool,
    image_mode: str,
    artifacts_dir: Path | None,
    path_mode: PathMode,
) -> PdfConversionResult:
    if not preserve_images:
        return PdfConversionResult(
            markdown=_normalize_markdown(document.export_to_markdown()),
            title=title,
            assets=[],
        )

    if image_mode == "external":
        if artifacts_dir is None:
            raise ValueError("artifacts_dir is required for external image mode")
        markdown, refs = _export_external_markdown(
            document,
            artifacts_dir=artifacts_dir,
            doc_id=build_doc_id(source_name, source_bytes),
            path_mode=path_mode,
        )
        assets = _build_assets_from_refs(refs, pictures, artifacts_dir=artifacts_dir)
        return PdfConversionResult(
            markdown=_normalize_markdown(markdown),
            title=title,
            assets=assets,
        )

    markdown = document.export_to_markdown(image_mode=ImageRefMode.EMBEDDED)
    refs = _extract_image_refs(markdown)
    assets = _build_embedded_assets(refs, pictures)
    return PdfConversionResult(
        markdown=_normalize_markdown(markdown),
        title=title,
        assets=assets,
    )


def _export_external_markdown(
    document: DoclingDocument,
    *,
    artifacts_dir: Path,
    doc_id: str,
    path_mode: PathMode,
) -> tuple[str, list[str]]:
    artifacts_root = artifacts_dir.resolve()
    document_artifacts_dir = artifacts_root / doc_id

    with TemporaryDirectory(prefix="markitdown-pdf-images-") as temp_root:
        if path_mode == "relative":
            markdown_path = artifacts_root.parent / f".{doc_id}.md"
            relative_artifacts_dir = Path(artifacts_root.name) / doc_id
            document.save_as_markdown(
                markdown_path,
                artifacts_dir=relative_artifacts_dir,
                image_mode=ImageRefMode.REFERENCED,
            )
        else:
            markdown_path = Path(temp_root) / f"{doc_id}.md"
            document.save_as_markdown(
                markdown_path,
                artifacts_dir=document_artifacts_dir,
                image_mode=ImageRefMode.REFERENCED,
            )

        try:
            markdown = markdown_path.read_text(encoding="utf-8")
        finally:
            markdown_path.unlink(missing_ok=True)

    markdown = _normalize_markdown_paths(markdown)
    refs = _extract_image_refs(markdown)
    return markdown, refs


def _build_assets_from_refs(
    refs: list[str],
    pictures: list[PictureRecord],
    *,
    artifacts_dir: Path,
) -> list[PdfAsset]:
    assets: list[PdfAsset] = []
    for ref, picture in zip(refs, pictures, strict=False):
        path = Path(ref)
        if not path.is_absolute():
            path = (artifacts_dir.parent / path).resolve()
        assets.append(
            PdfAsset(
                filename=path.name,
                path=path,
                markdown_path=ref,
                page_number=picture.page_number,
                kind=picture.kind,
                ocr_text=picture.ocr_text,
            )
        )
    return assets


def _build_embedded_assets(refs: list[str], pictures: list[PictureRecord]) -> list[PdfAsset]:
    assets: list[PdfAsset] = []
    per_page_counts: dict[int, int] = {}

    for ref, picture in zip(refs, pictures, strict=False):
        page_number = picture.page_number
        per_page_counts[page_number] = per_page_counts.get(page_number, 0) + 1
        assets.append(
            PdfAsset(
                filename=f"p{page_number:04d}-{per_page_counts[page_number]:02d}{picture.extension}",
                path=None,
                markdown_path=ref,
                page_number=page_number,
                kind=picture.kind,
                ocr_text=picture.ocr_text,
            )
        )
    return assets


def extension_from_data_uri(data_uri: str) -> str:
    match = DATA_URI_PATTERN.match(data_uri)
    if match is None:
        return ".png"

    mime_type = match.group("mime")
    if mime_type == "image/jpeg":
        return ".jpg"
    if mime_type == "image/svg+xml":
        return ".svg"
    if mime_type == "image/png":
        return ".png"
    if mime_type == "image/gif":
        return ".gif"
    return ".bin"


def _extract_image_refs(markdown: str) -> list[str]:
    return [match.group("path") for match in IMAGE_LINK_PATTERN.finditer(markdown)]


def _normalize_markdown_paths(markdown: str) -> str:
    def replace(match: re.Match[str]) -> str:
        alt = match.group("alt")
        ref = match.group("path").replace("\\", "/")
        return f"![{alt}]({ref})"

    return IMAGE_LINK_PATTERN.sub(replace, markdown)


def _normalize_markdown(markdown: str) -> str:
    lines = [line.rstrip() for line in re.split(r"\r?\n", markdown)]
    normalized = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", normalized)
