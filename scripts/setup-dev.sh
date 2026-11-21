#!/usr/bin/env bash
# ===========================================================================
# scripts/setup-dev.sh — Setup de hooks de Git para desarrolladores
# ===========================================================================
# Configura tu copia local del repo para usar los hooks versionados en
# .githooks/ (incluye pre-push estratificado).
#
# Ejecucion (una sola vez al clonar el repo):
#   bash scripts/setup-dev.sh
#
# Que hace:
#   1. Apunta git al directorio .githooks (en lugar de .git/hooks)
#   2. Marca los hooks como ejecutables
#   3. Verifica que tu entorno tiene ruff + pytest instalados
#
# Para desactivar despues:
#   git config --unset core.hooksPath
# ===========================================================================

set -e

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
    echo "✗ Error: ejecuta este script desde dentro del repo."
    exit 1
fi

cd "$REPO_ROOT"

echo "→ Configurando git para usar .githooks/…"
git config core.hooksPath .githooks

echo "→ Marcando hooks como ejecutables…"
chmod +x .githooks/* 2>/dev/null || true

echo "→ Verificando entorno Python…"
if ! command -v ruff &>/dev/null; then
    echo "  ⚠ ruff no encontrado. Instala con: pip install ruff"
fi
if ! command -v pytest &>/dev/null; then
    echo "  ⚠ pytest no encontrado. Instala con: pip install pytest"
fi

echo
echo "✓ Hooks activados. A partir de ahora:"
echo "  - push a feature/*  → solo ruff (rapido)"
echo "  - push a main        → ruff + pytest completo (~8 min)"
echo "  - escape hatch       → git push --no-verify"
echo
echo "Doc: docs/runbooks/pre-push-hook.md"
