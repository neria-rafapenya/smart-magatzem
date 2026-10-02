"""Estimación de coste del consumo tokenizado de Bedrock.

Los precios son configurables porque AWS puede cambiarlos y dependen del modelo.
Los valores por defecto corresponden a Amazon Nova Lite estándar y son una
aproximación, no una factura de AWS.
"""

from __future__ import annotations

import os
from collections.abc import Iterable


DEFAULT_INPUT_USD_PER_MILLION = 0.06
DEFAULT_OUTPUT_USD_PER_MILLION = 0.24
DEFAULT_USD_TO_EUR = 0.92


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value >= 0 else default


def pricing_config() -> dict[str, object]:
    return {
        "currency": "EUR",
        "model_id": os.getenv("BEDROCK_MODEL_ID", "eu.amazon.nova-lite-v1:0"),
        "usd_to_eur": _env_float("USD_TO_EUR_RATE", DEFAULT_USD_TO_EUR),
        "input_usd_per_million": _env_float("BEDROCK_INPUT_USD_PER_MILLION", DEFAULT_INPUT_USD_PER_MILLION),
        "output_usd_per_million": _env_float("BEDROCK_OUTPUT_USD_PER_MILLION", DEFAULT_OUTPUT_USD_PER_MILLION),
        "basis": "Amazon Nova Lite estándar; importe aproximado",
    }


def token_cost_eur(input_tokens: int | float, output_tokens: int | float) -> float:
    config = pricing_config()
    usd = (
        float(input_tokens) / 1_000_000 * float(config["input_usd_per_million"])
        + float(output_tokens) / 1_000_000 * float(config["output_usd_per_million"])
    )
    return round(usd * float(config["usd_to_eur"]), 8)


def annotate_event(event: dict[str, object]) -> dict[str, object]:
    annotated = dict(event)
    annotated["token_cost_eur"] = token_cost_eur(
        int(event.get("input_tokens", 0) or 0),
        int(event.get("output_tokens", 0) or 0),
    )
    return annotated


def sum_token_cost(events: Iterable[dict[str, object]]) -> float:
    return round(sum(float(annotate_event(event)["token_cost_eur"]) for event in events), 8)
