import argparse
from pathlib import Path

from .converter import convert_pdf


def main() -> int:
    parser = argparse.ArgumentParser(prog="markitdown-pdf-images")
    parser.add_argument("input_pdf", type=Path)
    parser.add_argument(
        "--image-mode",
        choices=["external", "data-uri"],
        default="external",
    )
    parser.add_argument("--artifacts-dir", type=Path)
    parser.add_argument(
        "--path-mode",
        choices=["relative", "absolute"],
        default="relative",
    )
    args = parser.parse_args()

    result = convert_pdf(
        args.input_pdf,
        image_mode=args.image_mode,
        artifacts_dir=args.artifacts_dir,
        path_mode=args.path_mode,
    )
    print(result.markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
