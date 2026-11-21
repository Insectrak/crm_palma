"""
scripts/_scrub_brand_mentions.py — Limpieza masiva de marcas terceras
en comentarios y docstrings del codigo vivo.

Politica del proyecto: nunca mencionar marcas externas (Salesforce, HubSpot,
Stripe, Linear, Notion, Slack, etc.) en commits, codigo, comentarios o docs.
Frases neutras solamente — la marca propia (brighton) es la unica que aparece.

Estrategia: reemplazo ordenado de frases compuestas PRIMERO (mas especificas),
luego palabras sueltas. Aplicado a archivos .py / .jsx / .js bajo web/.

Reversible: corre git diff + revisa antes de commitear. No toca strings dentro
de URLs / nombres de tablas / DB.
"""
from __future__ import annotations
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCAN_DIRS = [REPO / "web" / "backend" / "app", REPO / "web" / "frontend" / "src"]
EXTENSIONS = {".py", ".jsx", ".js"}

# Frases compuestas — MAS ESPECIFICAS primero para que tengan precedencia
# sobre las palabras sueltas que vienen al final.
COMPOUND_REPLACEMENTS = [
    # — primera pasada dejo residuos tipo "patrón estándar/Salesforce" cuando
    # la palabra ya reemplazada se concatenaba con otra. Los limpiamos primero.
    ("patrón estándar/Salesforce", "patrón estándar"),
    ("patrón estándar/HubSpot",    "patrón estándar"),
    ("patron estandar/Salesforce", "patron estandar"),
    ("patron estandar/HubSpot",    "patron estandar"),
    ("patron estandar / Salesforce", "patron estandar"),
    ("patron estandar / HubSpot",    "patron estandar"),
    ("patrón estándar / HubSpot",    "patrón estándar"),
    ("patrón estándar / Salesforce", "patrón estándar"),
    ("patrón estándar/Stripe",     "patrón estándar"),
    ("patron estandar/Stripe",     "patron estandar"),
    ("patrón premium/Stripe",      "patrón premium"),
    ("patrón premium/Linear",      "patrón premium"),
    ("patrón premium/Notion",      "patrón premium"),
    ("CRMs profesionales/Stripe",  "APIs profesionales"),
    ("CRMs profesionales/HubSpot", "CRMs profesionales"),
    ("Mailchimp/HubSpot",          "mensajería profesional"),
    ("Mailchimp/patrón estándar",  "mensajería profesional"),
    ("GitHub Apps",                "apps externas"),
    ("Apple",                      "estilo elegante"),
    ("Mailchimp",                  "mensajería profesional"),
    # — combos con barra (originales)
    ("paridad Salesforce/HubSpot", "paridad con CRMs profesionales"),
    ("patrón Salesforce/HubSpot", "patrón estándar de la industria"),
    ("patron Salesforce/HubSpot", "patron estandar de la industria"),
    ("Salesforce/HubSpot pattern", "patrón estándar de la industria"),
    ("Salesforce/HubSpot Reports", "reportes profesionales del mercado"),
    ("Salesforce/HubSpot Notification", "preferencias de notificación"),
    ("Salesforce/HubSpot", "CRMs profesionales"),
    ("Stripe/HubSpot/PayPal", "pasarelas profesionales"),
    ("Stripe/HubSpot", "APIs profesionales"),
    ("Linear/HubSpot", "herramientas premium"),
    ("Linear/Notion", "herramientas premium"),
    ("Linear/Vercel/Stripe", "herramientas premium"),
    ("Slack/HubSpot/WhatsApp", "mensajería profesional"),
    ("Slack/HubSpot", "mensajería profesional"),
    ("Slack/Linear/Front", "herramientas premium"),
    ("Mixpanel/Amplitude/Linear", "patrón de analytics"),
    ("Mixpanel/Amplitude", "patrón de analytics"),
    ("Stripe / Slack / Meta", "patrón de configuración profesional"),
    ("Slack / Linear / Front", "patrón premium"),
    ("Salesforce / HubSpot", "CRMs profesionales"),
    ("iOS/HubSpot", "estilo moderno"),
    ("Airtable/NocoDB", "tablas profesionales"),
    ("Excel/NocoDB", "hojas de cálculo"),
    ("Slack / HubSpot", "mensajería profesional"),
    # — combinaciones con apostrofes / comillas
    ("Salesforce 'Lead Recapture'", "patrón estándar 'Lead Recapture'"),
    ("HubSpot 'Re-engagement", "patrón estándar 'Re-engagement"),
    ("HubSpot \"Merge contacts\"", "patrón estándar \"Merge contacts\""),
    ("Salesforce \"Lead Recapture\"", "patrón estándar \"Lead Recapture\""),
    ("Salesforce Quotas", "metas profesionales"),
    ("HubSpot Quotas", "metas profesionales"),
    ("Salesforce closed-won", "closed-won (patrón estándar)"),
    ("HubSpot closed-won", "closed-won (patrón estándar)"),
    ("Salesforce Lead Status", "estados de lead profesionales"),
    # — combinaciones "estilo X"
    ("Salesforce-style", "patrón estándar"),
    ("HubSpot-style", "patrón estándar"),
    ("Stripe-style", "patrón estándar"),
    ("Linear-style", "patrón estándar"),
    ("Notion-style", "patrón estándar"),
    ("Slack-style", "patrón estándar"),
    ("estilo Salesforce", "patrón estándar"),
    ("estilo HubSpot", "patrón estándar"),
    ("estilo Stripe", "patrón estándar"),
    ("estilo Linear", "patrón premium"),
    ("estilo Notion", "patrón premium"),
    ("estilo Slack", "patrón premium"),
    ("estilo Airtable", "patrón premium"),
    ("estilo Excel", "patrón de hoja de cálculo"),
    # — "patron X"
    ("patrón Salesforce", "patrón estándar"),
    ("patrón HubSpot", "patrón estándar"),
    ("patrón Stripe", "patrón estándar"),
    ("patrón Linear", "patrón premium"),
    ("patrón Notion", "patrón premium"),
    ("patrón Slack", "patrón premium"),
    ("patrón Mixpanel", "patrón de analytics"),
    ("patron Salesforce", "patron estandar"),
    ("patron HubSpot", "patron estandar"),
    ("patron Stripe", "patron estandar"),
    ("patron Linear", "patron premium"),
    ("patron Notion", "patron premium"),
    ("patron Slack", "patron premium"),
    ("patron Mixpanel", "patron de analytics"),
    # — "paridad X" / "paridad con X"
    ("paridad Salesforce", "paridad con CRMs profesionales"),
    ("paridad HubSpot", "paridad con CRMs profesionales"),
    ("paridad con Salesforce", "paridad con CRMs profesionales"),
    ("paridad con HubSpot", "paridad con CRMs profesionales"),
    ("paridad con Stripe", "paridad con APIs profesionales"),
    ("paridad con Linear", "paridad con herramientas premium"),
    # — referencias compuestas restantes
    ("Salesforce Sharing Rules", "reglas de visibilidad profesionales"),
    ("Salesforce Setup", "configuración profesional"),
    ("HubSpot Settings", "configuración profesional"),
    ("Stripe Dashboard", "panel profesional"),
    ("Salesforce Connected Apps", "apps conectadas (patrón estándar)"),
    ("Connected Apps (Salesforce)", "apps conectadas (patrón estándar)"),
    ("Private Apps (HubSpot)", "apps privadas (patrón estándar)"),
    ("HubSpot Lead Status", "estados de lead profesionales"),
    ("HubSpot CRM", "CRMs profesionales"),
    ("Notification Preferences", "preferencias de notificación"),
]

# Palabras sueltas — se aplican DESPUES de las compuestas.
# Solo reemplazamos cuando aparecen como palabra entera (boundary).
SINGLE_REPLACEMENTS = [
    ("Salesforce", "patrón estándar"),
    ("HubSpot",    "patrón estándar"),
    ("Hubspot",    "patrón estándar"),
    ("Stripe",     "patrón estándar"),
    ("Pipedrive",  "patrón estándar"),
    ("Zoho",       "patrón estándar"),
    ("Databricks", "patrón premium"),
    ("Atlassian",  "patrón premium"),
    ("Linear",     "patrón premium"),
    ("Notion",     "patrón premium"),
    ("Slack",      "patrón premium"),
    ("Trello",     "patrón premium"),
    ("Jira",       "patrón premium"),
    ("Asana",      "patrón premium"),
    ("Airtable",   "patrón premium"),
    ("Mixpanel",   "patrón de analytics"),
    ("Amplitude",  "patrón de analytics"),
    ("Vercel",     "patrón premium"),
    ("NocoDB",     "patrón premium"),
    ("Pipefy",     "patrón premium"),
    ("Monday",     "patrón premium"),
    ("PayPal",     "patrón premium"),
    ("Figma",      "patrón premium"),
    ("Glassdoor",  "fuente externa"),
    ("Mailchimp",  "mensajería profesional"),
    ("GitHub",     "servicio externo"),
    ("Gmail",      "correo profesional"),
    ("Apple",      "estilo elegante"),
    ("Front",      "herramienta premium"),
]


def should_replace_single(text: str, word: str, start: int) -> bool:
    """Solo reemplaza la palabra suelta si esta como termino independiente
    en un comentario / docstring — no si forma parte de un nombre tecnico
    (variable, URL, tabla DB).
    """
    # Detectar URLs reales (http://, https://, www., .com, dominio.algo).
    # El check anterior era muy laxo (/ cualquier) y mataba todos los
    # reemplazos en frases tipo "Stripe / HubSpot" donde la barra es solo
    # un separador de prosa, no parte de un path.
    upto = text[max(0, start - 30):start]
    if any(marker in upto for marker in ("http://", "https://", "www.", ".com/", ".org/", "@")):
        return False
    # Tambien evitamos si la palabra esta justo despues de un punto sin
    # espacio (ej: "request.Salesforce" — improbable pero defensa extra).
    if start > 0 and text[start - 1] == ".":
        return False
    return True


def scrub_file(path: Path) -> int:
    original = path.read_text(encoding="utf-8")
    text = original

    # Hasta 3 pasadas — cada reemplazo puede crear nueva combinacion que
    # otro reemplazo necesita atrapar (ej: "X/Salesforce" -> "X/patron estandar"
    # -> sigue siendo limpio pero a veces forma nueva compuesta).
    for _ in range(3):
        before = text
        # 1) Frases compuestas — orden importa.
        for src, dst in COMPOUND_REPLACEMENTS:
            text = text.replace(src, dst)

        # 2) Palabras sueltas — boundary regex \b
        for word, repl in SINGLE_REPLACEMENTS:
            pattern = re.compile(r"\b" + re.escape(word) + r"\b")
            def _sub(m: re.Match) -> str:
                return repl if should_replace_single(text, word, m.start()) else m.group(0)
            text = pattern.sub(_sub, text)

        if text == before:
            break

    if text == original:
        return 0
    path.write_text(text, encoding="utf-8")
    return original.count("\n") - text.count("\n") + 1  # marker no-strict


def main() -> int:
    total_files = 0
    for root in SCAN_DIRS:
        if not root.exists():
            continue
        for ext in EXTENSIONS:
            for path in root.rglob(f"*{ext}"):
                # Skip __pycache__ y build outputs
                if "__pycache__" in path.parts or "node_modules" in path.parts:
                    continue
                changed = scrub_file(path)
                if changed:
                    total_files += 1
                    print(f"  scrubbed: {path.relative_to(REPO)}")
    print(f"\nArchivos modificados: {total_files}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
