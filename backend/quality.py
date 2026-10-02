"""Análisis determinista de calidad de imagen antes del OCR.

No intenta interpretar el documento. Solo decide si la captura tiene calidad
suficiente para que el OCR y las reglas posteriores sean fiables.
"""

from __future__ import annotations

from statistics import mean, pstdev

from .contracts import QualityReport


class LocalImageQualityAnalyzer:
    """Analizador local basado en Pillow y métricas reproducibles.

    Pillow es una dependencia opcional en desarrollo. Si todavía no está
    instalada, el pipeline informa de que la calidad no se puede verificar en
    vez de fingir que la imagen es válida.
    """

    name = "local-image-quality"

    def analyze(self, content: bytes, content_type: str, filename: str) -> QualityReport:
        if not content_type.startswith("image/"):
            return {
                "status": "not_applicable",
                "decision": "pass",
                "score": 1.0,
                "metrics": {"format": content_type or "unknown"},
                "reasons": [],
                "provider": self.name,
            }

        try:
            from PIL import Image, ImageChops, ImageFilter, ImageOps
        except ImportError:
            return {
                "status": "unavailable",
                "decision": "review",
                "score": 0.0,
                "metrics": {},
                "reasons": ["instala Pillow para activar la verificación de calidad de imagen"],
                "provider": self.name,
            }

        try:
            with Image.open(__import__("io").BytesIO(content)) as original:
                image = ImageOps.exif_transpose(original).convert("L")
                width, height = image.size
                if width <= 0 or height <= 0:
                    raise ValueError("dimensiones vacías")
                sample = image.copy()
                sample.thumbnail((900, 900))

                pixels = list(sample.getdata())
                brightness = mean(pixels)
                contrast = pstdev(pixels) if len(pixels) > 1 else 0.0
                edge_image = sample.filter(ImageFilter.FIND_EDGES)
                edge_pixels = list(edge_image.getdata())
                edge_mean = mean(edge_pixels) if edge_pixels else 0.0
                edge_spread = pstdev(edge_pixels) if len(edge_pixels) > 1 else 0.0

                # Una captura borrosa conserva menos variación de bordes. La
                # comparación con una versión ligeramente desenfocada evita
                # depender de una resolución concreta.
                blurred = sample.filter(ImageFilter.GaussianBlur(radius=1.5))
                detail_delta = ImageChops.difference(sample, blurred)
                detail_pixels = list(detail_delta.getdata())
                detail_mean = mean(detail_pixels) if detail_pixels else 0.0

                shadow_ratio = sum(pixel < 35 for pixel in pixels) / max(len(pixels), 1)
                glare_ratio = sum(pixel > 248 for pixel in pixels) / max(len(pixels), 1)
                dark_border_ratio = self._border_dark_ratio(sample)

                resolution_score = self._resolution_score(width, height)
                sharpness_score = min(1.0, (detail_mean / 18.0) * 0.7 + (edge_spread / 55.0) * 0.3)
                lighting_score = self._lighting_score(brightness, shadow_ratio, glare_ratio)
                contrast_score = min(1.0, max(0.0, contrast / 58.0))
                bounds_score = max(0.0, 1.0 - max(0.0, dark_border_ratio - 0.45) * 1.6)
                overall = round(
                    resolution_score * 0.2
                    + sharpness_score * 0.3
                    + lighting_score * 0.2
                    + contrast_score * 0.15
                    + bounds_score * 0.15,
                    3,
                )

                observed_reasons: list[str] = []
                if resolution_score < 0.55:
                    observed_reasons.append("resolución insuficiente")
                if sharpness_score < 0.42:
                    observed_reasons.append("imagen borrosa o desenfocada")
                if lighting_score < 0.55:
                    observed_reasons.append("iluminación insuficiente o irregular")
                if shadow_ratio > 0.22:
                    observed_reasons.append("sombras detectadas")
                # Un documento blanco suele tener muchos píxeles saturados. Solo
                # consideramos reflejo una saturación casi total combinada con
                # contraste muy bajo.
                if glare_ratio > 0.98 and contrast < 15:
                    observed_reasons.append("reflejos o zonas sobreexpuestas")
                if contrast_score < 0.35:
                    observed_reasons.append("contraste insuficiente")
                if bounds_score < 0.65:
                    observed_reasons.append("bordes del documento posiblemente recortados")

                # Los umbrales de aviso y bloqueo son deliberadamente distintos:
                # una sombra leve o un desenfoque moderado no deben impedir el
                # OCR si los campos obligatorios todavía se pueden interpretar.
                blocking_reasons: list[str] = []
                if resolution_score < 0.42:
                    blocking_reasons.append("resolución insuficiente")
                if sharpness_score < 0.25:
                    blocking_reasons.append("imagen borrosa o desenfocada")
                if lighting_score < 0.35:
                    blocking_reasons.append("iluminación insuficiente o irregular")
                if shadow_ratio > 0.45:
                    blocking_reasons.append("sombras detectadas")
                if glare_ratio > 0.98 and contrast < 15:
                    blocking_reasons.append("reflejos o zonas sobreexpuestas")
                if contrast_score < 0.20:
                    blocking_reasons.append("contraste insuficiente")
                if bounds_score < 0.45:
                    blocking_reasons.append("bordes del documento posiblemente recortados")
                if overall < 0.45:
                    blocking_reasons.append("calidad global de imagen insuficiente")

                # Conservamos los avisos para diagnóstico, pero solo los motivos
                # críticos bloquean el pipeline.
                blocking_reasons = list(dict.fromkeys(blocking_reasons))
                warnings = [reason for reason in observed_reasons if reason not in blocking_reasons]
                status = "good" if not blocking_reasons else "needs_review"
                return {
                    "status": status,
                    "decision": "pass" if status == "good" else "review",
                    "score": overall,
                    "metrics": {
                        "width": width,
                        "height": height,
                        "brightness": round(brightness, 2),
                        "contrast": round(contrast, 2),
                        "sharpness": round(sharpness_score, 3),
                        "lighting": round(lighting_score, 3),
                        "document_bounds": round(bounds_score, 3),
                        "shadow_ratio": round(shadow_ratio, 3),
                        "glare_ratio": round(glare_ratio, 3),
                    },
                    "reasons": blocking_reasons,
                    "warnings": warnings,
                    "blocking_reasons": blocking_reasons,
                    "provider": self.name,
                }
        except Exception as error:  # Pillow puede rechazar formatos o bytes truncados.
            return {
                "status": "unreadable",
                "decision": "review",
                "score": 0.0,
                "metrics": {},
                "reasons": [f"no se ha podido leer la imagen: {error}"],
                "provider": self.name,
            }

    @staticmethod
    def _resolution_score(width: int, height: int) -> float:
        pixels = width * height
        if pixels >= 2_000_000:
            return 1.0
        if pixels >= 1_000_000:
            return 0.82
        if pixels >= 500_000:
            return 0.62
        if pixels >= 250_000:
            return 0.42
        return 0.2

    @staticmethod
    def _lighting_score(brightness: float, shadow_ratio: float, glare_ratio: float) -> float:
        underexposure = max(0.0, 95.0 - brightness) / 95.0
        overexposure = max(0.0, brightness - 248.0) / 7.0
        exposure = max(0.0, 1.0 - min(0.85, underexposure * 0.9 + overexposure * 0.7))
        glare_penalty = 0.3 if glare_ratio > 0.98 and brightness > 248.0 else 0.0
        penalties = min(0.65, shadow_ratio * 1.4 + glare_penalty)
        return max(0.0, min(1.0, exposure * 0.75 + 0.25 - penalties))

    @staticmethod
    def _border_dark_ratio(image) -> float:
        width, height = image.size
        band_x = max(1, width // 30)
        band_y = max(1, height // 30)
        strips = []
        strips.extend(image.crop((0, 0, width, band_y)).getdata())
        strips.extend(image.crop((0, height - band_y, width, height)).getdata())
        strips.extend(image.crop((0, 0, band_x, height)).getdata())
        strips.extend(image.crop((width - band_x, 0, width, height)).getdata())
        return sum(pixel < 45 for pixel in strips) / max(len(strips), 1)
