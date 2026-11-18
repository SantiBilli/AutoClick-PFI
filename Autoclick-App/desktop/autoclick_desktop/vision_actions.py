from __future__ import annotations

from dataclasses import dataclass
import difflib
import importlib.util
import math
import os
import re
import shutil
from threading import Event
import time
from typing import Any, Callable, Protocol, Sequence
import unicodedata

from PIL import Image, ImageEnhance, ImageOps

from autoclick_desktop.dpi import enable_windows_dpi_awareness
from autoclick_desktop.execution_context import VirtualDesktopBounds
from autoclick_desktop.execution_errors import (
    ExecutionCancelled,
    ExecutionErrorCode,
    HandlerError,
)
from autoclick_desktop.execution_models import ResolvedAction


def _normalize_text(text: str) -> str:
    """Normalize text: casefold, Unicode NFKD diacritic removal, whitespace collapse."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(without_marks.split())


def _similarity_score(query: str, candidate: str) -> float:
    """Compare complete strings; a shared fragment is not a complete target."""
    norm_query = _normalize_text(query)
    norm_candidate = _normalize_text(candidate)
    if not norm_query or not norm_candidate:
        return 0.0
    if norm_query == norm_candidate:
        return 1.0

    try:
        import rapidfuzz.fuzz as fuzz  # type: ignore

        return float(fuzz.ratio(norm_query, norm_candidate)) / 100.0
    except Exception:
        matcher = difflib.SequenceMatcher(None, norm_query, norm_candidate, autojunk=False)
        return matcher.ratio()


@dataclass(frozen=True, slots=True)
class OcrBox:
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float
    line_num: int = 0
    word_num: int = 0


@dataclass(frozen=True, slots=True)
class VisionMatchResult:
    found: bool
    x: int
    y: int
    width: int
    height: int
    center_x: int
    center_y: int
    confidence: float
    detected_text: str
    pantalla_x: int | None = None
    pantalla_y: int | None = None
    pantalla_width: int | None = None
    pantalla_height: int | None = None
    pantalla_center_x: int | None = None
    pantalla_center_y: int | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "encontrado": self.found,
            "x": self.x,
            "y": self.y,
            "ancho": self.width,
            "alto": self.height,
            "centroX": self.center_x,
            "centroY": self.center_y,
            "confianza": self.confidence,
            "textoDetectado": self.detected_text,
        }
        if self.pantalla_x is not None:
            result.update(
                {
                    "pantallaX": self.pantalla_x,
                    "pantallaY": self.pantalla_y,
                    "pantallaAncho": self.pantalla_width,
                    "pantallaAlto": self.pantalla_height,
                    "pantallaCentroX": self.pantalla_center_x,
                    "pantallaCentroY": self.pantalla_center_y,
                }
            )
        return result


class OcrEngineAdapter(Protocol):
    def is_available(self) -> bool: ...
    def detect_words(self, image: Image.Image) -> list[OcrBox]: ...


COMMON_TESSERACT_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def _find_tesseract_binary(configured: str | None = None) -> str | None:
    if configured:
        if os.path.isabs(configured) and os.path.exists(configured):
            return configured
        which_configured = shutil.which(configured)
        if which_configured:
            return which_configured
    env_configured = os.getenv("AUTOCLICK_TESSERACT_PATH") or os.getenv("TESSERACT_PATH")
    if env_configured and os.path.exists(env_configured):
        return env_configured
    which_default = shutil.which("tesseract")
    if which_default:
        return which_default
    for common in COMMON_TESSERACT_PATHS:
        if os.path.exists(common):
            return common
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        for sub in (
            r"Programs\Tesseract-OCR\tesseract.exe",
            r"Tesseract-OCR\tesseract.exe",
            r"Programs\Tesseract\tesseract.exe",
        ):
            p = os.path.join(local_app_data, sub)
            if os.path.exists(p):
                return p
    program_data = os.getenv("ProgramData")
    if program_data:
        p = os.path.join(program_data, r"Tesseract-OCR\tesseract.exe")
        if os.path.exists(p):
            return p
    try:
        from pathlib import Path

        app_root = Path(__file__).resolve().parents[2]
        bundled = app_root / "tools" / "tesseract" / "tesseract.exe"
        if bundled.exists():
            return str(bundled)
    except Exception:
        pass
    return None


class TesseractOcrEngine:
    def __init__(self, tesseract_cmd: str | None = None) -> None:
        self._tesseract_cmd = tesseract_cmd

    def is_available(self) -> bool:
        if importlib.util.find_spec("pytesseract") is None:
            return False
        return _find_tesseract_binary(self._tesseract_cmd) is not None

    def detect_words(self, image: Image.Image) -> list[OcrBox]:
        try:
            import pytesseract  # type: ignore
            from pytesseract import Output  # type: ignore
        except Exception:
            raise HandlerError(ExecutionErrorCode.VISION_OCR_UNAVAILABLE) from None

        binary = _find_tesseract_binary(self._tesseract_cmd)
        if not binary:
            raise HandlerError(ExecutionErrorCode.VISION_OCR_UNAVAILABLE)

        pytesseract.pytesseract.tesseract_cmd = binary

        # Small UI glyphs lose accents and strokes at native screen resolution.
        # Upscale for recognition, cap the working image, then map boxes back to
        # the original capture so mouse coordinates and region offsets stay exact.
        pixels = max(1, image.width * image.height)
        scale = 4 if pixels * 16 <= 40_000_000 else 2 if pixels * 4 <= 40_000_000 else 1
        source = image.resize((image.width * scale, image.height * scale), Image.Resampling.LANCZOS) if scale > 1 else image
        processed = ImageOps.grayscale(source)
        enhancer = ImageEnhance.Contrast(processed)
        processed = enhancer.enhance(1.5)

        try:
            data = pytesseract.image_to_data(processed, output_type=Output.DICT)
        except Exception:
            raise HandlerError(ExecutionErrorCode.VISION_OCR_UNAVAILABLE) from None

        boxes: list[OcrBox] = []
        n_boxes = len(data.get("text", []))
        for i in range(n_boxes):
            text = str(data["text"][i]).strip()
            if not text:
                continue
            conf_val = float(data["conf"][i])
            if conf_val < 0:
                continue
            confidence = max(0.0, min(1.0, conf_val / 100.0))
            left, top = int(data["left"][i]), int(data["top"][i])
            right = left + int(data["width"][i])
            bottom = top + int(data["height"][i])
            x, y = left // scale, top // scale
            boxes.append(
                OcrBox(
                    text=text,
                    x=x,
                    y=y,
                    width=max(1, math.ceil(right / scale) - x),
                    height=max(1, math.ceil(bottom / scale) - y),
                    confidence=confidence,
                    line_num=int(data.get("line_num", [0] * n_boxes)[i]),
                    word_num=int(data.get("word_num", [0] * n_boxes)[i]),
                )
            )
        return boxes


class ScreenCaptureProvider(Protocol):
    def is_available(self) -> bool: ...
    def capture_screen(self) -> tuple[Image.Image, tuple[int, int]]: ...
    def capture_active_window(self) -> tuple[Image.Image, tuple[int, int]]: ...
    def capture_region(self, x: int, y: int, width: int, height: int) -> tuple[Image.Image, tuple[int, int]]: ...


class LocalScreenCaptureProvider:
    def __init__(self) -> None:
        enable_windows_dpi_awareness()

    def is_available(self) -> bool:
        return True

    def capture_screen(self) -> tuple[Image.Image, tuple[int, int]]:
        offset_x, offset_y = 0, 0
        try:
            import ctypes

            user32 = getattr(ctypes, "windll", None)
            if user32 and hasattr(user32, "user32"):
                offset_x = int(user32.user32.GetSystemMetrics(76))
                offset_y = int(user32.user32.GetSystemMetrics(77))
        except Exception:
            pass

        # 1. Try all screens with PIL
        try:
            from PIL import ImageGrab  # type: ignore

            return ImageGrab.grab(all_screens=True), (offset_x, offset_y)
        except Exception:
            pass

        # 2. Try primary screen with PIL
        try:
            from PIL import ImageGrab  # type: ignore

            return ImageGrab.grab(all_screens=False), (0, 0)
        except Exception:
            pass

        # 3. Fallback to pyautogui
        try:
            import pyautogui  # type: ignore

            return pyautogui.screenshot(), (0, 0)
        except Exception:
            pass

        raise HandlerError(ExecutionErrorCode.VISION_CAPTURE_FAILED)

    def capture_active_window(self) -> tuple[Image.Image, tuple[int, int]]:
        try:
            import pygetwindow  # type: ignore

            active = pygetwindow.getActiveWindow()
            if active is not None and active.width > 0 and active.height > 0:
                left, top = int(active.left), int(active.top)
                width, height = int(active.width), int(active.height)
                return self.capture_region(left, top, width, height)
        except Exception:
            pass
        return self.capture_screen()

    def capture_region(self, x: int, y: int, width: int, height: int) -> tuple[Image.Image, tuple[int, int]]:
        if width <= 0 or height <= 0:
            raise HandlerError(ExecutionErrorCode.ACTION_PARAMETER_INVALID)

        # 1. Try PIL ImageGrab with bbox
        try:
            from PIL import ImageGrab  # type: ignore

            return ImageGrab.grab(bbox=(x, y, x + width, y + height)), (x, y)
        except Exception:
            pass

        # 2. Try pyautogui screenshot with region
        try:
            import pyautogui  # type: ignore

            return pyautogui.screenshot(region=(x, y, width, height)), (x, y)
        except Exception:
            pass

        # 3. Fallback: capture screen and crop
        try:
            full_img, offset = self.capture_screen()
            crop_x = x - offset[0]
            crop_y = y - offset[1]
            crop_box = (
                max(0, crop_x),
                max(0, crop_y),
                min(full_img.width, crop_x + width),
                min(full_img.height, crop_y + height),
            )
            if crop_box[2] > crop_box[0] and crop_box[3] > crop_box[1]:
                return full_img.crop(crop_box), (x, y)
        except Exception:
            pass

        raise HandlerError(ExecutionErrorCode.VISION_CAPTURE_FAILED)


def _build_candidate_phrases(boxes: list[OcrBox], max_tokens: int = 10) -> list[OcrBox]:
    """Generate both single word boxes and contiguous line phrases for multi-word matching."""
    if not boxes:
        return []
    candidates: list[OcrBox] = list(boxes)

    # OCR line numbers repeat across blocks. Group by overlapping glyphs and
    # aligned baselines, then split large gaps between separate controls/columns.
    lines: list[list[OcrBox]] = []
    for box in sorted(boxes, key=lambda b: (b.y, b.x)):
        compatible: list[tuple[int, int, list[OcrBox]]] = []
        for line in lines:
            # A distant column may use a smaller font. Align with the nearest
            # word so its glyph bounds cannot split a valid local phrase.
            anchor = min(line, key=lambda other: max(
                other.x - box.x - box.width, box.x - other.x - other.width, 0
            ))
            min_height = min(box.height, anchor.height)
            overlap = min(box.y + box.height, anchor.y + anchor.height) - max(box.y, anchor.y)
            baseline_delta = abs(box.y + box.height - anchor.y - anchor.height)
            if min_height > 0 and overlap >= min_height * 0.5 and baseline_delta <= max(3, min_height * 0.5):
                gap = max(anchor.x - box.x - box.width, box.x - anchor.x - anchor.width, 0)
                compatible.append((gap, baseline_delta, line))
        if compatible:
            min(compatible, key=lambda item: item[:2])[2].append(box)
        else:
            lines.append([box])

    runs: list[list[OcrBox]] = []
    for line_boxes in lines:
        line_boxes.sort(key=lambda b: b.x)
        run: list[OcrBox] = []
        for box in line_boxes:
            if run:
                previous = run[-1]
                gap = box.x - previous.x - previous.width
                if gap > max(12, min(previous.height, box.height) * 0.9):
                    runs.append(run)
                    run = []
            run.append(box)
        if run:
            runs.append(run)

    for line_boxes in runs:
        n = len(line_boxes)
        for length in range(2, min(n + 1, max_tokens + 1)):
            for start in range(n - length + 1):
                window = line_boxes[start : start + length]
                combined_text = " ".join(b.text for b in window)
                min_x = min(b.x for b in window)
                min_y = min(b.y for b in window)
                max_x = max(b.x + b.width for b in window)
                max_y = max(b.y + b.height for b in window)
                avg_conf = sum(b.confidence for b in window) / len(window)
                candidates.append(
                    OcrBox(
                        text=combined_text,
                        x=min_x,
                        y=min_y,
                        width=max_x - min_x,
                        height=max_y - min_y,
                        confidence=avg_conf,
                    )
                )
    return candidates


def match_text_candidates(
    query: str,
    boxes: list[OcrBox],
    *,
    match_type: str = "aproximada",
    threshold: float = 0.75,
    offset: tuple[int, int] = (0, 0),
    base_resolution: tuple[int, int] | None = None,
    desktop_bounds: VirtualDesktopBounds | None = None,
) -> VisionMatchResult | None:
    """Find the best matching candidate above threshold with deterministic ranking."""
    query = query.strip()
    if not query or not boxes:
        return None

    norm_query = _normalize_text(query)
    candidates = _build_candidate_phrases(boxes, max_tokens=max(10, len(norm_query.split())))
    scored: list[tuple[float, float, int, int, float, OcrBox]] = []

    for box in candidates:
        norm_candidate = _normalize_text(box.text)
        if not norm_candidate or box.confidence < threshold:
            continue

        if match_type == "exacta":
            if norm_query == norm_candidate:
                score = 2.0 + box.confidence
                if box.confidence >= threshold:
                    scored.append((score, box.confidence, -box.y, -box.x, box.confidence, box))
            elif len(norm_query) > 3 and re.search(r"(?<!\w)" + re.escape(norm_query) + r"(?!\w)", norm_candidate):
                score = 1.0 + box.confidence
                if box.confidence >= threshold:
                    scored.append((score, box.confidence, -box.y, -box.x, box.confidence, box))
        else:
            if norm_query == norm_candidate:
                sim = 1.0
                rank = 10.0 + box.confidence
                reported_conf = box.confidence
                if box.confidence >= threshold:
                    scored.append((rank, box.confidence, -box.y, -box.x, reported_conf, box))
            else:
                sim = _similarity_score(query, box.text)
                if sim >= threshold:
                    combined = sim * 0.7 + box.confidence * 0.3
                    # Text similarity ranks first; OCR confidence breaks ties.
                    rank = sim
                    reported_conf = combined
                    if combined >= threshold:
                        scored.append((rank, box.confidence, -box.y, -box.x, reported_conf, box))

    if not scored:
        return None

    # Sort descending by primary score, secondary confidence, tertiary deterministic position
    scored.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)
    best_item = scored[0]
    best_box = best_item[5]
    final_score = round(best_item[4], 2)

    abs_x = offset[0] + best_box.x
    abs_y = offset[1] + best_box.y
    center_x = round(abs_x + best_box.width / 2.0)
    center_y = round(abs_y + best_box.height / 2.0)

    # If base resolution is active, map target screen coordinates to base coordinates
    # so that downstream mouse actions scaled via _ScaledMouse hit the exact detected position.
    if (
        base_resolution is not None
        and desktop_bounds is not None
        and desktop_bounds.width > 1
        and desktop_bounds.height > 1
    ):
        base_w, base_h = base_resolution
        base_x = round((abs_x - desktop_bounds.left) * (base_w - 1) / (desktop_bounds.width - 1))
        base_y = round((abs_y - desktop_bounds.top) * (base_h - 1) / (desktop_bounds.height - 1))
        base_center_x = round((center_x - desktop_bounds.left) * (base_w - 1) / (desktop_bounds.width - 1))
        base_center_y = round((center_y - desktop_bounds.top) * (base_h - 1) / (desktop_bounds.height - 1))
        base_width = max(1, round(best_box.width * (base_w - 1) / (desktop_bounds.width - 1)))
        base_height = max(1, round(best_box.height * (base_h - 1) / (desktop_bounds.height - 1)))
        out_x, out_y = base_x, base_y
        out_w, out_h = base_width, base_height
        out_cx, out_cy = base_center_x, base_center_y
    else:
        out_x, out_y = abs_x, abs_y
        out_w, out_h = best_box.width, best_box.height
        out_cx, out_cy = center_x, center_y

    return VisionMatchResult(
        found=True,
        x=out_x,
        y=out_y,
        width=out_w,
        height=out_h,
        center_x=out_cx,
        center_y=out_cy,
        confidence=final_score,
        detected_text=best_box.text,
        pantalla_x=abs_x,
        pantalla_y=abs_y,
        pantalla_width=best_box.width,
        pantalla_height=best_box.height,
        pantalla_center_x=center_x,
        pantalla_center_y=center_y,
    )



def handle_vision_detect_element(
    action: ResolvedAction,
    cancel_event: Event,
    capture_provider: ScreenCaptureProvider | None = None,
    ocr_engine: OcrEngineAdapter | None = None,
    base_resolution: tuple[int, int] | None = None,
    desktop_bounds: VirtualDesktopBounds | None = None,
) -> dict[str, Any]:
    """Execute vision.detectElement search loop and return candidate dictionary."""
    capture = capture_provider or LocalScreenCaptureProvider()
    engine = ocr_engine or TesseractOcrEngine()

    if not engine.is_available():
        raise HandlerError(ExecutionErrorCode.VISION_OCR_UNAVAILABLE)

    text = str(action.params.get("text", "")).strip()
    if not text:
        raise HandlerError(ExecutionErrorCode.ACTION_PARAMETER_INVALID)

    scope = str(action.params.get("scope", "pantalla"))
    confidence_threshold = float(action.params.get("confidenceThreshold", 0.75))
    if not (0.0 <= confidence_threshold <= 1.0):
        raise HandlerError(ExecutionErrorCode.ACTION_PARAMETER_INVALID)

    timeout_s = float(action.params.get("timeout", 10))
    if timeout_s <= 0:
        raise HandlerError(ExecutionErrorCode.ACTION_PARAMETER_INVALID)

    poll_interval_ms = int(action.params.get("pollIntervalMs", 500))
    if poll_interval_ms < 50:
        raise HandlerError(ExecutionErrorCode.ACTION_PARAMETER_INVALID)

    match_type = str(action.params.get("matchType", "aproximada"))
    if match_type not in {"exacta", "aproximada"}:
        raise HandlerError(ExecutionErrorCode.ACTION_PARAMETER_INVALID)

    x = action.params.get("x")
    y = action.params.get("y")
    width = action.params.get("width")
    height = action.params.get("height")

    reg_x, reg_y, reg_w, reg_h = 0, 0, 0, 0
    if scope == "region":
        if x is None or y is None or width is None or height is None:
            raise HandlerError(ExecutionErrorCode.ACTION_PARAMETER_INVALID)
        try:
            x_int, y_int, w_int, h_int = int(x), int(y), int(width), int(height)
            if w_int <= 0 or h_int <= 0 or x_int < 0 or y_int < 0:
                raise HandlerError(ExecutionErrorCode.ACTION_PARAMETER_INVALID)
        except (TypeError, ValueError):
            raise HandlerError(ExecutionErrorCode.ACTION_PARAMETER_INVALID) from None

        # Pro-rate region from base resolution to current desktop bounds if base resolution is active
        if (
            base_resolution is not None
            and desktop_bounds is not None
            and desktop_bounds.width > 1
            and desktop_bounds.height > 1
        ):
            base_w, base_h = base_resolution
            reg_x = desktop_bounds.left + round(x_int * (desktop_bounds.width - 1) / (base_w - 1))
            reg_y = desktop_bounds.top + round(y_int * (desktop_bounds.height - 1) / (base_h - 1))
            reg_w = max(1, round(w_int * (desktop_bounds.width - 1) / (base_w - 1)))
            reg_h = max(1, round(h_int * (desktop_bounds.height - 1) / (base_h - 1)))
        else:
            reg_x, reg_y, reg_w, reg_h = x_int, y_int, w_int, h_int

        if desktop_bounds is not None:
            max_right = desktop_bounds.left + desktop_bounds.width
            max_bottom = desktop_bounds.top + desktop_bounds.height
            reg_x = max(desktop_bounds.left, min(reg_x, max_right - 1))
            reg_y = max(desktop_bounds.top, min(reg_y, max_bottom - 1))
            reg_w = max(1, min(reg_w, max_right - reg_x))
            reg_h = max(1, min(reg_h, max_bottom - reg_y))

    deadline = time.monotonic() + timeout_s

    while True:
        if cancel_event.is_set():
            raise ExecutionCancelled()

        # Perform screen capture based on scope
        try:
            if scope == "region":
                image, offset = capture.capture_region(reg_x, reg_y, reg_w, reg_h)
            elif scope == "ventana_activa":
                image, offset = capture.capture_active_window()
            else:
                image, offset = capture.capture_screen()
        except HandlerError:
            raise
        except Exception:
            raise HandlerError(ExecutionErrorCode.VISION_CAPTURE_FAILED) from None

        # Extract words from OCR
        boxes = engine.detect_words(image)

        # Match text against OCR boxes
        result = match_text_candidates(
            text,
            boxes,
            match_type=match_type,
            threshold=confidence_threshold,
            offset=offset,
            base_resolution=base_resolution,
            desktop_bounds=desktop_bounds,
        )

        if result is not None:
            return result.to_dict()

        if time.monotonic() >= deadline:
            break

        # Cooperative cancel-aware sleep
        if cancel_event.wait(poll_interval_ms / 1000.0):
            raise ExecutionCancelled()

    raise HandlerError(ExecutionErrorCode.VISION_ELEMENT_NOT_FOUND)
