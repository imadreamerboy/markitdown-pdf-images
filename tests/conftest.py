from pathlib import Path

import pytest
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


@pytest.fixture
def make_image():
    def _make_image(path: Path, *, color: tuple[int, int, int]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (80, 40), color).save(path)
        return path

    return _make_image


@pytest.fixture
def make_pdf():
    def _make_pdf(
        path: Path,
        *,
        title: str | None = None,
        pages: list[dict],
    ) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        pdf = canvas.Canvas(str(path), pagesize=A4)
        if title:
            pdf.setTitle(title)

        for index, page in enumerate(pages):
            text = page.get("text", "")
            lines = str(text).splitlines() or [""]
            y = 760
            for line in lines:
                if line:
                    pdf.drawString(72, y, line)
                y -= 16

            for image in page.get("images", []):
                x0, y0, x1, y1 = image["rect"]
                pdf.drawImage(
                    ImageReader(str(image["path"])),
                    x0,
                    y0,
                    width=x1 - x0,
                    height=y1 - y0,
                    preserveAspectRatio=False,
                    mask="auto",
                )

            if index < len(pages) - 1:
                pdf.showPage()

        pdf.save()
        return path

    return _make_pdf
