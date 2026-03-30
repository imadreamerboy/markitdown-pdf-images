import markitdown._markitdown as markitdown_module
import pytest
from markitdown import MarkItDown
from markitdown.converters._pdf_converter import PdfConverter as BuiltinPdfConverter

import markitdown_pdf_images.plugin as plugin_module
from markitdown_pdf_images.plugin import PDF_PLUGIN_PRIORITY, PdfImagesConverter


@pytest.fixture(autouse=True)
def reset_markitdown_plugin_cache():
    markitdown_module._plugins = None
    yield
    markitdown_module._plugins = None


def test_plugin_registration():
    markdown = MarkItDown(enable_plugins=True)
    registrations = sorted(markdown._converters, key=lambda item: item.priority)

    plugin_index = next(
        index
        for index, registration in enumerate(registrations)
        if isinstance(registration.converter, PdfImagesConverter)
    )
    builtin_index = next(
        index
        for index, registration in enumerate(registrations)
        if isinstance(registration.converter, BuiltinPdfConverter)
    )

    assert registrations[plugin_index].priority == PDF_PLUGIN_PRIORITY
    assert plugin_index < builtin_index


def test_plugin_falls_back_to_builtin_when_custom_converter_fails(
    make_pdf,
    monkeypatch,
    tmp_path,
):
    pdf_path = make_pdf(
        tmp_path / "fallback.pdf",
        pages=[{"text": "Built-in fallback text."}],
    )

    def fail_conversion(*args, **kwargs):
        raise RuntimeError("expected plugin failure")

    monkeypatch.setattr(plugin_module, "convert_pdf", fail_conversion)

    markdown = MarkItDown(enable_plugins=True)
    result = markdown.convert(pdf_path)

    assert "Built-in fallback text." in result.markdown


def test_plugin_attaches_structured_pdf_metadata(make_pdf, make_image, tmp_path):
    image_path = make_image(tmp_path / "plugin-image.png", color=(255, 0, 0))
    pdf_path = make_pdf(
        tmp_path / "plugin.pdf",
        pages=[
            {
                "text": "Plugin metadata sample.",
                "images": [{"path": image_path, "rect": (72, 640, 180, 720)}],
            }
        ],
    )

    markdown = MarkItDown(enable_plugins=True)
    result = markdown.convert(
        pdf_path,
        pdf_preserve_images=True,
        pdf_artifacts_dir=tmp_path / "assets",
    )

    assert hasattr(result, "pdf_conversion_result")
    assert hasattr(result, "pdf_assets")
    assert result.pdf_conversion_result.assets == result.pdf_assets
    assert len(result.pdf_assets) == 1
    assert result.pdf_assets[0].path is not None
