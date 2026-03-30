from dataclasses import dataclass
import re

from PIL import ImageChops
import pypdfium2
from docling_core.types.doc.base import BoundingBox, CoordOrigin
from docling_core.types.doc.document import ImageRef

CAPTION_PATTERN = re.compile(r"^\s*(figure|fig\.?)\s*\d+", re.IGNORECASE)


@dataclass(frozen=True)
class TextLine:
    index: int
    bbox: BoundingBox
    text: str


@dataclass(frozen=True)
class TextBlock:
    id: int
    bbox: BoundingBox
    text: str
    line_indices: frozenset[int]
    line_count: int
    char_count: int
    lines: tuple[TextLine, ...]


@dataclass(frozen=True)
class TextSelection:
    block_id: int
    bbox: BoundingBox
    line_indices: frozenset[int]


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
    text_blocks = _build_text_blocks(getattr(page, "textline_cells", []))
    clusters = _cluster_boxes(shape_boxes)
    figures: list[VectorFigure] = []
    used_block_ids: set[int] = set()

    for cluster in clusters:
        if not _is_likely_figure(cluster, page_width=page_width, page_height=page_height):
            continue
        if any(_overlap_ratio(cluster, bitmap_box) >= 0.6 for bitmap_box in bitmap_boxes):
            continue

        attached = _select_attached_text_blocks(
            cluster,
            text_blocks,
            used_block_ids=used_block_ids,
        )
        final_bbox = cluster
        consumed_text_indices: set[int] = set()
        for selection in attached:
            final_bbox = _merge_boxes(final_bbox, selection.bbox)
            consumed_text_indices.update(selection.line_indices)
            used_block_ids.add(selection.block_id)

        image = _render_cluster_image(
            pdfium_page,
            bbox=final_bbox,
            page_width=page_width,
            page_height=page_height,
        )
        figures.append(
            VectorFigure(
                bbox=final_bbox,
                image_ref=ImageRef.from_pil(image, dpi=144),
                consumed_text_indices=frozenset(consumed_text_indices),
            )
        )

    return figures


def _build_text_blocks(lines: list[object]) -> list[TextBlock]:
    line_infos: list[TextLine] = []
    for line in lines:
        text = str(getattr(line, "text", "") or "").strip()
        if not text:
            continue
        line_infos.append(
            TextLine(
                index=int(getattr(line, "index", -1)),
                bbox=line.rect.to_bounding_box(),
                text=text,
            )
        )

    line_infos.sort(key=lambda item: (-float(item.bbox.t), float(item.bbox.l)))
    if not line_infos:
        return []

    blocks: list[TextBlock] = []
    current_lines: list[TextLine] = [line_infos[0]]
    current_bbox = line_infos[0].bbox
    previous_bbox = current_bbox

    for line in line_infos[1:]:
        if _should_merge_text_line(previous_bbox, line.bbox):
            current_lines.append(line)
            current_bbox = _merge_boxes(current_bbox, line.bbox)
            previous_bbox = line.bbox
            continue

        blocks.append(_make_text_block(len(blocks), current_bbox, current_lines))
        current_lines = [line]
        current_bbox = line.bbox
        previous_bbox = line.bbox

    blocks.append(_make_text_block(len(blocks), current_bbox, current_lines))
    return blocks


def _make_text_block(block_id: int, bbox: BoundingBox, lines: list[TextLine]) -> TextBlock:
    return TextBlock(
        id=block_id,
        bbox=bbox,
        text="\n".join(line.text for line in lines),
        line_indices=frozenset(line.index for line in lines),
        line_count=len(lines),
        char_count=sum(len(line.text) for line in lines),
        lines=tuple(lines),
    )


def _select_attached_text_blocks(
    cluster: BoundingBox,
    text_blocks: list[TextBlock],
    *,
    used_block_ids: set[int],
) -> list[TextSelection]:
    available_blocks = [block for block in text_blocks if block.id not in used_block_ids]
    attached: list[TextSelection] = []
    selected_ids: set[int] = set()

    inside_blocks = [
        block
        for block in available_blocks
        if _is_inside_or_overlapping(cluster, block.bbox)
    ]
    attached.extend(_selection_from_block(block) for block in inside_blocks)
    selected_ids.update(block.id for block in inside_blocks)

    title_block = _find_title_block(cluster, available_blocks, excluded_ids=selected_ids)
    if title_block is not None:
        attached.append(_selection_from_block(title_block))
        selected_ids.add(title_block.id)

    caption_block = _find_caption_block(cluster, available_blocks, excluded_ids=selected_ids)
    if caption_block is not None:
        attached.append(_caption_selection(caption_block))
        selected_ids.add(caption_block.id)

    legend_blocks = _find_legend_blocks(cluster, available_blocks, excluded_ids=selected_ids)
    attached.extend(_selection_from_block(block) for block in legend_blocks)

    return attached


def _find_title_block(
    cluster: BoundingBox,
    blocks: list[TextBlock],
    *,
    excluded_ids: set[int],
) -> TextBlock | None:
    candidates: list[tuple[float, TextBlock]] = []
    cluster_width = _box_width(cluster)
    cluster_center = _center_x(cluster)

    for block in blocks:
        if block.id in excluded_ids:
            continue
        if block.line_count > 2 or block.char_count > 80:
            continue

        distance = float(block.bbox.b) - float(cluster.t)
        if distance < -2 or distance > 72:
            continue

        block_center = _center_x(block.bbox)
        center_delta = abs(block_center - cluster_center)
        overlap = _axis_overlap(float(cluster.l), float(cluster.r), float(block.bbox.l), float(block.bbox.r))
        if center_delta > max(24.0, cluster_width * 0.22) and overlap < cluster_width * 0.25:
            continue

        score = 100.0 - distance - center_delta * 0.2
        candidates.append((score, block))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _find_caption_block(
    cluster: BoundingBox,
    blocks: list[TextBlock],
    *,
    excluded_ids: set[int],
) -> TextBlock | None:
    candidates: list[tuple[float, TextBlock]] = []
    cluster_width = _box_width(cluster)
    cluster_center = _center_x(cluster)

    for block in blocks:
        if block.id in excluded_ids:
            continue
        if not CAPTION_PATTERN.match(block.text):
            continue

        distance = float(cluster.b) - float(block.bbox.t)
        if distance < -2 or distance > 120:
            continue

        block_center = _center_x(block.bbox)
        center_delta = abs(block_center - cluster_center)
        width_ratio = _box_width(block.bbox) / max(cluster_width, 1.0)
        if center_delta > max(36.0, cluster_width * 0.3):
            continue
        if width_ratio < 0.4 or width_ratio > 1.8:
            continue

        score = 150.0 - distance - center_delta * 0.15
        candidates.append((score, block))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _find_legend_blocks(
    cluster: BoundingBox,
    blocks: list[TextBlock],
    *,
    excluded_ids: set[int],
) -> list[TextBlock]:
    candidates: list[tuple[float, TextBlock]] = []
    cluster_width = _box_width(cluster)

    for block in blocks:
        if block.id in excluded_ids:
            continue
        if block.line_count > 3 or block.char_count > 100:
            continue
        if CAPTION_PATTERN.match(block.text):
            continue

        overlap = _axis_overlap(float(cluster.l), float(cluster.r), float(block.bbox.l), float(block.bbox.r))
        below_distance = float(cluster.b) - float(block.bbox.t)
        side_gap = min(
            abs(float(block.bbox.r) - float(cluster.l)),
            abs(float(block.bbox.l) - float(cluster.r)),
        )
        vertical_overlap = _axis_overlap(float(cluster.b), float(cluster.t), float(block.bbox.b), float(block.bbox.t))

        is_below = -2 <= below_distance <= 54 and overlap >= cluster_width * 0.2
        is_side = side_gap <= 36 and vertical_overlap >= _box_height(block.bbox) * 0.5

        if not is_below and not is_side:
            continue

        score = 40.0
        if is_below:
            score += max(0.0, 30.0 - max(0.0, below_distance))
        if is_side:
            score += max(0.0, 20.0 - side_gap)
        candidates.append((score, block))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [block for _, block in candidates[:3]]


def _selection_from_block(block: TextBlock) -> TextSelection:
    return TextSelection(
        block_id=block.id,
        bbox=block.bbox,
        line_indices=block.line_indices,
    )


def _caption_selection(block: TextBlock) -> TextSelection:
    selected_lines: list[TextLine] = []
    total_chars = 0

    for line in block.lines:
        selected_lines.append(line)
        total_chars += len(line.text)
        if any(mark in line.text for mark in (".", "!", "?")):
            break
        if len(selected_lines) >= 2 or total_chars >= 120:
            break

    bbox = selected_lines[0].bbox
    for line in selected_lines[1:]:
        bbox = _merge_boxes(bbox, line.bbox)

    return TextSelection(
        block_id=block.id,
        bbox=bbox,
        line_indices=frozenset(line.index for line in selected_lines),
    )


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


def _render_cluster_image(
    pdfium_page: pypdfium2.PdfPage,
    *,
    bbox: BoundingBox,
    page_width: float,
    page_height: float,
):
    padding = 4.0
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
    image = bitmap.to_pil().convert("RGB")
    return _trim_whitespace(image)


def _trim_whitespace(image):
    background = image.copy()
    background.paste((255, 255, 255), (0, 0, image.width, image.height))
    diff = ImageChops.difference(image, background)
    bbox = diff.getbbox()
    if bbox is None:
        return image

    padding = 4
    left = max(0, bbox[0] - padding)
    upper = max(0, bbox[1] - padding)
    right = min(image.width, bbox[2] + padding)
    lower = min(image.height, bbox[3] + padding)
    return image.crop((left, upper, right, lower))


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


def _should_merge_text_line(previous: BoundingBox, current: BoundingBox) -> bool:
    vertical_gap = max(0.0, float(previous.b) - float(current.t))
    height_threshold = max(_box_height(previous), _box_height(current)) * 1.4
    overlap = _axis_overlap(float(previous.l), float(previous.r), float(current.l), float(current.r))
    min_width = max(1.0, min(_box_width(previous), _box_width(current)))
    left_delta = abs(float(previous.l) - float(current.l))
    center_delta = abs(_center_x(previous) - _center_x(current))

    return vertical_gap <= height_threshold and (
        overlap / min_width >= 0.2 or left_delta <= 24.0 or center_delta <= 36.0
    )


def _is_inside_or_overlapping(cluster: BoundingBox, text_box: BoundingBox) -> bool:
    expanded = BoundingBox(
        l=float(cluster.l) - 6.0,
        t=float(cluster.t) + 6.0,
        r=float(cluster.r) + 6.0,
        b=float(cluster.b) - 6.0,
        coord_origin=cluster.coord_origin,
    )
    if (
        float(text_box.l) >= float(expanded.l)
        and float(text_box.r) <= float(expanded.r)
        and float(text_box.b) >= float(expanded.b)
        and float(text_box.t) <= float(expanded.t)
    ):
        return True

    return _overlap_ratio(cluster, text_box) >= 0.18


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


def _center_x(box: BoundingBox) -> float:
    return (float(box.l) + float(box.r)) / 2


def _axis_overlap(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))


def _box_width(box: BoundingBox) -> float:
    return abs(float(box.r) - float(box.l))


def _box_height(box: BoundingBox) -> float:
    return abs(float(box.t) - float(box.b))
