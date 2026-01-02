"""
Chatbot Financeiro - Lógica Principal
Gemini com RAG (contexto do banco de dados)
"""

from google import genai
from google.genai import types
import os
from django.db.models import Sum, Q
from django.core.cache import cache
from datetime import datetime
from decimal import Decimal

from .models import Transacao, Conta, Categoria


def gerar_resposta_chatbot(mensagem_usuario, usuario, historico=None):
    """
    Gera resposta inteligente usando Gemini com contexto financeiro.
    """
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        return "❌ Erro: Chave de API do Gemini não configurada. Contate o administrador."

    client = genai.Client(api_key=api_key)

    # 1. Busca contexto financeiro (com cache)
    resumo_financeiro = _montar_contexto_financeiro(usuario)
    
    # 2. System instruction completa
    system_instruction = f"""
Você é **FinBot**, assistente financeiro pessoal do usuário.

🎯 SUA PERSONALIDADE:
- Gentil, prestativo e profissional
- Conciso (máximo 3 parágrafos por resposta)
- Use emojis com moderação (1-2 por resposta)
- Linguagem natural e clara

DADOS DO USUÁRIO:
{resumo_financeiro}

FERRAMENTAS DISPONÍVEIS:

1. criar_transacao
   Quando: usuário diz "gastei", "recebi", "comprei", "paguei", "pix"
   Ação: CHAME IMEDIATAMENTE
   - Infira categoria se não foi dita
   - Conta="" se não foi dita
   - Data=hoje se não foi dita
   - Valor=0 se não foi dito

2. criar_categoria
   Quando: "crie categoria X", "nova categoria X"
   Ação: CHAME criar_categoria(nome="X")

3. editar_categoria
   Quando: "renomeie categoria X para Y", "mude categoria X"
   Ação: Busque ID de X no contexto → CHAME editar_categoria(id=ID, novo_nome="Y")

4. excluir_categoria
   Quando: "delete categoria X", "remova categoria X"
   Ação: Busque ID de X → CHAME excluir_categoria(id=ID)

5. criar_conta
   Quando: "crie conta X", "nova conta X"
   Ação: CHAME criar_conta(nome="X", instituicao="X", saldo_inicial=0)

6. editar_conta
   Quando: "edite conta X", "mude saldo de X"
   Ação: Busque ID de X → CHAME editar_conta(id=ID, ...)

7. excluir_conta
   Quando: "delete conta X"
   Ação: Busque ID de X → CHAME excluir_conta(id=ID)

8. consultar_maiores_gastos
   Quando: "maiores gastos", "top gastos", "top 5 gastos", "onde mais gastei"
   Ação: CHAME consultar_maiores_gastos(ano=YYYY, mes=MM, limit=N)
   Exemplo: "top 5 gastos de 2025" → consultar_maiores_gastos(ano=2025, limit=5)

9. consultar_categoria_mais_gasta
   Quando: "qual categoria mais gastei", "categoria que mais gasto", "onde mais gasto"
   Ação: CHAME consultar_categoria_mais_gasta(ano=YYYY, mes=MM)
   Exemplo: "qual categoria mais gastei em 2025?" → consultar_categoria_mais_gasta(ano=2025)

10. consultar_gastos_por_categoria
    Quando: "gastos por categoria", "quanto gastei em cada categoria", "distribuição de gastos"
    Ação: CHAME consultar_gastos_por_categoria(ano=YYYY, mes=MM)
    Exemplo: "gastos por categoria em 2025" → consultar_gastos_por_categoria(ano=2025)

REGRAS:
- NÃO peça confirmação (formulário faz isso)
- SEMPRE use IDs do contexto para editar/excluir

📋 FORMATAÇÃO DE LISTAS:
Quando listar categorias ou contas, use este formato:

**Categorias:**
- Nome1
- Nome2
- Nome3

**Contas:**
- Nome (Instituição): R$ saldo
- Nome (Instituição): R$ saldo
- Saldo total: R$ saldo

🚫 NUNCA mostre IDs para o usuário (use apenas internamente)

🚫 PERGUNTAS NÃO-FINANCEIRAS:
- Se a pergunta não for sobre finanças pessoais ou O SISTEMA (categorias/contas), responda educadamente:
  "Sou especializado em ajudar com suas finanças e gerenciamento do app. Posso responder sobre saldo, gastos, receitas ou ajudar a organizar categorias e contas."
- Exemplo: clima, notícias, esportes → redirecionar para finanças
- NUNCA invente informações sobre outros assuntos

🚨 REGRA SUPREMA DE AÇÃO (CRÍTICO):
SE O USUÁRIO PEDIR PARA CRIAR, EDITAR OU EXCLUIR ALGO:
VOCÊ ESTÁ PROIBIDO DE EXECUTAR AÇÕES APENAS COM TEXTO.
1. VC DEVE CHAMAR A FERRAMENTA CORRESPONDENTE (Tool Call).
2. VC NÃO PODE RESPONDER: "Criando categoria..." ou "Criei a conta...".
3. A ÚNICA resposta aceitável para uma ação é o CHAMADO DA FUNÇÃO.
4. Se você responder apenas textos como "Vou criar a categoria X", VOCÊ FALHOU.

📌 REGRAS ESPECÍFICAS PARA AÇÕES:
- Respostas: máx 3 parágrafos, use **negrito** em valores
"""

    # 3. Definição de Ferramentas (Function Calling)
    # Define a ferramenta para criar transações
    ferramenta_criar_transacao = types.FunctionDeclaration(
        name="criar_transacao",
        description="Registra uma nova despesa ou receita. Chame isso quando o usuário mencionar qualquer atividade financeira (ex: comprei, paguei, recebi, fiz pix), mesmo sem palavras-chave explícitas.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "descricao": types.Schema(type="STRING", description="Descrição curta da transação (ex: Uber, Mercado, Salário)."),
                "valor": types.Schema(type="NUMBER", description="Valor numérico da transação (ex: 50.00). Use positivo."),
                "tipo": types.Schema(type="STRING", enum=["D", "R"], description="Tipo: 'D' para Despesa, 'R' para Receita"),
                "categoria": types.Schema(type="STRING", description="Nome da categoria (ex: Transporte, Alimentação). OBRIGATÓRIO: Se não foi falado, INFERIR pelo contexto (ex: Uber -> Transporte)."),
                "conta": types.Schema(type="STRING", description="Nome da conta (ex: Nubank, Carteira). Se for cartão de crédito, deixe vazio."),
                "cartao": types.Schema(type="STRING", description="Nome do cartão de crédito (ex: Nubank, Visa). Use se o usuário mencionar 'crédito' ou nome do cartão."),
                "data": types.Schema(type="STRING", description="Data no formato YYYY-MM-DD. OBRIGATÓRIO: Se o usuário disse 'ontem', 'hoje', 'terça passada', CALCULE baseando-se na data de referência fornecida.")
            },
            required=["descricao", "valor", "tipo", "data", "categoria"]
        )
    )
    # --- TOOLS PARA CATEGORIAS ---
    ferramenta_criar_categoria = types.FunctionDeclaration(
        name="criar_categoria", description="Cria uma nova categoria.",
        parameters=types.Schema(type="OBJECT", properties={"nome": types.Schema(type="STRING", description="Nome da categoria")}, required=["nome"])
    )
    ferramenta_editar_categoria = types.FunctionDeclaration(
        name="editar_categoria", description="Edita o nome de uma categoria existente. Requer ID (veja no contexto).",
        parameters=types.Schema(type="OBJECT", properties={
            "id": types.Schema(type="INTEGER", description="ID da categoria a editar"),
            "novo_nome": types.Schema(type="STRING", description="Novo nome")
        }, required=["id", "novo_nome"])
    )
    ferramenta_excluir_categoria = types.FunctionDeclaration(
        name="excluir_categoria", description="Exclui uma categoria existente. Requer ID (veja no contexto).",
        parameters=types.Schema(type="OBJECT", properties={"id": types.Schema(type="INTEGER", description="ID da categoria")}, required=["id"])
    )

    # --- TOOLS PARA CONTAS ---
    ferramenta_criar_conta = types.FunctionDeclaration(
        name="criar_conta", description="Cria uma nova conta bancária.",
        parameters=types.Schema(type="OBJECT", properties={
            "nome": types.Schema(type="STRING", description="Nome da conta"),
            "instituicao": types.Schema(type="STRING", description="Instituição (opcional)"),
            "saldo_inicial": types.Schema(type="NUMBER", description="Saldo inicial")
        }, required=["nome"])
    )
    ferramenta_editar_conta = types.FunctionDeclaration(
        name="editar_conta", description="Edita uma conta existente.",
        parameters=types.Schema(type="OBJECT", properties={
            "id": types.Schema(type="INTEGER", description="ID da conta"),
            "nome": types.Schema(type="STRING", description="Novo nome"),
            "instituicao": types.Schema(type="STRING", description="Nova instituição"),
            "saldo_inicial": types.Schema(type="NUMBER", description="Novo saldo inicial")
        }, required=["id"])
    )
    ferramenta_excluir_conta = types.FunctionDeclaration(
        name="excluir_conta", description="Exclui uma conta existente.",
        parameters=types.Schema(type="OBJECT", properties={"id": types.Schema(type="INTEGER", description="ID da conta")}, required=["id"])
    )
    
    # --- TOOLS ANALÍTICAS ---
    ferramenta_top_gastos = types.FunctionDeclaration(
        name="consultar_maiores_gastos",
        description="Retorna os maiores gastos de um período. Use quando usuário perguntar 'maiores gastos', 'top gastos', 'onde mais gastei'.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "ano": types.Schema(type="INTEGER", description="Ano para consulta (ex: 2025)"),
                "mes": types.Schema(type="INTEGER", description="Mês (1-12). Opcional. Se não informado, busca o ano todo."),
                "limit": types.Schema(type="INTEGER", description="Quantos resultados retornar (padrão: 5)")
            },
            required=["ano"]
        )
    )

    ferramenta_categoria_mais_gasta = types.FunctionDeclaration(
        name="consultar_categoria_mais_gasta",
        description="Retorna qual categoria teve mais gastos no período.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "ano": types.Schema(type="INTEGER", description="Ano"),
                "mes": types.Schema(type="INTEGER", description="Mês (opcional)")
            },
            required=["ano"]
        )
    )

    ferramenta_gastos_por_categoria = types.FunctionDeclaration(
        name="consultar_gastos_por_categoria",
        description="Retorna total gasto em cada categoria do período.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "ano": types.Schema(type="INTEGER", description="Ano"),
                "mes": types.Schema(type="INTEGER", description="Mês (opcional)")
            },
            required=["ano"]
        )
    )

    tools = [
        types.Tool(function_declarations=[
            ferramenta_criar_transacao,
            ferramenta_criar_categoria, ferramenta_editar_categoria, ferramenta_excluir_categoria,
            ferramenta_criar_conta, ferramenta_editar_conta, ferramenta_excluir_conta,
            ferramenta_top_gastos, ferramenta_categoria_mais_gasta, ferramenta_gastos_por_categoria
        ])
    ]

    # 4. Monta conversa com histórico
    contents = []
    
    # Adiciona últimas 5 trocas (10 mensagens) para contexto if historico
    if historico:
        for msg in historico[-10:]:
            role = 'user' if msg['role'] == 'user' else 'model'
            # Se for uma mensagem de ação anterior, o conteúdo pode ser complexo. 
            # Por simplificação, se não for string, ignoramos no histórico imediato
            # ou convertemos para texto indicativo.
            if isinstance(msg['content'], str):
                contents.append(types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=msg['content'])]
                ))
    
    # Adiciona mensagem atual
    contents.append(types.Content(
        role='user', 
        parts=[types.Part.from_text(text=f"{mensagem_usuario} (Data de hoje para referência: {datetime.now().strftime('%Y-%m-%d')})")]
    ))

    # 5. Chama Gemini com Tools
    try:
        generate_content_config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.5, # Temperatura mediana para ser mais preciso nas funções
            max_output_tokens=1000, # Aumentado para suportar respostas analíticas
            tools=tools, # ✅ Injeta as ferramentas
        )

        response = client.models.generate_content(
            model='gemini-2.0-flash', 
            contents=contents,
            config=generate_content_config
        )
        
        # 6. Verifica se houve Chamada de Função
        # No novo SDK, verificamos se há parts com function_call
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    fc = part.function_call
                    
                    # === FLUXO A: AÇÕES (Retorna Card para Frontend) ===
                    if fc.name == "criar_transacao":
                        args = {k: v for k, v in fc.args.items()}
                        return { "type": "action_proposal", "action": "create_transaction", "data": {
                                "descricao": args.get('descricao'), "valor": float(args.get('valor', 0)),
                                "tipo": args.get('tipo'), "categoria": args.get('categoria', 'Importados'),
                                "conta": args.get('conta', ''), "cartao": args.get('cartao', ''), 
                                "data": args.get('data', datetime.now().strftime('%Y-%m-%d'))
                            }, "text_fallback": f"Entendi. Vou preparar o lançamento de {args.get('descricao')} no valor de R$ {args.get('valor')}."
                        }
                    elif fc.name == "criar_categoria":
                        args = {k: v for k, v in fc.args.items()}
                        return { "type": "action_proposal", "action": "create_category", "data": args, "text_fallback": f"Vou criar a categoria '{args.get('nome')}'." }
                    elif fc.name == "editar_categoria":
                        args = {k: v for k, v in fc.args.items()}
                        return { "type": "action_proposal", "action": "edit_category", "data": args, "text_fallback": f"Vou editar a categoria ID {args.get('id')}." }
                    elif fc.name == "excluir_categoria":
                        args = {k: v for k, v in fc.args.items()}
                        return { "type": "action_proposal", "action": "delete_category", "data": args, "text_fallback": f"Vou excluir a categoria ID {args.get('id')}." }
                    elif fc.name == "criar_conta":
                        args = {k: v for k, v in fc.args.items()}
                        return { "type": "action_proposal", "action": "create_account", "data": args, "text_fallback": f"Vou criar a conta '{args.get('nome')}'." }
                    elif fc.name == "editar_conta":
                        args = {k: v for k, v in fc.args.items()}
                        return { "type": "action_proposal", "action": "edit_account", "data": args, "text_fallback": f"Vou editar a conta ID {args.get('id')}." }
                    elif fc.name == "excluir_conta":
                        args = {k: v for k, v in fc.args.items()}
                        return { "type": "action_proposal", "action": "delete_account", "data": args, "text_fallback": f"Vou excluir a conta ID {args.get('id')}." }
                    
                    # === FLUXO B: CONSULTAS ANALÍTICAS (Feedback Loop) ===
                    # 1. Executa a função localmente
                    elif fc.name in ["consultar_maiores_gastos", "consultar_categoria_mais_gasta", "consultar_gastos_por_categoria"]:
                        result_text = ""
                        args = {k: v for k, v in fc.args.items()}
                        
                        if fc.name == "consultar_maiores_gastos":
                            result_text = _buscar_maiores_gastos(usuario, args.get('ano'), args.get('mes'), args.get('limit', 5))
                        elif fc.name == "consultar_categoria_mais_gasta":
                            result_text = _buscar_categoria_mais_gasta(usuario, args.get('ano'), args.get('mes'))
                        elif fc.name == "consultar_gastos_por_categoria":
                            result_text = _buscar_gastos_por_categoria(usuario, args.get('ano'), args.get('mes'))

                        # 2. Adiciona ao histórico da conversa ATUAL (para o modelo ver o resultado)
                        # Precisamos adicionar a chamada da tool e o resultado
                        part_function_response = types.Part.from_function_response(
                            name=fc.name,
                            response={'result': result_text}
                        )
                        
                        # Adiciona a request do assistant que gerou o call
                        contents.append(response.candidates[0].content)
                        # Adiciona a resposta da tool
                        contents.append(types.Content(role="tool", parts=[part_function_response]))

                        # 3. Chama o modelo novamente com o novo contexto
                        response_final = client.models.generate_content(
                            model='gemini-2.0-flash', 
                            contents=contents,
                            config=generate_content_config
                        )
                        
                        return response_final.text

        # Se não houve function call, retorna o texto normal
        resposta_texto = response.text
        
        if not resposta_texto or len(resposta_texto.strip()) < 2:
            return "Desculpe, não entendi. Poderia repetir?"
        
        return resposta_texto
        
    except Exception as e:
        erro_msg = str(e)
        
        # Tratamento de erros específicos
        if "quota" in erro_msg.lower() or "rate limit" in erro_msg.lower():
            return "⏳ Muitas requisições. Por favor, aguarde alguns segundos e tente novamente."
        elif "api key" in erro_msg.lower():
            return "🔑 Erro de autenticação. Contate o administrador do sistema."
        else:
            return f"❌ Erro ao processar sua pergunta: {erro_msg}"


def _montar_contexto_financeiro(usuario):
    """
    Busca dados financeiros do usuário e formata para prompt.
    USA CACHE para evitar queries repetidas (5 minutos).
    """
    # Tenta pegar do cache primeiro
    cache_key = f'contexto_financeiro_{usuario.id}'
    contexto = cache.get(cache_key)
    
    if contexto:
        return contexto
    
    # Se não estiver em cache, busca do banco
    hoje = datetime.now()
    
    # === 1. SALDOS DAS CONTAS ===
    contas = Conta.objects.filter(usuario=usuario).annotate(
        total_receitas=Sum('transacao__valor', filter=Q(transacao__tipo='R'), default=Decimal('0')),
        total_despesas=Sum('transacao__valor', filter=Q(transacao__tipo='D'), default=Decimal('0'))
    ).order_by('nome')
    
    txt_contas = "💰 **CONTAS E SALDOS:**\n"
    saldo_total_geral = Decimal('0')
    
    if contas.exists():
        for conta in contas:
            receitas = conta.total_receitas or Decimal('0')
            despesas = conta.total_despesas or Decimal('0')
            saldo_atual = conta.saldo_inicial + receitas - despesas
            saldo_total_geral += saldo_atual
            
            txt_contas += f"  • **{conta.nome}** ({conta.instituicao}): R$ {saldo_atual:,.2f}\n"
        
        txt_contas += f"\n  📊 **SALDO TOTAL CONSOLIDADO: R$ {saldo_total_geral:,.2f}**\n"
    else:
        txt_contas += "  ⚠️ Nenhuma conta cadastrada.\n"

    # === 2. RESUMO DO MÊS ATUAL ===
    transacoes_mes = Transacao.objects.filter(
        conta__usuario=usuario, 
        data__month=hoje.month, 
        data__year=hoje.year
    ).aggregate(
        receitas=Sum('valor', filter=Q(tipo='R'), default=Decimal('0')),
        despesas=Sum('valor', filter=Q(tipo='D'), default=Decimal('0'))
    )
    
    receitas_mes = transacoes_mes['receitas'] or Decimal('0')
    despesas_mes = transacoes_mes['despesas'] or Decimal('0')
    balanco_mes = receitas_mes - despesas_mes
    
    txt_resumo = f"""
📅 **RESUMO DO MÊS ATUAL ({hoje.strftime('%B/%Y').upper()}):**
  • Receitas: R$ {receitas_mes:,.2f} 🟢
  • Despesas: R$ {despesas_mes:,.2f} 🔴
  • Balanço: R$ {balanco_mes:,.2f} {'✅' if balanco_mes >= 0 else '⚠️'}
"""

    # === 3. ÚLTIMAS 15 TRANSAÇÕES ===
    transacoes = Transacao.objects.filter(
        conta__usuario=usuario
    ).select_related('categoria', 'conta').order_by('-data')[:15]
    
    txt_transacoes = "\n📋 **ÚLTIMAS 15 TRANSAÇÕES:**\n"
    
    if transacoes.exists():
        for t in transacoes:
            icone = "🔴" if t.tipo == 'D' else "🟢"
            descricao = t.descricao[:35] + "..." if len(t.descricao) > 35 else t.descricao
            
            # ✅ CORREÇÃO:
            categoria_nome = t.categoria.nome if t.categoria else "Sem categoria"
            
            txt_transacoes += f"  {icone} {t.data.strftime('%d/%m/%Y')} | {descricao} | {categoria_nome} | R$ {t.valor:,.2f}\n"
    else:
        txt_transacoes += "  ⚠️ Nenhuma transação registrada ainda.\n"

    # === 4. GASTOS POR CATEGORIA (Top 5 do mês) ===
    gastos_categoria = Transacao.objects.filter(
        conta__usuario=usuario,
        data__month=hoje.month,
        data__year=hoje.year,
        tipo='D'
    ).values('categoria__nome').annotate(
        total=Sum('valor')
    ).order_by('-total')[:5]
    
    txt_categorias = "\n📊 **TOP 5 CATEGORIAS DE GASTOS (MÊS ATUAL):**\n"
    
    if gastos_categoria.exists():
        for item in gastos_categoria:
            categoria = item['categoria__nome']
            total = item['total'] or Decimal('0')
            txt_categorias += f"  • {categoria}: R$ {total:,.2f}\n"
    else:
        txt_categorias += "  ⚠️ Nenhum gasto categorizado este mês.\n"

    # === 5. LISTA DE CATEGORIAS E CONTAS (PARA REFERÊNCIA DO AGENTE) ===
    # O agente precisa dos IDs para editar ou excluir
    cats_db = Categoria.objects.filter(usuario=usuario).order_by('nome')
    txt_ref_cats = "\n📂 **CATEGORIAS DISPONÍVEIS (ID - Nome):**\n"
    if cats_db.exists():
        for c in cats_db:
            txt_ref_cats += f"  - ID {c.id}: {c.nome}\n"
    else:
        txt_ref_cats += "  (Nenhuma categoria cadastrada)\n"

    contas_db = Conta.objects.filter(usuario=usuario).order_by('nome')
    txt_ref_contas = "\n💳 **CONTAS DISPONÍVEIS (ID - Nome):**\n"
    if contas_db.exists():
        for c in contas_db:
            txt_ref_contas += f"  - ID {c.id}: {c.nome}\n"
    else:
        txt_ref_contas += "  (Nenhuma conta cadastrada)\n"

    # === MONTA CONTEXTO FINAL ===
    contexto_final = f"{txt_contas}\n{txt_resumo}\n{txt_transacoes}\n{txt_categorias}\n{txt_ref_cats}\n{txt_ref_contas}"
    
    # Salva no cache por 5 minutos (300 segundos)
    # ATENÇÃO: É necessário implementar mecanismo de invalidação de cache ao salvar novas transações!
    cache.set(cache_key, contexto_final, 300)
    
    return contexto_final


def limpar_cache_contexto(usuario):
    """
    Limpa o cache de contexto financeiro do usuário.
    Chamar sempre que houver mudanças (criar/editar/deletar transação).
    """
    if usuario:
        cache_key = f'contexto_financeiro_{usuario.id}'
        cache.delete(cache_key)


def limpar_historico_chat(session):
    """
    Limpa o histórico de conversa da sessão.
    """
    if 'chat_history' in session:
        del session['chat_history']
        session.modified = True


# --- FUNÇÕES AUXILIARES DE CONSULTA (AGENTE ANALÍTICO) ---

def _buscar_maiores_gastos(usuario, ano, mes=None, limit=5):
    """Busca maiores gastos do período"""
    
    qs = Transacao.objects.filter(
        conta__usuario=usuario,
        data__year=ano,
        tipo='D'
    )
    
    if mes:
        qs = qs.filter(data__month=mes)
    
    top = qs.order_by('-valor')[:limit]
    
    # Formata resposta
    periodo = f"{mes}/{ano}" if mes else f"{ano}"
    texto = f"**Top {limit} gastos de {periodo}:**\n"
    
    if not top.exists():
        return f"Não encontrei gastos registrados em {periodo}."
    
    for t in top:
        categoria = t.categoria.nome if t.categoria else "Sem categoria"
        texto += f"• {t.descricao}: R$ {t.valor:,.2f} ({categoria})\n"
    
    return texto


def _buscar_categoria_mais_gasta(usuario, ano, mes=None):
    """Busca categoria com mais gastos"""
    
    qs = Transacao.objects.filter(
        conta__usuario=usuario,
        data__year=ano,
        tipo='D'
    )
    
    if mes:
        qs = qs.filter(data__month=mes)
    
    resultado = qs.values('categoria__nome').annotate(
        total=Sum('valor')
    ).order_by('-total').first()
    
    if not resultado:
        return "Nenhum gasto registrado neste período."
    
    categoria = resultado['categoria__nome'] or "Sem categoria"
    total = resultado['total']
    
    periodo = f"{mes}/{ano}" if mes else f"{ano}"
    return f"**Categoria mais gasta em {periodo}:** {categoria} (R$ {total:,.2f})"


def _buscar_gastos_por_categoria(usuario, ano, mes=None):
    """Retorna gastos por categoria"""
    
    qs = Transacao.objects.filter(
        conta__usuario=usuario,
        data__year=ano,
        tipo='D'
    )
    
    if mes:
        qs = qs.filter(data__month=mes)
    
    categorias = qs.values('categoria__nome').annotate(
        total=Sum('valor')
    ).order_by('-total')
    
    if not categorias.exists():
        return "Nenhum gasto registrado neste período."
    
    periodo = f"{mes}/{ano}" if mes else f"{ano}"
    texto = f"**Gastos por categoria ({periodo}):**\n"
    
    for item in categorias:
        cat = item['categoria__nome'] or "Sem categoria"
        texto += f"• {cat}: R$ {item['total']:,.2f}\n"
    
    return texto
