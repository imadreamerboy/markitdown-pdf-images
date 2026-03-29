import io
import tomllib
from pathlib import Path

from markitdown_pdf_images import PdfAsset, PdfConversionResult, convert_pdf


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
    result = convert_pdf(pdf_path, artifacts_dir=artifacts_dir)

    assert len(result.assets) == 1
    asset = result.assets[0]
    assert asset.path is not None
    assert asset.path.exists()
    assert asset.filename == asset.path.name
    assert asset.page_number == 1
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

    result = convert_pdf(pdf_path)

    assert len(result.assets) == 1
    asset = result.assets[0]
    assert asset.path is None
    assert asset.filename == "p0001-01.png"
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

    result = convert_pdf(pdf_path, artifacts_dir=tmp_path / "assets")

    assert len(result.assets) == 3
    assert [asset.page_number for asset in result.assets] == [1, 1, 2]
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

    result = convert_pdf(pdf_path, artifacts_dir=tmp_path / "assets")

    assert len(result.assets) == 1
    assert result.assets[0].path is not None
    assert result.assets[0].path.exists()
    assert result.assets[0].filename.endswith(".png")
    assert result.assets[0].page_number == 1
    assert "![Image](" in result.markdown


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

    first_result = convert_pdf(first_pdf, artifacts_dir=shared_artifacts_dir)
    second_result = convert_pdf(second_pdf, artifacts_dir=shared_artifacts_dir)

    assert first_result.assets[0].path is not None
    assert second_result.assets[0].path is not None
    assert first_result.assets[0].path.parent != second_result.assets[0].path.parent
    assert first_result.assets[0].markdown_path != second_result.assets[0].markdown_path


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

    result = convert_pdf(pdf_path, artifacts_dir=tmp_path / "assets")

    assert isinstance(result, PdfConversionResult)
    assert all(isinstance(asset, PdfAsset) for asset in result.assets)


def test_convert_pdf_accepts_binary_stream(make_pdf, tmp_path):
    pdf_path = make_pdf(
        tmp_path / "stream.pdf",
        pages=[{"text": "Stream source."}],
    )

    stream = io.BytesIO(pdf_path.read_bytes())
    stream.name = "stream.pdf"
    result = convert_pdf(stream)

    assert "Stream source." in result.markdown


def test_pyproject_has_no_pymupdf_dependency():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    dependencies = " ".join(data["project"]["dependencies"]).lower()

    assert "pymupdf" not in dependencies
    assert "pymupdf4llm" not in dependencies
