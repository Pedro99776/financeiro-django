import os
import requests
from datetime import datetime


# URL base do microsserviço "PDF to MD" (Hugging Face Spaces)
# A URL pública do HF Spaces usa o formato: https://owner-space-name.hf.space
PDF_TO_MD_API_URL = os.getenv(
    'PDF_TO_MD_API_URL',
    'https://pedro-branco-api-extrato-bancario.hf.space'
)

# Chave de autenticação do microsserviço (opcional — se vazia, autenticação é desabilitada no servidor)
PDF_TO_MD_API_KEY = os.getenv('PDF_TO_MD_API_KEY', '')


def importar_extrato_via_microsservico(arquivo_upload, categorias_disponiveis: list) -> list:
    """
    Envia o arquivo de extrato (PDF ou CSV) ao microsserviço "PDF to MD" e
    retorna a lista de transações já estruturadas e categorizadas.

    O microsserviço se encarrega de:
    - Extrair o texto do PDF/CSV via MarkItDown
    - Parsear as transações
    - Categorizar via Zero-Shot Classification (sem IA da Gemini)

    Retorno esperado (lista de dicts):
    [
        {
            "data": "YYYY-MM-DD",
            "descricao": "Descrição limpa",
            "valor": 150.00,       # float positivo
            "tipo": "D",           # "D" (Débito) ou "R" (Receita/Crédito)
            "categoria": "Alimentação"
        },
        ...
    ]

    Lança Exception em caso de falha de comunicação ou resposta inválida.
    """
    endpoint = f"{PDF_TO_MD_API_URL.rstrip('/')}/api/v1/extract-markdown"

    headers = {}
    if PDF_TO_MD_API_KEY:
        headers['X-API-Key'] = PDF_TO_MD_API_KEY

    # Prepara as categorias como string separada por vírgula
    categories_str = ','.join(categorias_disponiveis)

    # Lê o conteúdo do arquivo (InMemoryUploadedFile ou arquivo com .chunks())
    if hasattr(arquivo_upload, 'read'):
        arquivo_upload.seek(0)
        file_content = arquivo_upload.read()
    else:
        with open(arquivo_upload, 'rb') as f:
            file_content = f.read()

    filename = getattr(arquivo_upload, 'name', 'extrato.pdf')

    # Determina o MIME type pelo nome do arquivo
    ext = os.path.splitext(filename)[1].lower()
    mime_map = {
        '.pdf': 'application/pdf',
        '.csv': 'text/csv',
        '.txt': 'text/plain',
    }
    mime_type = mime_map.get(ext, 'application/octet-stream')

    print(f"--- Enviando '{filename}' ao microsserviço: {endpoint} ---")

    try:
        response = requests.post(
            endpoint,
            headers=headers,
            files={'file': (filename, file_content, mime_type)},
            data={'categories': categories_str},
            timeout=120,  # 2 minutos — o microsserviço pode demorar para carregar o modelo
        )
    except requests.exceptions.ConnectionError:
        raise Exception(
            f"Não foi possível conectar ao microsserviço ({PDF_TO_MD_API_URL}). "
            "Verifique se o Space está ativo no Hugging Face."
        )
    except requests.exceptions.Timeout:
        raise Exception(
            "O microsserviço demorou demais para responder (timeout de 120s). "
            "O Space pode estar inicializando — tente novamente em alguns segundos."
        )

    # Erros HTTP
    if response.status_code == 403:
        raise Exception("API Key inválida ou ausente. Verifique PDF_TO_MD_API_KEY no .env.")
    elif response.status_code == 415:
        raise Exception(
            f"Formato de arquivo não suportado pelo microsserviço. "
            "Apenas PDF e CSV são aceitos."
        )
    elif response.status_code == 413:
        raise Exception("Arquivo muito grande (limite: 10MB).")
    elif response.status_code != 200:
        raise Exception(
            f"Erro do microsserviço (HTTP {response.status_code}): {response.text[:300]}"
        )

    # Parse da resposta JSON
    try:
        data = response.json()
    except Exception:
        raise Exception(f"Resposta inválida do microsserviço (não é JSON): {response.text[:300]}")

    if data.get('status') != 'success':
        raise Exception(f"Microsserviço retornou status de erro: {data}")

    transactions_raw = data.get('transactions', [])

    if not transactions_raw:
        print("⚠️  Microsserviço não encontrou transações no arquivo.")
        return []

    # Valida e normaliza cada transação retornada
    transacoes = []
    for item in transactions_raw:
        try:
            if not all(k in item for k in ['data', 'descricao', 'valor', 'tipo']):
                print(f"⚠️  Item ignorado (campos faltando): {item}")
                continue

            # Garante formato ISO de data
            data_str = item['data']
            datetime.strptime(data_str, '%Y-%m-%d')  # valida, não converte

            transacoes.append({
                'data': data_str,
                'descricao': item['descricao'],
                'valor': float(item['valor']),
                'tipo': item['tipo'],
                'categoria': item.get('categoria', 'Importados'),
            })
        except ValueError as ve:
            print(f"⚠️  Data inválida em item ignorado: {item} — {ve}")
            continue
        except Exception as e:
            print(f"⚠️  Erro ao processar item: {item} — {e}")
            continue

    print(f"✅  Total de transações recebidas do microsserviço: {len(transacoes)}")
    return transacoes