from __future__ import annotations
from app.config import get_settings


def configure_telemetry(app):
    """Configure OpenTelemetry when enabled; no-op in local/offline mode."""
    s=get_settings()
    if not s.otel_enabled: return {'enabled':False}
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        resource=Resource.create({'service.name':s.otel_service_name,'deployment.environment':s.app_env,'service.version':'7.0.1'})
        provider=TracerProvider(resource=resource)
        if s.otel_exporter_otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=s.otel_exporter_otlp_endpoint)))
        trace.set_tracer_provider(provider); FastAPIInstrumentor.instrument_app(app,tracer_provider=provider)
        return {'enabled':True,'service':s.otel_service_name,'exporter':bool(s.otel_exporter_otlp_endpoint)}
    except Exception as e:
        if s.is_production: raise RuntimeError(f'OpenTelemetry initialization failed: {e}') from e
        return {'enabled':False,'error':str(e)}
