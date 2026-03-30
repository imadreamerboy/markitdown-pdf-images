import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from markitdown_pdf_images import PdfAsset, PdfConversionResult, convert_pdf
from markitdown_pdf_images.ocr import MISSING_OCR_BACKEND_MESSAGE


class FakeOcrEngine:
    def __init__(self, text: str = "OCR_TEXT") -> None:
        self.text = text
        self.calls: list[tuple[int, int]] = []

    def ocr_image(self, image) -> str:
        self.calls.append(image.size)
        return self.text


def test_convert_text_only_pdf(make_pdf, tmp_path):
    pdf_path = make_pdf(
        tmp_path / "text-only.pdf",
        title="Text Only",
        pages=[{"text": "Hello from a text-only PDF."}],
    )

    result = convert_pdf(pdf_path)

    assert isinstance(result, PdfConversionResult)
    assert result.title is None
    assert result.assets == []
    assert "Hello from a text-only PDF." in result.markdown
    assert "![" not in result.markdown


def test_convert_pdf_preserve_disabled_ignores_image_options(make_pdf, make_image, tmp_path):
    image_path = make_image(tmp_path / "image.png", color=(255, 0, 0))
    pdf_path = make_pdf(
        tmp_path / "no-preserve.pdf",
        pages=[
            {
                "text": "PDF with one image.",
                "images": [{"path": image_path, "rect": (72, 640, 180, 720)}],
            }
        ],
    )

    result = convert_pdf(
        pdf_path,
        preserve_images=False,
        image_mode="external",
        artifacts_dir=tmp_path / "assets",
        path_mode="absolute",
    )

    assert result.assets == []
    assert "PDF with one image." in result.markdown
    assert "![" not in result.markdown


def test_convert_pdf_writes_external_assets(make_pdf, make_image, tmp_path):
    image_path = make_image(tmp_path / "image.png", color=(255, 0, 0))
    pdf_path = make_pdf(
        tmp_path / "with-image.pdf",
        pages=[
            {
                "text": "PDF with one image.",
                "images": [{"path": image_path, "rect": (72, 640, 180, 720)}],
            }
        ],
    )

    artifacts_dir = tmp_path / "assets"
    result = convert_pdf(pdf_path, preserve_images=True, artifacts_dir=artifacts_dir)

    assert len(result.assets) == 1
    asset = result.assets[0]
    assert asset.path is not None
    assert asset.path.exists()
    assert asset.filename == asset.path.name
    assert asset.page_number == 1
    assert asset.kind == "bitmap"
    assert asset.ocr_text is None
    assert asset.markdown_path.startswith("assets/")
    assert asset.markdown_path in result.markdown
    assert str(asset.path).replace("\\", "/") not in result.markdown
    assert "AppData/Local/Temp" not in result.markdown


def test_convert_pdf_without_artifacts_dir_embeds_data_uri(make_pdf, make_image, tmp_path):
    image_path = make_image(tmp_path / "embedded.png", color=(0, 255, 0))
    pdf_path = make_pdf(
        tmp_path / "embedded.pdf",
        pages=[
            {
                "text": "PDF with embedded image output.",
                "images": [{"path": image_path, "rect": (72, 640, 180, 720)}],
            }
        ],
    )

    result = convert_pdf(pdf_path, preserve_images=True)

    assert len(result.assets) == 1
    asset = result.assets[0]
    assert asset.path is None
    assert asset.filename == "p0001-01.png"
    assert asset.kind == "bitmap"
    assert asset.ocr_text is None
    assert asset.markdown_path.startswith("data:image/png;base64,")
    assert asset.markdown_path in result.markdown


def test_convert_pdf_multi_page_multiple_images(make_pdf, make_image, tmp_path):
    first_image = make_image(tmp_path / "first.png", color=(255, 0, 0))
    second_image = make_image(tmp_path / "second.png", color=(0, 255, 0))
    third_image = make_image(tmp_path / "third.png", color=(0, 0, 255))
    pdf_path = make_pdf(
        tmp_path / "multi-page.pdf",
        pages=[
            {
                "text": "First page.",
                "images": [
                    {"path": first_image, "rect": (72, 640, 160, 720)},
                    {"path": second_image, "rect": (180, 640, 280, 730)},
                ],
            },
            {
                "text": "Second page.",
                "images": [{"path": third_image, "rect": (72, 640, 200, 730)}],
            },
        ],
    )

    result = convert_pdf(pdf_path, preserve_images=True, artifacts_dir=tmp_path / "assets")

    assert len(result.assets) == 3
    assert [asset.page_number for asset in result.assets] == [1, 1, 2]
    assert [asset.kind for asset in result.assets] == ["bitmap", "bitmap", "bitmap"]
    assert result.markdown.count("![") == 3
    assert all(asset.path is not None and asset.path.exists() for asset in result.assets)


def test_convert_pdf_extracts_vector_figure(make_pdf, tmp_path):
    pdf_path = make_pdf(
        tmp_path / "vector-chart.pdf",
        pages=[
            {
                "text": "",
                "vectors": [
                    {"kind": "line", "start": (72, 640), "end": (72, 740)},
                    {"kind": "line", "start": (72, 640), "end": (272, 640)},
                    {"kind": "rect", "rect": (90, 640, 115, 680), "fill": 1},
                    {"kind": "rect", "rect": (130, 640, 155, 710), "fill": 1},
                ],
                "labels": [
                    {"text": "A", "pos": (88, 625)},
                    {"text": "B", "pos": (128, 625)},
                ],
            }
        ],
    )

    result = convert_pdf(pdf_path, preserve_images=True, artifacts_dir=tmp_path / "assets")

    assert len(result.assets) == 1
    assert result.assets[0].path is not None
    assert result.assets[0].path.exists()
    assert result.assets[0].filename.endswith(".png")
    assert result.assets[0].page_number == 1
    assert result.assets[0].kind == "vector"
    assert "![Image](" in result.markdown


def test_convert_pdf_attaches_caption_and_keeps_unrelated_text(make_pdf, tmp_path):
    pdf_path = make_pdf(
        tmp_path / "vector-caption.pdf",
        pages=[
            {
                "vectors": [
                    {"kind": "line", "start": (72, 640), "end": (72, 740)},
                    {"kind": "line", "start": (72, 640), "end": (272, 640)},
                    {"kind": "rect", "rect": (90, 640, 115, 680), "fill": 1},
                    {"kind": "rect", "rect": (130, 640, 155, 710), "fill": 1},
                ],
                "labels": [
                    {"text": "Win Rate", "pos": (130, 760)},
                    {"text": "Figure 1: Test figure caption.", "pos": (72, 600)},
                    {"text": "This descriptive sentence should stay in markdown.", "pos": (72, 586)},
                    {"text": "This paragraph should stay in markdown.", "pos": (72, 560)},
                ],
            }
        ],
    )

    result = convert_pdf(pdf_path, preserve_images=True, artifacts_dir=tmp_path / "assets")

    assert len(result.assets) == 1
    assert "Win Rate" not in result.markdown
    assert "Figure 1: Test figure caption." not in result.markdown
    assert "This descriptive sentence should stay in markdown." in result.markdown
    assert "This paragraph should stay in markdown." in result.markdown


def test_convert_pdf_uses_document_scoped_artifacts(make_pdf, make_image, tmp_path):
    shared_artifacts_dir = tmp_path / "shared-assets"
    first_image = make_image(tmp_path / "first" / "image.png", color=(255, 0, 0))
    second_image = make_image(tmp_path / "second" / "image.png", color=(0, 0, 255))

    first_pdf = make_pdf(
        tmp_path / "first" / "report.pdf",
        pages=[
            {
                "text": "First report.",
                "images": [{"path": first_image, "rect": (72, 640, 180, 720)}],
            }
        ],
    )
    second_pdf = make_pdf(
        tmp_path / "second" / "report.pdf",
        pages=[
            {
                "text": "Second report.",
                "images": [{"path": second_image, "rect": (72, 640, 180, 720)}],
            }
        ],
    )

    first_result = convert_pdf(first_pdf, preserve_images=True, artifacts_dir=shared_artifacts_dir)
    second_result = convert_pdf(second_pdf, preserve_images=True, artifacts_dir=shared_artifacts_dir)

    assert first_result.assets[0].path is not None
    assert second_result.assets[0].path is not None
    assert first_result.assets[0].path.parent != second_result.assets[0].path.parent
    assert first_result.assets[0].markdown_path != second_result.assets[0].markdown_path


def test_convert_pdf_ocr_only_recovers_text_without_assets(make_pdf, make_image, tmp_path):
    image_path = make_image(tmp_path / "scan.png", color=(120, 120, 120))
    pdf_path = make_pdf(
        tmp_path / "ocr-only.pdf",
        pages=[{"images": [{"path": image_path, "rect": (72, 640, 180, 720)}]}],
    )
    ocr_engine = FakeOcrEngine("Recovered OCR text")

    result = convert_pdf(pdf_path, ocr_enabled=True, ocr_engine=ocr_engine)

    assert result.assets == []
    assert "![" not in result.markdown
    assert "Recovered OCR text" in result.markdown
    assert ocr_engine.calls


def test_convert_pdf_preserve_and_ocr_keeps_assets_and_inserts_ocr_text(make_pdf, make_image, tmp_path):
    image_path = make_image(tmp_path / "scan.png", color=(90, 90, 90))
    pdf_path = make_pdf(
        tmp_path / "ocr-preserve.pdf",
        pages=[{"images": [{"path": image_path, "rect": (72, 640, 180, 720)}]}],
    )

    result = convert_pdf(
        pdf_path,
        preserve_images=True,
        artifacts_dir=tmp_path / "assets",
        ocr_enabled=True,
        ocr_engine=FakeOcrEngine("Image OCR text"),
    )

    assert len(result.assets) == 1
    assert result.assets[0].ocr_text == "Image OCR text"
    assert result.assets[0].path is not None and result.assets[0].path.exists()
    image_index = result.markdown.index("![")
    ocr_index = result.markdown.index("Image OCR text")
    assert image_index < ocr_index


def test_convert_pdf_mixed_native_and_ocr_pages(make_pdf, make_image, tmp_path):
    image_path = make_image(tmp_path / "scan.png", color=(200, 200, 200))
    pdf_path = make_pdf(
        tmp_path / "mixed.pdf",
        pages=[
            {"text": "Native page text."},
            {"images": [{"path": image_path, "rect": (72, 640, 180, 720)}]},
        ],
    )

    result = convert_pdf(
        pdf_path,
        ocr_enabled=True,
        ocr_engine=FakeOcrEngine("Fallback OCR text"),
    )

    assert "Native page text." in result.markdown
    assert "Fallback OCR text" in result.markdown
    assert result.assets == []


def test_custom_ocr_engine_overrides_builtin(make_pdf, make_image, monkeypatch, tmp_path):
    image_path = make_image(tmp_path / "scan.png", color=(50, 50, 50))
    pdf_path = make_pdf(
        tmp_path / "custom-ocr.pdf",
        pages=[{"images": [{"path": image_path, "rect": (72, 640, 180, 720)}]}],
    )

    def fail_import():
        raise AssertionError("built-in OCR should not be imported")

    monkeypatch.setattr("markitdown_pdf_images.ocr._import_pytesseract", fail_import)

    result = convert_pdf(
        pdf_path,
        ocr_enabled=True,
        ocr_engine=FakeOcrEngine("Custom OCR text"),
    )

    assert "Custom OCR text" in result.markdown


def test_builtin_tesseract_backend_works(make_pdf, make_image, monkeypatch, tmp_path):
    image_path = make_image(tmp_path / "scan.png", color=(10, 10, 10))
    pdf_path = make_pdf(
        tmp_path / "builtin-ocr.pdf",
        pages=[{"images": [{"path": image_path, "rect": (72, 640, 180, 720)}]}],
    )
    calls: list[dict[str, object]] = []
    state = SimpleNamespace(tesseract_cmd="tesseract")

    fake_pytesseract = SimpleNamespace(
        pytesseract=state,
        image_to_string=lambda image, *, lang=None, timeout=None: (
            calls.append(
                {
                    "size": image.size,
                    "lang": lang,
                    "timeout": timeout,
                    "tesseract_cmd": state.tesseract_cmd,
                }
            )
            or "Built-in OCR text"
        ),
    )
    monkeypatch.setattr(
        "markitdown_pdf_images.ocr._import_pytesseract",
        lambda: fake_pytesseract,
    )

    result = convert_pdf(
        pdf_path,
        ocr_enabled=True,
        tesseract_path=Path("/custom/tesseract"),
        ocr_languages="eng",
    )

    assert "Built-in OCR text" in result.markdown
    assert calls
    assert calls[0]["lang"] == "eng"
    assert calls[0]["timeout"] == 60
    assert calls[0]["tesseract_cmd"] == str(Path("/custom/tesseract"))
    assert state.tesseract_cmd == "tesseract"


def test_missing_ocr_backend_raises_clear_error(make_pdf, monkeypatch, tmp_path):
    pdf_path = make_pdf(
        tmp_path / "missing-ocr.pdf",
        pages=[{"text": "Hello"}],
    )

    def fail_import():
        raise RuntimeError(MISSING_OCR_BACKEND_MESSAGE)

    monkeypatch.setattr("markitdown_pdf_images.ocr._import_pytesseract", fail_import)

    with pytest.raises(RuntimeError, match=MISSING_OCR_BACKEND_MESSAGE):
        convert_pdf(pdf_path, ocr_enabled=True)


def test_library_api_result_structure(make_pdf, make_image, tmp_path):
    image_path = make_image(tmp_path / "api.png", color=(100, 100, 100))
    pdf_path = make_pdf(
        tmp_path / "api.pdf",
        pages=[
            {
                "text": "Library API sample.",
                "images": [{"path": image_path, "rect": (72, 640, 180, 720)}],
            }
        ],
    )

    result = convert_pdf(pdf_path, preserve_images=True, artifacts_dir=tmp_path / "assets")

    assert isinstance(result, PdfConversionResult)
    assert all(isinstance(asset, PdfAsset) for asset in result.assets)


def test_runtime_dependencies_declared():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    dependencies = data["project"]["dependencies"]

    assert any(dep.startswith("pillow") for dep in dependencies)
    assert any(dep.startswith("pytesseract") for dep in dependencies)
    assert not any(dep.startswith("pymupdf") for dep in dependencies)
    assert not any(dep.startswith("pymupdf4llm") for dep in dependencies)
