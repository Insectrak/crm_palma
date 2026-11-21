import os
import re
from pathlib import Path

# Directorio raíz del proyecto
REPO_ROOT = Path(__file__).resolve().parent.parent

# Patrones de búsqueda y sus reemplazos específicos para eliminar Azoramind y Gustavo Bravo
REPLACEMENTS = [
    # 1. Frases combinadas de Azoramind y Gustavo
    (r"Desarrollado por:\s*Azoramind\s*\|\s*Gustavo Bravo\s*\|\s*www\.azoramind\.com", "Desarrollado por: Brighton | brightoninglesnativo.com"),
    (r"Desarrollado por:\s*\*\*Azoramind\*\*\s*—\s*IA, Autorización y Datos\.", "Desarrollado por: **Brighton**."),
    (r"Desarrollado por:\s*\*\*Azoramind\*\*\s*—\s*IA, Automatización y Datos\.", "Desarrollado por: **Brighton**."),
    (r"Gustavo Roger Bravo Esquivias\s*\n\s*Senior Data Architect \| Master en IA — VIU\s*\n\s*", ""),
    (r"Gustavo Roger Bravo Esquivias", "Brighton"),
    (r"Gustavo Bravo", "Brighton"),

    # 2. Correos electrónicos
    (r"gussbrav@gmail\.com", "soporte@brightoninglesnativo.com"),
    (r"gustavo\.bravo@azoramind\.com", "administrador@brightoninglesnativo.com"),
    (r"gustavo\.7avo@gmail\.com", "soporte@brightoninglesnativo.com"),
    (r"g\*\*\*\*\*\*\*\*\*\*\*o@azoramind\.com", "a***********r@brightoninglesnativo.com"),
    (r"soporte@azoramind\.com", "soporte@brightoninglesnativo.com"),
    (r"administrador@azoramind\.com", "administrador@brightoninglesnativo.com"),

    # 3. Decisores, Propietarios y Autores
    (r"\*\*Decisores:\*\* Gustavo Bravo \(Azoramind\)", "**Decisores:** Brighton"),
    (r"\*\*Decisores:\*\* Gustavo Bravo", "**Decisores:** Brighton"),
    (r"\*\*Decisores:\*\* Azoramind", "**Decisores:** Brighton"),
    (r"Gustavo Bravo \(Azoramind\)", "Brighton"),
    (r"\*\*Propietario:\*\* Gustavo Bravo \(Azoramind\)", "**Propietario:** Brighton"),
    (r"\*\*Propietario:\*\* Azoramind", "**Propietario:** Brighton"),
    (r"-- Autor:\s*Azoramind\s*\|\s*Gustavo Bravo", "-- Autor:       Brighton"),
    (r"-- Autor:\s*Azoramind", "-- Autor:       Brighton"),
    (r'"name": "Gustavo Bravo"', '"name": "Brighton"'),
    (r'"name": "Azoramind"', '"name": "Brighton"'),

    # 4. Referencias y Casos específicos de Gustavo (persona)
    (r"pedir a Gustavo si no las tienes", "pedir a Soporte si no las tienes"),
    (r"pedir a Gustavo", "pedir a Soporte"),
    (r"reportado por Gustavo", "reportado por Soporte"),
    (r"por Gustavo", "por Soporte"),
    (r"el admin \(Gustavo\)", "el admin"),
    (r"El admin del repo \(Gustavo\)", "El admin del repo"),
    (r"On-call: Gustavo", "On-call: Soporte"),
    (r"admin antiguo \(Gustavo o el que sea\)", "admin antiguo"),
    (r"\bGustavo\b", "Soporte"),

    # 5. Reemplazos de marca general Azoramind
    (r"azoramind-crm-azoramind", "brighton-crm-brighton"),
    (r"azoramind_postgres", "brighton_postgres"),
    (r"azoramind_crm", "brighton_crm"),
    (r"azoramind_n8n", "brighton_n8n"),
    (r"azoramind_ocr-api", "brighton_ocr-api"),
    (r"azoramind_ollama", "brighton_ollama"),
    (r"azoramind_dev", "brighton_dev"),
    (r"azoramind_cert", "brighton_cert"),
    (r"azoramind_pdf", "brighton_pdf"),
    (r"azoramind", "brighton"),
    (r"Azoramind", "Brighton"),
    (r"gussbrav", "brighton"),
    (r"www\.azoramind\.com", "brightoninglesnativo.com"),
    (r"azoramind\.com", "brightoninglesnativo.com"),
]

# Extensiones de archivos a procesar (incluyendo vacío '' para archivos sin extensión como LICENSE)
EXTENSIONS = {'.md', '.sql', '.json', '.txt', '.py', '.js', '.jsx', '.yml', '.yaml', ''}

# Directorios a excluir (solo dependencias pesadas y git)
EXCLUDE_DIRS = {'.git', '.venv', 'node_modules', '__pycache__'}

def scrub_file(file_path: Path) -> bool:
    try:
        content = file_path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        try:
            content = file_path.read_text(encoding='latin-1')
        except Exception:
            return False
    except Exception:
        return False

    modified_content = content
    for pattern, replacement in REPLACEMENTS:
        modified_content = re.sub(pattern, replacement, modified_content, flags=re.IGNORECASE)

    if modified_content != content:
        try:
            file_path.write_text(modified_content, encoding='utf-8')
            return True
        except Exception as e:
            print(f"Error escribiendo en {file_path}: {e}")
            return False
    return False

def main():
    print("Iniciando la eliminación de menciones de Azoramind y Gustavo...")
    modified_count = 0
    total_scanned = 0

    for root, dirs, files in os.walk(REPO_ROOT):
        # Filtrar directorios excluidos
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        
        for file in files:
            file_path = Path(root) / file
            
            # Ignorar este propio script de limpieza
            if file_path == Path(__file__).resolve():
                continue
                
            if file_path.suffix in EXTENSIONS:
                total_scanned += 1
                if scrub_file(file_path):
                    print(f"[MODIFICADO] {file_path.relative_to(REPO_ROOT)}")
                    modified_count += 1

    print("\n============================================================")
    print("  PROCESO COMPLETADO")
    print("============================================================")
    print(f"Archivos escaneados:   {total_scanned}")
    print(f"Archivos modificados:  {modified_count}")
    print("============================================================\n")

if __name__ == "__main__":
    main()
