"""Estimación local del consumo del pipeline AWS.

Durante la fase local no se llama a AWS. Este módulo expone el contrato de
telemetría que usará el adaptador AWS y calcula una previsión equivalente a
partir de los documentos procesados, sin contar Cognito.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Iterable

from .pricing import annotate_event, pricing_config, sum_token_cost


def _event(
    document_id: str,
    created_at: str,
    service: str,
    operation: str,
    *,
    requests: int = 1,
    pages: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    state_transitions: int = 0,
    messages: int = 0,
) -> dict[str, object]:
    return {
        "id": f"EST-{document_id}-{service.lower()}-{operation.lower().replace(' ', '-')}",
        "document_id": document_id,
        "created_at": created_at,
        "service": service,
        "operation": operation,
        "mode": "estimate",
        "requests": requests,
        "pages": pages,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "state_transitions": state_transitions,
        "messages": messages,
    }


def _sum_metrics(events: Iterable[dict[str, object]]) -> dict[str, int]:
    totals = defaultdict(int)
    for event in events:
        for key in ("requests", "pages", "input_tokens", "output_tokens", "state_transitions", "messages"):
            totals[key] += int(event.get(key, 0) or 0)
    return dict(totals)


def build_usage_snapshot(records: list[dict[str, object]], provider: str = "local") -> dict[str, object]:
    """Devuelve el consumo observado y la previsión equivalente del flujo AWS."""
    events: list[dict[str, object]] = []
    for record in records:
        document_id = str(record.get("id", "documento"))
        created_at = str(record.get("created_at", datetime.now(UTC).isoformat()))
        status = str(record.get("status", ""))

        pages_count = max(1, int(record.get("pages_count", 1) or 1))
        source_keys = record.get("source_object_keys")
        evidence_requests = len(source_keys) if isinstance(source_keys, list) and source_keys else pages_count

        # Evidencia y metadatos: entrada + registro de resultado y, si procede,
        # copia para el cliente. Son peticiones S3 equivalentes, no llamadas reales
        # mientras DOCUMENT_AI_PROVIDER=local.
        events.append(_event(document_id, created_at, "S3", "PutObject · evidencia", requests=evidence_requests))
        events.append(_event(document_id, created_at, "S3", "PutObject · metadatos"))
        if status == "sent_to_erp":
            events.append(_event(document_id, created_at, "S3", "PutObject · copia cliente"))

        # Un PDF/XML nativo se lee sin OCR ni Bedrock. Para imágenes o PDFs
        # escaneados estimamos una lectura multimodal y un contraste Textract por
        # página, igual que el runtime AWS.
        native_reading = record.get("native_reading")
        is_native = isinstance(native_reading, dict) and bool(native_reading.get("is_native"))
        if not is_native:
            events.append(_event(document_id, created_at, "Bedrock", "Invoke · lectura multimodal", input_tokens=1200, output_tokens=600))
            events.append(_event(document_id, created_at, "Textract", "AnalyzeDocument · contraste", requests=pages_count, pages=pages_count))

        if status == "sent_to_erp":
            events.append(_event(document_id, created_at, "Step Functions", "StartExecution · pipeline", state_transitions=6))
            email_delivery = record.get("email_delivery")
            if isinstance(email_delivery, dict) and email_delivery.get("status") == "simulated":
                events.append(_event(document_id, created_at, "SES", "SendEmail · copia cliente", messages=1))

    events = [annotate_event(event) for event in events]
    service_totals: dict[str, dict[str, object]] = {}
    for event in events:
        service = str(event["service"])
        service_totals.setdefault(service, {"service": service, "requests": 0, "pages": 0, "input_tokens": 0, "output_tokens": 0, "state_transitions": 0, "messages": 0, "token_cost_eur": 0.0})
        current = service_totals[service]
        for key in ("requests", "pages", "input_tokens", "output_tokens", "state_transitions", "messages"):
            current[key] = int(current[key]) + int(event.get(key, 0) or 0)
        current["token_cost_eur"] = round(float(current["token_cost_eur"]) + float(event.get("token_cost_eur", 0) or 0), 8)

    estimated = _sum_metrics(events)
    actual = {key: 0 for key in estimated}
    aws_connected = provider == "aws"
    estimated_token_cost_eur = sum_token_cost(events)
    return {
        "provider": provider,
        "aws_connected": aws_connected,
        "cognito_excluded": True,
        "notice": (
            "Las peticiones reales a AWS se mostrarán aquí cuando se active el adaptador AWS."
            if aws_connected
            else "Modo local: no se ha realizado ninguna petición AWS. Los datos mostrados son una estimación equivalente del flujo futuro."
        ),
        "summary": {
            "documents": len(records),
            "actual": actual,
            "estimated": estimated,
            "actual_token_cost_eur": 0.0,
            "estimated_token_cost_eur": estimated_token_cost_eur,
        },
        "pricing": pricing_config(),
        "services": list(service_totals.values()),
        "events": list(reversed(events)),
    }
