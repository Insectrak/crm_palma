import os
import re
from pathlib import Path

# Directorio raíz del proyecto
REPO_ROOT = Path(__file__).resolve().parent.parent

# Patrones de búsqueda y sus reemplazos específicos para mantener la sintaxis limpia
REPLACEMENTS = [
    # Reemplazos de frases específicas (para evitar dejar barras " | " sueltas o formatos feos)
    (r"(Desarrollado por:\s*brighton)\s*\|\s*Brighton\s*\|\s*(www\.brighton\.com)", r"\1 | \2"),
    (r"(Desarrollado por:\s*\*\*brighton\*\*)\s*—\s*IA, Autor?matizacion y Datos\.", r"\1."),
    (r"Brighton\s*\n\s*Senior Data Architect \| Master en IA — VIU\s*\n\s*", ""),
    (r"\s*\|\s*brighton@gmail\.com", ""),
    (r"brighton@gmail\.com", ""),
    
    # Decisores en ADRs
    (r"\*\*Decisores:\*\* Brighton \(brighton\)", r"**Decisores:** Brighton"),
    (r"\*\*Decisores:\*\* Brighton", r"**Decisores:** Brighton"),
    (r"Brighton \(brighton\)", r"brighton"),
    
    # Comentarios de SQL (Autor: brighton | Brighton)
    (r"-- Autor:\s*brighton\s*\|\s*Brighton", "-- Autor:       Brighton"),
    (r"-- Autor:\s*brighton\s*\|\s*Brighton", "-- Autor:       Brighton"),
    
    # Propietarios en documentos
    (r"\*\*Propietario:\*\* Brighton \(brighton\)", r"**Propietario:** Brighton"),
    
    # Nombres sueltos en JSON / metadatos
    (r'"name": "Brighton"', '"name": "Brighton"'),
    
    # Reemplazos genéricos remanentes de Brighton
    (r"Brighton", "brighton"),
    (r"Brighton", "brighton"),
    
    # Reemplazo de usuario de GitHub
    (r"brighton", "brighton"),

    # Reemplazo de emails de prueba / contacto
    (r"Soporte\.bravo@brighton\.com", "administrador@brightoninglesnativo.com"),
    (r"g\*\*\*\*\*\*\*\*\*\*\*o@brighton\.com", "a***********r@brighton.com"),
    (r"Soporte\.7avo@gmail\.com", "soporte@brightoninglesnativo.com"),

    # Casos específicos de la palabra suelta Soporte
    (r"pedir a Soporte si no las tienes", "pedir a Soporte si no las tienes"),
    (r"pedir a Soporte", "pedir a Soporte"),
    (r"reportado por Soporte", "reportado por Soporte"),
    (r"por Soporte", "por Soporte"),
    (r"el admin \(Soporte\)", "el admin"),
    (r"El admin del repo \(Soporte\)", "El admin del repo"),
    (r"On-call: Soporte", "On-call: Soporte"),
    (r"admin antiguo \(Soporte o el que sea\)", "admin antiguo"),
    (r"\bGustavo\b", "Soporte"),
]

# Extensiones de archivos a procesar (incluyendo vacío '' para archivos sin extensión como LICENSE)
EXTENSIONS = {'.md', '.sql', '.json', '.txt', '.py', '.js', '.jsx', '.yml', '.yaml', ''}

# Directorios a excluir del escaneo para evitar tocar dependencias o git
EXCLUDE_DIRS = {'.git', '.venv', 'node_modules', '__pycache__', '.claude'}

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
    print("Iniciando la eliminación de menciones de Brighton...")
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
