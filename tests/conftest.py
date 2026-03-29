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

            for vector in page.get("vectors", []):
                kind = vector["kind"]
                if kind == "line":
                    (x0, y0) = vector["start"]
                    (x1, y1) = vector["end"]
                    pdf.line(x0, y0, x1, y1)
                    continue

                if kind == "rect":
                    x0, y0, x1, y1 = vector["rect"]
                    pdf.rect(
                        x0,
                        y0,
                        x1 - x0,
                        y1 - y0,
                        stroke=1,
                        fill=vector.get("fill", 0),
                    )
                    continue

                raise ValueError(f"Unsupported vector kind: {kind}")

            for label in page.get("labels", []):
                x, y = label["pos"]
                pdf.drawString(x, y, label["text"])

            if index < len(pages) - 1:
                pdf.showPage()

        pdf.save()
        return path

    return _make_pdf
