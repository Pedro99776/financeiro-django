from google import genai
from google.genai import types
import os
import json
import tempfile
from datetime import datetime
import csv
import io


def importar_extrato_com_ia(arquivo_upload, categorias_disponiveis):
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        print("ERRO: Chave API não encontrada.")
        return []

    # --- CONFIGURAÇÃO CLI DO NOVO SDK ---
    client = genai.Client(api_key=api_key)

    # Detecta extensão
    ext = os.path.splitext(arquivo_upload.name)[1].lower()
    
    # --- FLUXO CSV OTIMIZADO ---
    if ext in ['.csv', '.txt']:
        return processar_csv_workflow(arquivo_upload, categorias_disponiveis, client)

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


def processar_csv_workflow(arquivo, categorias_disponiveis, client):
    """
    Fluxo OTIMIZADO V4 (Correção de Chaves):
    - Normaliza chaves do JSON da IA (Data -> data, Descrição -> descricao).
    - Mantém a blindagem de lotes e try/except.
    """
    try:
        print("--- Iniciando Processamento CSV V4 ---")
        arquivo.seek(0)
        content_bytes = arquivo.read()
        
        # 1. Decodificação Robusta
        try:
            texto_completo = content_bytes.decode('utf-8')
        except UnicodeDecodeError:
            texto_completo = content_bytes.decode('latin-1')

        linhas = texto_completo.splitlines()
        amostra = "\n".join(linhas[:25]) 

        # --- PASSO 1: ANALISAR ESTRUTURA (IA) ---
        prompt_header = f"""
        Analise este início de CSV bancário. Retorne a configuração para leitura.
        
        AMOSTRA:
        {amostra}
        
        REGRAS:
        - Identifique os índices (0-based) das colunas: 'data', 'descricao', 'valor'.
        - Se houver colunas separadas de Entrada/Saida, use 'valor' para a coluna de valor absoluto ou a de Saída.
        
        Retorne JSON Exato:
        {{
            "delimiter": ";", 
            "header_line_index": 0,
            "date_format": "%d/%m/%Y",
            "decimal_separator": ",",
            "indices": {{ "data": 0, "descricao": 1, "valor": 2 }}
        }}
        """
        
        try:
            resp_header = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt_header,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            config = json.loads(resp_header.text)
        except Exception as e:
            print(f"Erro ao analisar cabeçalho: {e}")
            config = {'delimiter': ';', 'header_line_index': 0, 'indices': {}}
        
        print(f"DEBUG - Config detectada: {config}")

        # Extrai configurações
        delim = config.get('delimiter', ';')
        start_line = config.get('header_line_index', 0)
        indices_raw = config.get('indices', {})
        date_fmt = config.get('date_format', '%d/%m/%Y')
        dec_sep = config.get('decimal_separator', ',')

        # --- CORREÇÃO: NORMALIZAÇÃO DE ÍNDICES ---
        # A IA pode retornar 'Data', 'Valor', 'Descrição'. Nós precisamos de 'data', 'valor', 'descricao'.
        indices = {}
        
        # Função auxiliar para limpar strings (remove acentos e lowercase)
        def limpar_chave(txt):
            return txt.lower().replace('ç', 'c').replace('ã', 'a').replace('á', 'a').replace('é', 'e')

        # Mapeamento inteligente
        mapa_campos = {
            'data': ['data', 'date', 'dt', 'dia'],
            'descricao': ['descricao', 'desc', 'historico', 'hist', 'memorando', 'loja'],
            'valor': ['valor', 'amount', 'total', 'mn', 'saldo'] # Saldo as vezes é confundido, mas 'valor' é prioridade
        }

        # Varre o que a IA retornou e tenta encaixar nas chaves certas
        for k_ia, v_ia in indices_raw.items():
            chave_limpa = limpar_chave(k_ia)
            
            # Tenta encontrar match exato ou por sinônimo
            found = False
            for campo_interno, sinonimos in mapa_campos.items():
                if chave_limpa == campo_interno or chave_limpa in sinonimos:
                    indices[campo_interno] = v_ia
                    found = True
                    break
            
            # Se não achou por lista, assume direto se contiver o nome (ex: 'valor_total' -> 'valor')
            if not found:
                for campo_interno in mapa_campos:
                    if campo_interno in chave_limpa:
                        indices[campo_interno] = v_ia

        print(f"DEBUG - Índices Normalizados: {indices}")

        # --- PASSO 2: PROCESSAMENTO PYTHON ---
        transacoes_temp = []
        descricoes_unicas = set()
        
        if start_line + 1 < len(linhas):
            dados_reais = linhas[start_line + 1:] 
        else:
            dados_reais = []
        
        csv_reader = csv.reader(dados_reais, delimiter=delim)

        for row in csv_reader:
            # Verifica se temos as colunas obrigatórias mapeadas
            if not row or 'data' not in indices or 'valor' not in indices:
                continue
            
            # Proteção de tamanho da linha
            max_idx = max(indices.values())
            if len(row) <= max_idx:
                continue
            
            try:
                # Usa .get com fallback para descricao se falhar
                raw_data = row[indices['data']].strip()
                raw_valor = row[indices['valor']].strip()
                
                if 'descricao' in indices:
                    raw_desc = row[indices['descricao']].strip()
                else:
                    raw_desc = "Sem Descrição"

                # Parseamento de Valor Robusto
                val_clean = raw_valor.replace('R$', '').replace(' ', '')
                if dec_sep == ',':
                    val_clean = val_clean.replace('.', '').replace(',', '.')
                else:
                    val_clean = val_clean.replace(',', '')
                
                if not val_clean: continue
                valor_float = float(val_clean)

                # Parseamento de Data
                try:
                    dt_obj = datetime.strptime(raw_data, date_fmt)
                    data_iso = dt_obj.strftime('%Y-%m-%d')
                except ValueError:
                    data_iso = datetime.now().strftime('%Y-%m-%d')

                transacoes_temp.append({
                    'data': data_iso,
                    'descricao': raw_desc,
                    'valor': abs(valor_float),
                    'tipo': 'D' if valor_float < 0 else 'R', 
                    'categoria': 'Importados'
                })
                
                descricoes_unicas.add(raw_desc)

            except Exception as e:
                continue

        # --- PASSO 3: CATEGORIZAÇÃO EM LOTES ---
        lista_descricoes = list(descricoes_unicas)
        batch_size = 50 
        mapa_global = {}

        if lista_descricoes:
            for i in range(0, len(lista_descricoes), batch_size):
                lote = lista_descricoes[i:i + batch_size]
                print(f"Categorizando lote {i} a {i+len(lote)}...")

                prompt_cat = f"""
                Classifique as transações bancárias abaixo em uma das categorias: {", ".join(categorias_disponiveis)}.
                
                Transações:
                {json.dumps(lote, ensure_ascii=False)}
                
                Retorne APENAS um JSON (Lista de objetos):
                [
                    {{"descricao": "Descrição Original", "categoria": "Categoria Escolhida"}}
                ]
                """
                
                try:
                    resp_cat = client.models.generate_content(
                        model='gemini-2.0-flash',
                        contents=prompt_cat,
                        config=types.GenerateContentConfig(response_mime_type="application/json")
                    )
                    
                    dados_ia = json.loads(resp_cat.text)
                    
                    if isinstance(dados_ia, dict):
                        mapa_global.update(dados_ia)
                    elif isinstance(dados_ia, list):
                        for item in dados_ia:
                            # Tenta pegar chaves variadas que a IA possa inventar
                            chave = item.get('descricao') or item.get('transacao') or item.get('nome')
                            valor = item.get('categoria') or item.get('classificacao')
                            if chave and valor:
                                mapa_global[chave] = valor
                            elif isinstance(item, str) and len(dados_ia) == len(lote):
                                # Fallback para lista simples de strings
                                for desc_orig, cat_ia in zip(lote, dados_ia):
                                    mapa_global[desc_orig] = cat_ia
                                break
                                    
                except Exception as e:
                    print(f"Erro ao processar lote {i}: {e}")

        # Aplica o mapa final
        print(f"Mapa de categorias gerado: {len(mapa_global)} itens")
        for t in transacoes_temp:
            desc_limpa = t['descricao'].strip()
            # Tenta match exato ou parcial
            if desc_limpa in mapa_global:
                t['categoria'] = mapa_global[desc_limpa]
            else:
                # Tenta match parcial reverso (se a IA encurtou o nome no mapa)
                for k, v in mapa_global.items():
                    if k in desc_limpa:
                        t['categoria'] = v
                        break

        return transacoes_temp

    except Exception as e:
        print(f"Erro fatal no processamento CSV: {e}")
        return []