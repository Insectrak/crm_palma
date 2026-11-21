#!/usr/bin/env python3
"""
change_admin_password.py - Cambia la contraseña de cualquier usuario en la base de datos de forma segura.
"""
import sys
import os
import bcrypt
import psycopg2
from pathlib import Path

# Cargar variables del archivo .env manualmente si no están en el entorno
def load_env():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

def main():
    load_env()
    
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("Error: No se encontró DATABASE_URL en el entorno ni en el archivo .env")
        sys.exit(1)
        
    print("--- Cambiar contraseña de usuario (CRM) ---")
    
    # 1. Pedir el correo (username) del usuario
    email = input("Introduce el email del usuario (ej. admin@local o tu correo): ").strip()
    if not email:
        print("Error: El email no puede estar vacío.")
        sys.exit(1)
        
    # 2. Pedir la nueva contraseña
    password = input("Introduce la NUEVA contraseña segura: ").strip()
    if len(password) < 6:
        print("Error: La contraseña debe tener al menos 6 caracteres por seguridad.")
        sys.exit(1)
        
    # 3. Hashear la contraseña con bcrypt
    print("Hasheando contraseña...")
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    # 4. Conectar a la base de datos y actualizar
    try:
        conn = psycopg2.connect(database_url)
        with conn.cursor() as cur:
            # Verificar si el usuario existe
            cur.execute("SELECT id, role FROM auth.users WHERE email = %s", (email,))
            user = cur.fetchone()
            
            if not user:
                print(f"Error: No se encontró ningún usuario con el email '{email}' en la base de datos.")
                conn.close()
                sys.exit(1)
                
            user_id, role = user
            print(f"Usuario encontrado (ID: {user_id}, Rol: {role}). Actualizando contraseña...")
            
            # Actualizar hash de contraseña
            cur.execute(
                "UPDATE auth.users SET password_hash = %s, updated_at = NOW() WHERE id = %s",
                (password_hash, user_id)
            )
            
            # Invalidar todas las sesiones activas del usuario para forzar re-login
            cur.execute(
                "UPDATE auth.user_sessions SET is_active = FALSE, updated_at = NOW() WHERE user_id = %s",
                (user_id,)
            )
            
        conn.commit()
        conn.close()
        print("\n[OK] ¡Contraseña actualizada con éxito!")
        print("Se han cerrado todas las sesiones activas del usuario. Deberá iniciar sesión con su nueva contraseña.")
        
    except Exception as e:
        print(f"\n[X] Error al conectar o actualizar en la base de datos: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
