# markitdown-pdf-images

Small MarkItDown PDF plugin focused on preserving PDF images and vector-style figures in markdown workflows without pulling in AGPL PDF dependencies.

## What this solves

Stock MarkItDown's built-in PDF converter can fall back to plain text extraction, but it does not preserve embedded PDF images as markdown image references. This package registers a higher-priority PDF converter and uses `docling-parse`, `docling-core`, and `pypdfium2` to return markdown with bitmap images preserved and vector-heavy figures rasterized into reusable assets.

## Scope

- Preserve PDF images and vector-like figures in markdown output
- Expose a small library API with structured asset metadata
- Work as a MarkItDown plugin through `markitdown.plugin`

This package does not implement OCR, table services, GUI code, scanned-PDF recovery, or full PDF layout reconstruction.

## Install

```bash
uv add markitdown-pdf-images
```

For local development:

```bash
uv sync --dev
```

## Dependency note

This rewrite removes the previous PyMuPDF / MuPDF backend. The runtime stack is now based on permissive open-source dependencies:

- `markitdown[pdf]`
- `docling-parse`
- `docling-core`
- `pypdfium2`

## MarkItDown plugin usage

```python
from markitdown import MarkItDown

md = MarkItDown(enable_plugins=True)

result = md.convert(
    "document.pdf",
    pdf_image_mode="external",
    pdf_artifacts_dir="out_assets",
    pdf_path_mode="relative",
)

print(result.markdown)
```

Behavior:

- The plugin registers a PDF converter at priority `-1.0`
- MarkItDown's built-in PDF converter remains available as fallback
- If the custom converter raises, MarkItDown continues to the built-in converter

## Library usage

```python
from markitdown_pdf_images import convert_pdf

result = convert_pdf(
    "document.pdf",
    image_mode="external",
    artifacts_dir="out_assets",
    path_mode="relative",
)

print(result.title)
print(result.markdown)

for asset in result.assets:
    print(asset.filename, asset.path, asset.markdown_path, asset.page_number)
```

Default behavior:

- If `artifacts_dir` is provided, images are written as external files and markdown links point at the document-scoped artifact folder
- If `artifacts_dir` is not provided, the converter falls back to embedded data URIs so markdown never points at temp files

## CLI

Minimal CLI for local testing:

```bash
uv run markitdown-pdf-images input.pdf --artifacts-dir out_assets
```

By default the CLI prints markdown to stdout.

## How this differs from stock MarkItDown

- Stock MarkItDown uses its built-in PDF converter
- `markitdown-pdf-images` runs earlier and preserves image references
- This package also exposes structured asset metadata through a small library API

## Migration note

This is a fresh rewrite of the earlier PyMuPDF prototype.

- `asset_dir` became `artifacts_dir`
- `asset_path_mode` became `path_mode`
- `asset_layout` was removed
- The package no longer depends on `pymupdf` or `pymupdf4llm`

## Limitations

- Focused on image preservation, not OCR
- Uses lightweight page-local ordering, not a full layout engine
- Vector figures are rasterized into PNG assets when they are not embedded as bitmap images
- Multi-column and table-heavy PDFs are out of scope for v1
- Embedded mode returns data URIs, which can make markdown large
