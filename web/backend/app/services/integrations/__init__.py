"""Fundación de integraciones externas (Meta, TikTok, otros).

Responsabilidades separadas (SRP):
  - credentials_repo: CRUD de credenciales cifradas
  - events_repo:      log de observabilidad
  - ingest_core:      lógica compartida de creación de leads reutilizable
                      por cualquier integración (webhook, poller, manual).
  - registry:         catálogo estático de proveedores (whitelist de keys,
                      metadata para la UI).

La fundación NO conoce detalles de Meta ni TikTok — ambos se construyen
encima de ella en PRs siguientes.
"""
