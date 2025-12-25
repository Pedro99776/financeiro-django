import google.genai as genai
import os
import json
import tempfile
from datetime import datetime
from google.generativeai.types import HarmCategory, HarmBlockThreshold


def importar_extrato_com_ia(arquivo_upload, categorias_disponiveis):
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        print("ERRO: Chave API não encontrada.")
        return []

    genai.configure(api_key=api_key)

    # --- CONFIGURAÇÃO ESTRITA: MODELO 2.0 ---
    nome_modelo = 'gemini-2.5-flash'

    try:
        model = genai.GenerativeModel(nome_modelo)
        print(f"--- Modelo Selecionado: {nome_modelo} ---")
    except Exception as e:
        print(f"Erro ao instanciar modelo {nome_modelo}: {e}")
        return []

    # --- ARQUIVO TEMPORÁRIO ---
    suffix = ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
        for chunk in arquivo_upload.chunks():
            tmp_file.write(chunk)
        tmp_path = tmp_file.name

    try:
        print(f"--- Enviando PDF ---")
        sample_file = genai.upload_file(path=tmp_path, display_name="Extrato")

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
        3. Converta datas para "YYYY-MM-DD".
        4. Ignore saldos diários.
        5. Valor: float positivo (ex: 20.50).
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

        # --- CONFIGURAÇÃO DE SEGURANÇA (CRÍTICO) ---
        # Isso impede que o Google bloqueie o extrato por achar que é dado sensível
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }

        # Gera o conteúdo
        response = model.generate_content(
            [prompt, sample_file],
            safety_settings=safety_settings
        )

        # --- DEBUG: Ver o que a IA respondeu antes de tentar ler JSON ---
        print(f"DEBUG - Resposta Bruta da IA: {response.text}")

        # Limpeza
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

                # IMPORTANTE: Mantém a data como STRING (para ser JSON-serializável)
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
        # Se houver feedback de bloqueio, mostramos
        if 'response' in locals() and hasattr(response, 'prompt_feedback'):
            print(f"Feedback de bloqueio: {response.prompt_feedback}")
        return []

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)