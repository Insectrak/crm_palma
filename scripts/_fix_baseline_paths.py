"""Normaliza los paths del .secrets.baseline a forward slashes simples.

Causado por baseline generado desde Windows que mete backslashes (que JSON
escapa como \\\\) y CI en Linux los detecta como diff cada vez que corre.
Este script se corre UNA vez y normaliza el archivo. Despues commitearlo.
"""
import json
import re

with open(".secrets.baseline", "r", encoding="utf-8") as f:
    data = json.load(f)

BACKSLASH = chr(92)  # \


def norm(p: str) -> str:
    s = p.replace(BACKSLASH, "/")
    s = re.sub(r"/+", "/", s)
    return s


fixed = {}
for path, findings in data.get("results", {}).items():
    np = norm(path)
    for entry in findings:
        if "filename" in entry:
            entry["filename"] = norm(entry["filename"])
    fixed[np] = findings
data["results"] = fixed

with open(".secrets.baseline", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

print("OK — paths normalizados")
