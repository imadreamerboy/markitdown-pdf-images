from dataclasses import dataclass

import pypdfium2
from docling_core.types.doc.base import BoundingBox, CoordOrigin
from docling_core.types.doc.document import ImageRef


@dataclass(frozen=True)
class VectorFigure:
    bbox: BoundingBox
    image_ref: ImageRef
    consumed_text_indices: frozenset[int]


def extract_vector_figures(
    *,
    page: object,
    page_width: float,
    page_height: float,
    pdfium_page: pypdfium2.PdfPage,
) -> list[VectorFigure]:
    shape_boxes = [_shape_bbox(shape) for shape in getattr(page, "shapes", [])]
    if not shape_boxes:
        return []

    bitmap_boxes = [bitmap.rect.to_bounding_box() for bitmap in getattr(page, "bitmap_resources", [])]
    text_lines = list(getattr(page, "textline_cells", []))
    clusters = _cluster_boxes(shape_boxes)
    figures: list[VectorFigure] = []

    for cluster in clusters:
        if not _is_likely_figure(cluster, page_width=page_width, page_height=page_height):
            continue
        if any(_overlap_ratio(cluster, bitmap_box) >= 0.6 for bitmap_box in bitmap_boxes):
            continue

        expanded_bbox, consumed_text_indices = _expand_cluster_with_labels(cluster, text_lines)
        image = _render_cluster_image(
            pdfium_page,
            bbox=expanded_bbox,
            page_width=page_width,
            page_height=page_height,
        )
        figures.append(
            VectorFigure(
                bbox=expanded_bbox,
                image_ref=ImageRef.from_pil(image, dpi=144),
                consumed_text_indices=frozenset(consumed_text_indices),
            )
        )

    return figures


def _shape_bbox(shape: object) -> BoundingBox:
    points = list(getattr(shape, "points", []))
    if not points:
        return BoundingBox(l=0, t=0, r=0, b=0, coord_origin=CoordOrigin.BOTTOMLEFT)

    xs = [float(point.x) for point in points]
    ys = [float(point.y) for point in points]
    coord_origin = getattr(shape, "coord_origin", CoordOrigin.BOTTOMLEFT)
    return BoundingBox(
        l=min(xs),
        t=max(ys),
        r=max(xs),
        b=min(ys),
        coord_origin=coord_origin,
    )


def _cluster_boxes(boxes: list[BoundingBox]) -> list[BoundingBox]:
    clusters: list[BoundingBox] = []
    for box in boxes:
        if _box_width(box) < 3 and _box_height(box) < 3:
            continue

        merged = False
        for index, cluster in enumerate(clusters):
            if _boxes_are_close(cluster, box):
                clusters[index] = _merge_boxes(cluster, box)
                merged = True
                break
        if not merged:
            clusters.append(box)

    changed = True
    while changed:
        changed = False
        merged_clusters: list[BoundingBox] = []
        for cluster in clusters:
            for index, existing in enumerate(merged_clusters):
                if _boxes_are_close(existing, cluster):
                    merged_clusters[index] = _merge_boxes(existing, cluster)
                    changed = True
                    break
            else:
                merged_clusters.append(cluster)
        clusters = merged_clusters

    return clusters


def _expand_cluster_with_labels(
    cluster: BoundingBox,
    text_lines: list[object],
) -> tuple[BoundingBox, set[int]]:
    expanded = cluster
    consumed_text_indices: set[int] = set()
    margin_x = max(18.0, _box_width(cluster) * 0.1)
    margin_y = max(24.0, _box_height(cluster) * 0.18)

    for line in text_lines:
        bbox = line.rect.to_bounding_box()
        if not _is_near_cluster(expanded, bbox, margin_x=margin_x, margin_y=margin_y):
            continue
        expanded = _merge_boxes(expanded, bbox)
        consumed_text_indices.add(int(getattr(line, "index", -1)))

    return expanded, consumed_text_indices


def _render_cluster_image(
    pdfium_page: pypdfium2.PdfPage,
    *,
    bbox: BoundingBox,
    page_width: float,
    page_height: float,
):
    padding = max(12.0, min(_box_width(bbox), _box_height(bbox)) * 0.08)
    left = max(0.0, float(bbox.l) - padding)
    right = min(page_width, float(bbox.r) + padding)
    bottom = max(0.0, float(bbox.b) - padding)
    top = min(page_height, float(bbox.t) + padding)

    crop = (
        left,
        bottom,
        max(0.0, page_width - right),
        max(0.0, page_height - top),
    )
    bitmap = pdfium_page.render(scale=2.0, crop=crop)
    return bitmap.to_pil()


def _is_likely_figure(
    box: BoundingBox,
    *,
    page_width: float,
    page_height: float,
) -> bool:
    width = _box_width(box)
    height = _box_height(box)
    area = width * height
    page_area = page_width * page_height

    if width < 40 or height < 40:
        return False
    if area < 4000:
        return False
    if area / page_area > 0.75:
        return False
    return True


def _is_near_cluster(
    cluster: BoundingBox,
    text_box: BoundingBox,
    *,
    margin_x: float,
    margin_y: float,
) -> bool:
    horizontal = float(text_box.r) >= float(cluster.l) - margin_x and float(text_box.l) <= float(cluster.r) + margin_x
    vertical = float(text_box.t) >= float(cluster.b) - margin_y and float(text_box.b) <= float(cluster.t) + margin_y
    return horizontal and vertical


def _boxes_are_close(first: BoundingBox, second: BoundingBox) -> bool:
    margin_x = max(12.0, min(_box_width(first), _box_width(second)) * 0.12)
    margin_y = max(12.0, min(_box_height(first), _box_height(second)) * 0.12)

    horizontal = float(first.r) >= float(second.l) - margin_x and float(second.r) >= float(first.l) - margin_x
    vertical = float(first.t) >= float(second.b) - margin_y and float(second.t) >= float(first.b) - margin_y
    return horizontal and vertical


def _overlap_ratio(first: BoundingBox, second: BoundingBox) -> float:
    left = max(float(first.l), float(second.l))
    right = min(float(first.r), float(second.r))
    bottom = max(float(first.b), float(second.b))
    top = min(float(first.t), float(second.t))
    if right <= left or top <= bottom:
        return 0.0

    intersection = (right - left) * (top - bottom)
    first_area = _box_width(first) * _box_height(first)
    if first_area == 0:
        return 0.0
    return intersection / first_area


def _merge_boxes(first: BoundingBox, second: BoundingBox) -> BoundingBox:
    return BoundingBox(
        l=min(float(first.l), float(second.l)),
        t=max(float(first.t), float(second.t)),
        r=max(float(first.r), float(second.r)),
        b=min(float(first.b), float(second.b)),
        coord_origin=first.coord_origin,
    )


def _box_width(box: BoundingBox) -> float:
    return abs(float(box.r) - float(box.l))


def _box_height(box: BoundingBox) -> float:
    return abs(float(box.t) - float(box.b))
