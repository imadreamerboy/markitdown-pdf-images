# markitdown-pdf-images

Reusable MarkItDown PDF plugin focused on two things:

- preserving PDF images and vector-style figures in markdown workflows
- adding optional OCR recovery without pulling in AGPL PDF dependencies

The package uses `docling-parse`, `docling-core`, and `pypdfium2` for PDF parsing, then layers image preservation and OCR on top.

## What this solves

Stock MarkItDown's built-in PDF converter is text-first. It does not preserve embedded PDF images as reusable markdown image references, and it does not expose structured asset metadata for host apps. This package registers a higher-priority PDF converter and exposes the same behavior through a direct library API.

## Supported behaviors

The library and plugin both support the same v1 behavior matrix:

- native parse only: `preserve_images=False`, `ocr_enabled=False`
- preserve images only: `preserve_images=True`, `ocr_enabled=False`
- OCR only: `preserve_images=False`, `ocr_enabled=True`
- OCR + preserve images: `preserve_images=True`, `ocr_enabled=True`

When OCR and image preservation are both enabled, OCR text is inserted immediately after each preserved image in the markdown flow.

## Install

```bash
uv add markitdown-pdf-images
```

For OCR with the built-in backend, install Tesseract on the host system as well. The Python package uses `pytesseract`, but it still needs the Tesseract executable.

For local development:

```bash
uv sync --dev
```

## Runtime stack

- `markitdown[pdf]`
- `docling-parse`
- `docling-core`
- `pypdfium2`
- `pillow`
- `pytesseract`

The package does not depend on `pymupdf` or `pymupdf4llm`.

## MarkItDown plugin usage

```python
from markitdown import MarkItDown

md = MarkItDown(enable_plugins=True)

result = md.convert(
    "document.pdf",
    pdf_preserve_images=True,
    pdf_image_mode="external",
    pdf_artifacts_dir="out_assets",
    pdf_path_mode="relative",
    pdf_ocr_enabled=True,
    pdf_ocr_languages="eng",
)

print(result.markdown)
print(result.pdf_assets)
```

Notes:

- The plugin registers at priority `-1.0`
- MarkItDown's built-in PDF converter remains available as fallback
- If the custom converter raises, MarkItDown can continue to the built-in converter
- The plugin attaches `pdf_conversion_result` and `pdf_assets` to the returned `DocumentConverterResult`

## Library usage

```python
from markitdown_pdf_images import convert_pdf

result = convert_pdf(
    "document.pdf",
    preserve_images=True,
    image_mode="external",
    artifacts_dir="out_assets",
    path_mode="relative",
    ocr_enabled=True,
    ocr_languages="eng",
)

print(result.title)
print(result.markdown)

for asset in result.assets:
    print(
        asset.filename,
        asset.path,
        asset.markdown_path,
        asset.page_number,
        asset.kind,
        asset.ocr_text,
    )
```

Behavior details:

- If `preserve_images=True` and `artifacts_dir` is provided, images are written as external files in a document-scoped artifact folder
- If `preserve_images=True` and `artifacts_dir` is not provided, the converter falls back to embedded data URIs so markdown never points at temp files
- If `preserve_images=False`, image export options are ignored and the result contains no assets
- If `ocr_enabled=True`, you can use either the built-in Tesseract backend or pass a custom `ocr_engine`

## CLI

Minimal CLI for local testing:

```bash
uv run markitdown-pdf-images input.pdf --preserve-images --artifacts-dir out_assets --ocr --ocr-languages eng
```

Supported flags:

- `--preserve-images`
- `--image-mode {external,data-uri}`
- `--artifacts-dir PATH`
- `--path-mode {relative,absolute}`
- `--ocr`
- `--tesseract-path PATH`
- `--ocr-languages LANGS`

The CLI prints markdown to stdout.

## OCR extension points

The built-in OCR backend uses Tesseract. For other workflows, pass a custom object that implements:

```python
def ocr_image(image) -> str:
    ...
```

That keeps the package generic while letting host applications plug in their own OCR stack.

## Limitations

- Uses lightweight page-local ordering, not a full layout engine
- Vector figures are rasterized into PNG assets when they are not embedded as bitmap images
- Page-level OCR fallback only runs on pages where no native paragraph text was extracted
- Multi-column and table-heavy PDFs are out of scope for v1
- Embedded mode returns data URIs, which can make markdown large
