import os
import re
from pathlib import Path

# Directorio raíz del proyecto
REPO_ROOT = Path(__file__).resolve().parent.parent

# Reemplazos específicos (ordenados de más específicos a más generales)
REPLACEMENTS = [
    # 1. Dominios, correos y URLs
    (r"www\.brighton\.com", "www.example.com"),
    (r"Soporte\.bravo@brighton\.com", "admin@crm.local"),
    (r"administrador@brighton\.com", "admin@crm.local"),
    (r"soporte@brighton\.com", "soporte@crm.local"),
    (r"g\*\*\*\*\*\*\*\*\*\*\*o@brighton\.com", "a***********r@crm.local"),
    (r"a\*\*\*\*\*\*\*\*\*\*\*r@brighton\.com", "a***********r@crm.local"),
    (r"glitchtip\.brighton\.com", "glitchtip.crm.local"),
    (r"brighton\.com", "crm.local"),
    (r"https://brighton-crm-brighton\.l7weu8\.easypanel\.host", "https://crm.local"),
    
    # 2. Contenedores, puertos y nombres de redes en Docker/Config
    (r"brighton_ollama", "crm_ollama"),
    (r"brighton-crm-backend-cert", "crm-backend-cert"),
    (r"brighton-crm-frontend-cert", "crm-frontend-cert"),
    (r"brighton-crm-backend", "crm-backend"),
    (r"brighton-crm-frontend", "crm-frontend"),
    (r"brighton-crm-cert-net", "crm-cert-net"),
    (r"brighton_crm-brighton", "crm-backend"),
    (r"brightonCRM-Webhook", "CRM-Webhook"),
    (r"brighton_crm_dev", "crm_db_dev"),
    (r"brighton_crm", "crm_db"),
    (r"brightondev_1234", "CRMdev_Pass123"),
    (r"brighton_1234", "CRM_Pass123"),

    # 3. Nombres de proyectos y marcas comerciales
    (r"brighton CRM", "Plataforma CRM"),
    (r"brighton — Plataforma de gestión de leads", "Plataforma CRM — Gestión de leads"),
    (r"brighton v3\.0", "CRM v3.0"),
    (r"brighton", "Mi CRM"),
    (r"brighton", "crm"),
]

# Extensiones de archivos a sugerir (incluyendo vacío '' para archivos sin extensión)
EXTENSIONS = {'.md', '.sql', '.json', '.txt', '.py', '.js', '.jsx', '.yml', '.yaml', '.conf', '.svg', '.html', ''}

# Directorios a excluir del escaneo
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
        # Reemplazar respetando mayúsculas/minúsculas o usando regex
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
    print("Iniciando la eliminación de menciones de brighton...")
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
