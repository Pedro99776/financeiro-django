import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

# Pega credenciais do .env
host = os.getenv('DB_HOST')
user = os.getenv('DB_USER')
password = os.getenv('DB_PASSWORD')
database = os.getenv('DB_NAME', 'postgres')

print("🔍 Testando conexão com Supabase...")
print(f"Host: {host}")
print(f"User: {user}")
print(f"Database: {database}")
print(f"Senha: {'***' if password else 'NÃO ENCONTRADA'}")
print()

try:
    conn = psycopg2.connect(
        host=host,
        user=user,
        password=password,
        database=database,
        connect_timeout=10
    )
    print("✅ CONEXÃO BEM-SUCEDIDA!")

    cursor = conn.cursor()
    cursor.execute("SELECT version();")
    version = cursor.fetchone()
    print(f"✅ PostgreSQL Version: {version[0]}")

    cursor.close()
    conn.close()

except psycopg2.OperationalError as e:
    print("❌ ERRO DE CONEXÃO:")
    print(str(e))
    print()
    print("🔧 Possíveis causas:")
    print("1. Projeto pausado no Supabase (free tier)")
    print("2. Firewall/antivírus bloqueando")
    print("3. Credenciais incorretas")
    print("4. VPN ativa bloqueando")
except Exception as e:
    print(f"❌ ERRO INESPERADO: {e}")