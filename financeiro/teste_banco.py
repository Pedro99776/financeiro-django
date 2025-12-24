import psycopg2

print("Tentando conectar e forçando resposta em UTF-8...")

try:
    # Adicionamos 'options' para forçar o encoding correto
    conn = psycopg2.connect(
        dbname="financeiro_db",
        user="postgres",
        password="1234",  # <--- COLOQUE SUA SENHA NUMÉRICA AQUI
        host="localhost",
        port="5432",
        options="-c client_encoding=UTF8"
    )
    print("✅ SUCESSO! Conexão realizada.")
    conn.close()

except Exception as e:
    print("\n❌ A CONEXÃO FALHOU. VEJA O MOTIVO ABAIXO:")
    # Usamos repr() para mostrar o erro 'cru' sem tentar formatar, evitando o travamento
    print(repr(e))