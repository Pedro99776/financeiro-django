from google import genai
from google.genai import types
import os
import json
import tempfile
from datetime import datetime


def importar_extrato_com_ia(arquivo_upload, categorias_disponiveis):
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        print("ERRO: Chave API não encontrada.")
        return []

    # --- CONFIGURAÇÃO CLI DO NOVO SDK ---
    client = genai.Client(api_key=api_key)

    nome_modelo = 'gemini-2.5-flash' # Atualizado para o modelo mais recente compatível com o SDK novo

    # --- ARQUIVO TEMPORÁRIO ---
    # Detecta a extensão do arquivo enviado
    ext = os.path.splitext(arquivo_upload.name)[1].lower()
    if not ext:
        ext = '.pdf' # Fallback

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
        for chunk in arquivo_upload.chunks():
            tmp_file.write(chunk)
        tmp_path = tmp_file.name

    try:
        print(f"--- Enviando Arquivo ({ext}) ---")
        
        # Define MIME type correto
        mime_type = 'application/pdf'
        if ext in ['.jpg', '.jpeg']:
            mime_type = 'image/jpeg'
        elif ext == '.png':
            mime_type = 'image/png'

        # Upload usando o cliente da nova SDK
        # O Client.files.upload retorna um objeto que pode ser passado pro generate_content
        sample_file = client.files.upload(file=tmp_path, config=types.UploadFileConfig(display_name="Extrato", mime_type=mime_type))

        # FORMATE AS CATEGORIAS PARA O PROMPT
        # Opção A: Lista simples separada por vírgulas
        # lista_cats_str = ", ".join(categorias_usuario)

        # Opção B: Lista numerada (mais clara para a IA)
        lista_cats_str = "\n".join([f"{i+1}. {cat}" for i, cat in enumerate(categorias_disponiveis)])

        # USE F-STRING PARA INTERPOLAR
        prompt = f"""
        Analise este extrato bancário.
        Extraia TODAS as transações para JSON.

        SUA MISSÃO DE CATEGORIZAÇÃO:
        Tente classificar cada compra em UMA das seguintes categorias existentes:
        {lista_cats_str}

        Regras:
        1. Se a transação se encaixar claramente em uma categoria acima, use o nome EXATO dela.
        2. Se não tiver certeza ou não encaixar, use a categoria "Importados".
        3. Converta datas para "YYYY-MM-DD". se o ano não estiver explícito, assuma o ano atual.
        4. Ignore saldos diários.
        5. Valor: float positivo (ex: 20.50). SE O VALOR NÃO ESTIVER CLARO, procure pelo número que aparece após "R$", geralmente está ao lado ou logo abaixo da descrição.
        6. Tipo: "D" (Débito) ou "R" (Crédito).
        7. Descricao: Limpe o texto.

        Retorne APENAS o JSON no formato:
        [
          {{
            "data": "YYYY-MM-DD",
            "descricao": "texto limpo",
            "valor": 0.00,
            "tipo": "D",
            "categoria": "nome_exato_da_categoria_ou_Importados"
          }}
        ]
        """

        # --- ESTRATÉGIA DE GERAÇÃO ---
        response = client.models.generate_content(
            model=nome_modelo,
            contents=[prompt, sample_file],
            config=types.GenerateContentConfig(
                response_mime_type="application/json", # Força JSON estruturado
                safety_settings=[
                    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
                ]
            )
        )

        # --- DEBUG ---
        print(f"DEBUG - Resposta da IA: {response.text}")

        # Com response_mime_type="application/json", o texto já deve vir limpo,
        # mas mantemos uma limpeza defensiva básica
        texto = response.text.replace('```json', '').replace('```', '').strip()

        if not texto:
            print("Erro: A IA retornou texto vazio.")
            return []

        dados = json.loads(texto)

        transacoes = []
        for item in dados:
            try:
                # Validação básica
                if not all(k in item for k in ['data', 'descricao', 'valor', 'tipo']):
                    print(f"⚠️ Item ignorado (campos faltando): {item}")
                    continue

                # Mantém data como string
                data_str = item['data']

                # Valida formato da data
                datetime.strptime(data_str, '%Y-%m-%d')  # Apenas valida, não converte

                # Pega a categoria que a IA escolheu (ou "Importados" se não vier)
                categoria_nome = item.get('categoria', 'Importados')

                transacoes.append({
                    'data': data_str,  # ✅ STRING, não objeto date
                    'descricao': item['descricao'],
                    'valor': float(item['valor']),
                    'tipo': item['tipo'],
                    'categoria': categoria_nome  # ✅ AGORA INCLUI A CATEGORIA
                })

            except ValueError as ve:
                print(f"⚠️ Erro ao processar item (data inválida): {item} - {ve}")
                continue
            except Exception as e:
                print(f"⚠️ Erro ao processar item: {item} - {e}")
                continue

        print(f"✅ Total de transações processadas: {len(transacoes)}")
        return transacoes

    except Exception as e:
        print(f"Erro na geração da IA: {e}")
        return []

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)