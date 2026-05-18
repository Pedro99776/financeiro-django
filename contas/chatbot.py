"""
Chatbot Financeiro - Arquitetura Agente
Lógica baseada em Ferramentas (Tools)
"""

import os
import google.genai as genai
from google.genai import types
from datetime import datetime, timedelta
from django.conf import settings
from django.db.models import Q, Sum, Count
from django.db.models.functions import TruncMonth
from .models import Transacao, Conta, Categoria, CartaoCredito, FaturaCredito

# ==============================================================================
# 1. CONFIGURAÇÃO E PERSONALIDADE
# ==============================================================================

def get_system_instruction(usuario):
    """Retorna as instruções de sistema atuais."""
    hoje = datetime.now().strftime('%Y-%m-%d')
    
    # EXECUTA as queries (não deixa como string!)
    categorias = list(Categoria.objects.filter(usuario=usuario).values_list('nome', flat=True))
    contas = list(Conta.objects.filter(usuario=usuario).values_list('nome', flat=True))
    cartoes = list(CartaoCredito.objects.filter(usuario=usuario).values_list('nome', flat=True))
    
    # Formata contexto
    ctx_categorias = ', '.join(categorias) if categorias else 'nenhuma cadastrada'
    ctx_contas = ', '.join(contas) if contas else 'nenhuma cadastrada'
    ctx_cartoes = ', '.join(cartoes) if cartoes else 'nenhum cadastrado'
    
    return f"""
Você é o **FinBot**, um assistente financeiro pessoal proativo e inteligente.
Data de hoje: {hoje}

📋 DADOS DO USUÁRIO:
- Categorias disponíveis: {ctx_categorias}
- Contas disponíveis: {ctx_contas}
- Cartões disponíveis: {ctx_cartoes}

🎯 REGRAS CRÍTICAS DE COMPORTAMENTO:

1. **NUNCA peça confirmação ou informações faltantes ao criar/editar transações.**
   - Se o usuário disser "gastei 50 no McDonald's", você DEVE chamar a ferramenta IMEDIATAMENTE.
   
2. **ASSUMA valores padrão automaticamente:**
   - **Data**: Se não especificada, use HOJE. Se disser "ontem", calcule baseado em {hoje}.
   - **Conta**: Se não especificada, use a PRIMEIRA conta disponível ({contas[0] if contas else 'Nenhuma'}).
   - **Categoria**: SEMPRE tente inferir das categorias disponíveis:
     * McDonald's, Burger King, restaurante → "Alimentação" (se existir)
     * Uber, 99, gasolina → "Transporte" (se existir)
     * Cinema, Netflix → "Lazer" (se existir)
     * Se NENHUMA categoria se encaixar, deixe VAZIO (não pergunte!)
   - **Tipo**: Se for gasto/compra/pagamento → "D" (Despesa). Se for recebimento/salário → "R" (Receita).
   
3. **Palavras temporais que você DEVE interpretar:**
   - "ontem" → {(datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')}
   - "anteontem" → {(datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')}
   - "hoje" → {hoje}
   - "semana passada" → ~7 dias atrás
   - Se não especificado → HOJE

4. **Exclusões SÃO DIFERENTES:**
   - Se o usuário pedir para EXCLUIR algo, você PODE confirmar se houver ambiguidade.
   - Ex: "Delete aquela transação" → Pergunte qual, ou busque primeiro.

5. **Você NÃO tem acesso direto a DADOS DINÂMICOS (saldo, extrato, transações antigas).**
   - Para consultas (saldo, gastos, etc), você DEVE usar as ferramentas.
   - **MAS** você POSSUI a lista de Categorias, Contas e Cartões (DADOS DO USUÁRIO acima). Pode responder sobre o que existe ou não com base nisso.

EXEMPLOS DE USO CORRETO:

❌ ERRADO:
User: "Gastei 50 no Uber ontem"
Bot: "Qual conta devo usar?"

✅ CERTO:
User: "Gastei 50 no Uber ontem"
Bot: [chama gerenciar_transacao(
    acao="criar",
    descricao="Uber",
    valor=50,
    tipo="D",
    data="{(datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')}",
    categoria="Transporte",  # Inferiu!
    conta="{contas[0] if contas else ''}"  # Primeira conta!
)]

---

❌ ERRADO:
User: "Comprei um lanche no McDonald's"
Bot: "Me diga a data e o valor"

✅ CERTO:
User: "Comprei um lanche no McDonald's"
Bot: [chama gerenciar_transacao com data=hoje, conta=primeira, categoria=Alimentação, tipo=D]
# NOTA: Se o usuário não disse valor, AÍ SIM você pode perguntar (valor é obrigatório!)

---

FERRAMENTAS DISPONÍVEIS:
1. `consultar_resumo_financeiro`: saldo, balanço
2. `gerenciar_transacao`: criar/editar/excluir despesas/receitas
3. `gerenciar_categoria/conta/cartao`: CRUD de entidades
4. `buscar_transacoes`: encontrar transações por filtros
5. `consultar_gastos_detalhados`: top gastos, análises
6. `consultar_fatura_cartao`: faturas de crédito

DICAS:
- "Qual meu saldo?" → consultar_resumo_financeiro(tipo='saldo_total')
- "Gastei X em Y" → gerenciar_transacao(acao="criar", ...) [INFERINDO valores!]
- "Apague a última transação" → gerenciar_transacao(acao="excluir") [Sem ID = última]
- "Edite a última transação para valor 50" → gerenciar_transacao(acao="editar", valor=50) [Sem ID = última]
- "Apague a transação 123" → gerenciar_transacao(acao="excluir", id=123)
- "Mude a categoria Comida para Alimentação" → gerenciar_categoria(acao="editar", nome_original="Comida", nome="Alimentação")
- "Apague a conta Nubank" → gerenciar_conta(acao="excluir", nome="Nubank")
- "Quanto gastei em Maio?" → consultar_resumo_financeiro(tipo="despesas_periodo", mes=5, modalidade="todos")
- "Gastos no cartão em Maio?" → consultar_resumo_financeiro(tipo="despesas_periodo", mes=5, modalidade="credito")
- "Qual mês gastei mais em 2024?" → analise_picos(tipo="despesa", data_inicio="2024-01-01", data_fim="2024-12-31")

6. **FORMATAÇÃO DE LISTAS:**
   - Sempre que listar categorias, contas ou cartões, use este formato limpo:
     **Categorias:**
     - Nome 1
     - Nome 2
     ...
"""

# ==============================================================================
# 2. DEFINIÇÃO DE ESQUEMAS (SCHEMA) DAS FERRAMENTAS
# ==============================================================================

tools_schema = [
    # --- Gestão de Transações ---
    types.FunctionDeclaration(
        name="gerenciar_transacao",
        description="Cria, edita ou exclui uma transação financeira (Receita ou Despesa).",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "acao": types.Schema(type="STRING", enum=["criar", "editar", "excluir"], description="Ação."),
                "id": types.Schema(type="INTEGER", description="ID da transação. Se omitido ao editar/excluir, assume a última transação realizada."),
                "descricao": types.Schema(type="STRING", description="Descrição."),
                "valor": types.Schema(type="NUMBER", description="Valor."),
                "tipo": types.Schema(type="STRING", enum=["D", "R"], description="Tipo."),
                "data": types.Schema(type="STRING", description="Data (YYYY-MM-DD)."),
                "categoria": types.Schema(type="STRING", description="Nome da categoria."),
                "conta": types.Schema(type="STRING", description="Nome da conta."),
                "cartao": types.Schema(type="STRING", description="Nome do cartão."),
                "fatura_id": types.Schema(type="INTEGER", description="ID fatura.")
            },
            required=["acao"]
        )
    ),

    # --- Gestão de Entidades (Categoria, Conta, Cartão) ---
    types.FunctionDeclaration(
        name="gerenciar_categoria",
        description="Gerencia Categorias.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "acao": types.Schema(type="STRING", enum=["criar", "editar", "excluir"]),
                "id": types.Schema(type="INTEGER", description="ID (Opcional se nome ou nome_original for informado)."),
                "nome": types.Schema(type="STRING", description="Nome (ou novo nome se for edição)."),
                "nome_original": types.Schema(type="STRING", description="Nome ATUAL da entidade (usado para localizar ao editar).")
            },
            required=["acao"]
        )
    ),
    types.FunctionDeclaration(
        name="gerenciar_conta",
        description="Gerencia Contas Bancárias.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "acao": types.Schema(type="STRING", enum=["criar", "editar", "excluir"]),
                "id": types.Schema(type="INTEGER", description="ID (Opcional se nome ou nome_original for informado)."),
                "nome": types.Schema(type="STRING", description="Nome (ou novo nome se for edição)."),
                "nome_original": types.Schema(type="STRING", description="Nome ATUAL da conta (usado para localizar ao editar)."),
                "instituicao": types.Schema(type="STRING", description="Instituição."),
                "saldo_inicial": types.Schema(type="NUMBER", description="Saldo inicial.")
            },
            required=["acao"]
        )
    ),
    types.FunctionDeclaration(
        name="gerenciar_cartao",
        description="Gerencia Cartões de Crédito.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "acao": types.Schema(type="STRING", enum=["criar", "editar", "excluir"]),
                "id": types.Schema(type="INTEGER", description="ID (Opcional se nome ou nome_original for informado)."),
                "nome": types.Schema(type="STRING", description="Nome (ou novo nome se for edição)."),
                "nome_original": types.Schema(type="STRING", description="Nome ATUAL do cartão (usado para localizar ao editar)."),
                "limite": types.Schema(type="NUMBER", description="Limite."),
                "dia_vencimento": types.Schema(type="INTEGER", description="Dia venc."),
                "dia_fechamento": types.Schema(type="INTEGER", description="Dia fech."),
                "bandeira": types.Schema(type="STRING", enum=["VISA", "MASTERCARD"])
            },
            required=["acao"]
        )
    ),

    # --- Busca e Consulta ---
    types.FunctionDeclaration(
        name="buscar_transacoes",
        description="Busca transações com filtros.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "texto": types.Schema(type="STRING"),
                "ano": types.Schema(type="INTEGER"),
                "mes": types.Schema(type="INTEGER"),
                "categoria_id": types.Schema(type="INTEGER"),
                "conta_id": types.Schema(type="INTEGER"),
                "cartao_id": types.Schema(type="INTEGER"),
                "tipo": types.Schema(type="STRING"),
                "limit": types.Schema(type="INTEGER"),
                "order_by": types.Schema(type="STRING")
            },
            required=[]
        )
    ),
    types.FunctionDeclaration(
        name="consultar_resumo_financeiro",
        description="Consulta saldos e balanços financeiros.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "tipo": types.Schema(type="STRING", enum=["saldo_total", "saldo_conta", "balanco_periodo", "receitas_periodo", "despesas_periodo"], description="Tipo (obrigatório)."),
                "conta_id": types.Schema(type="INTEGER", description="ID da conta (opcional)."),
                "ano": types.Schema(type="INTEGER", description="Ano."),
                "mes": types.Schema(type="INTEGER", description="Mês."),
                "modalidade": types.Schema(type="STRING", enum=["credito", "debito", "todos"], description="Filtrar por modalidade (Opcional). Default=todos.")
            },
            required=["tipo"]
        )
    ),

    # --- Análises ---
    types.FunctionDeclaration(
        name="consultar_gastos_detalhados",
        description="Análises agregadas.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "tipo": types.Schema(type="STRING", enum=["maiores_gastos", "categoria_mais_gasta", "gastos_por_categoria", "comparar_periodos"]),
                "ano": types.Schema(type="INTEGER"),
                "mes": types.Schema(type="INTEGER"),
                "ano2": types.Schema(type="INTEGER"),
                "mes2": types.Schema(type="INTEGER"),
                "limit": types.Schema(type="INTEGER")
            },
            required=["tipo"]
        )
    ),
    types.FunctionDeclaration(
        name="analise_picos",
        description="Analisa meses de maior receita ou despesa.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "tipo": types.Schema(type="STRING", enum=["receita", "despesa"], description="Tipo de análise."),
                "data_inicio": types.Schema(type="STRING", description="Filtro início (YYYY-MM-DD)."),
                "data_fim": types.Schema(type="STRING", description="Filtro fim (YYYY-MM-DD).")
            },
            required=["tipo"]
        )
    ),
    types.FunctionDeclaration(
        name="consultar_fatura_cartao",
        description="Faturas de cartão.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "cartao_id": types.Schema(type="INTEGER"),
                "mes": types.Schema(type="INTEGER"),
                "ano": types.Schema(type="INTEGER"),
                "detalhes": types.Schema(type="BOOLEAN")
            },
            required=["cartao_id"]
        )
    )
]

# ==============================================================================
# 3. IMPLEMENTAÇÃO DAS FERRAMENTAS (PYTHON)
# ==============================================================================

def _resolve_categoria(usuario, nome_categoria):
    """Busca ou cria categoria pelo nome (case insensitive)."""
    if not nome_categoria:
        return None
    nome_clean = nome_categoria.strip()
    cat = Categoria.objects.filter(usuario=usuario, nome__iexact=nome_clean).first()
    if not cat:
        cat = Categoria.objects.filter(usuario=usuario, nome__icontains=nome_clean).first()
    if not cat:
        # Se não existe, cria
        cat = Categoria.objects.create(usuario=usuario, nome=nome_clean)
    return cat

def _resolve_conta(usuario, nome_conta):
    """Busca conta pelo nome."""
    if not nome_conta:
        return None
    return Conta.objects.filter(usuario=usuario, nome__icontains=nome_conta.strip()).first()

def _resolve_cartao(usuario, nome_cartao):
    """Busca cartão pelo nome."""
    if not nome_cartao:
        return None
    return CartaoCredito.objects.filter(usuario=usuario, nome__icontains=nome_cartao.strip()).first()



def _gerenciar_transacao_func(usuario, acao, id=None, descricao=None, valor=None, tipo=None, 
                              data=None, categoria=None, conta=None, cartao=None, fatura_id=None):
    try:
        if acao == "criar":
            if not descricao or not valor or not data:
                return "Erro: Falta descrição, valor ou data."
            
            # Resolve chaves estrangeiras apenas para pegar os IDs/Nomes corretos para o preview
            cat_obj = _resolve_categoria(usuario, categoria) if categoria else None
            conta_obj = _resolve_conta(usuario, conta) if conta else None
            cartao_obj = _resolve_cartao(usuario, cartao) if cartao else None
            
            # Listas para Dropdowns no Frontend
            all_cats = list(Categoria.objects.filter(usuario=usuario).order_by('nome').values_list('nome', flat=True))
            all_contas = list(Conta.objects.filter(usuario=usuario).order_by('nome').values_list('nome', flat=True))
            all_cartoes = list(CartaoCredito.objects.filter(usuario=usuario).order_by('nome').values_list('nome', flat=True))

            # Retorna PROPOSTA DE AÇÃO
            return {
                "type": "action_proposal",
                "action": "create_transaction", # FIX: String compativel com JS
                "entity": "transacao",
                "text_fallback": f"Vou criar: {descricao} - R$ {valor} ({data})",
                "data": {
                    "descricao": descricao,
                    "valor": float(valor),
                    "tipo": tipo if tipo else 'D',
                    "data": data,
                    "categoria_nome": cat_obj.nome if cat_obj else None,
                    "conta_id": conta_obj.id if conta_obj else None,
                    "cartao_id": cartao_obj.id if cartao_obj else None,
                    "categoria": cat_obj.nome if cat_obj else "",
                    "conta_nome": conta_obj.nome if conta_obj else None, # Helper para JS
                    "cartao_nome": cartao_obj.nome if cartao_obj else None, # Helper para JS
                    "available_categories": all_cats,
                    "available_accounts": all_contas,
                    "available_cards": all_cartoes
                }
            }

        elif acao == "editar":
            t = None
            if not id:
                # Se não tem ID, tenta pegar a última transação do usuário
                t = Transacao.objects.filter(
                    Q(conta__usuario=usuario) | Q(cartao__usuario=usuario)
                ).order_by('-data', '-id').first()
                if not t:
                    return "Erro: Nenhuma transação encontrada para editar."
            else:
                try:
                    t = Transacao.objects.get(
                        Q(id=id) & (Q(conta__usuario=usuario) | Q(cartao__usuario=usuario))
                    )
                except Transacao.DoesNotExist: 
                    return "❌ Transação não encontrada ou você não tem permissão."
            
            # PROTEÇÃO DE INTEGRIDADE
            if t.fatura_pagamento:
                 return "❌ Erro: Esta transação é um pagamento de fatura e não pode ser editada diretamente."
            if t.categoria and "pagamento fatura" in t.categoria.nome.lower():
                 return "❌ Erro: Transação de 'Pagamento Fatura' não pode ser editada."
            if t.fatura and t.fatura.paga:
                 # Se mudar valor, quebra. No chat, bloqueamos qualquer revisão em fatura paga por segurança.
                 return "❌ Erro: Fatura já paga. Não é possível editar transações pelo Chat."
            
            return {
                "type": "action_proposal",
                "action": "edit_transaction",
                "entity": "transacao",
                "text_fallback": f"Editar transação {t.id}: {descricao or t.descricao}",
                "data": {
                    "id": t.id,
                    "descricao": descricao if descricao else t.descricao,
                    "valor": float(valor) if valor else float(t.valor),
                    "tipo": tipo if tipo else t.tipo,
                    "data": data if data else str(t.data),
                    "categoria_nome": (_resolve_categoria(usuario, categoria).nome if categoria else t.categoria.nome) if (categoria or (t.categoria)) else None,
                    "conta_nome": (_resolve_conta(usuario, conta).nome if conta else t.conta.nome) if (conta or t.conta) else None,
                    "cartao_nome": (_resolve_cartao(usuario, cartao).nome if cartao else t.cartao.nome) if (cartao or t.cartao) else None,
                    "available_categories": list(Categoria.objects.filter(usuario=usuario).order_by('nome').values_list('nome', flat=True)),
                    "available_accounts": list(Conta.objects.filter(usuario=usuario).order_by('nome').values_list('nome', flat=True)),
                    "available_cards": list(CartaoCredito.objects.filter(usuario=usuario).order_by('nome').values_list('nome', flat=True))
                }
            }

        elif acao == "excluir":
            t = None
            if not id:
                # Se não tem ID, tenta pegar a última transação do usuário
                t = Transacao.objects.filter(
                    Q(conta__usuario=usuario) | Q(cartao__usuario=usuario)
                ).order_by('-data', '-id').first()
                if not t:
                    return "Erro: Nenhuma transação encontrada para excluir."
            else:
                try:
                    t = Transacao.objects.get(
                        Q(id=id) & (Q(conta__usuario=usuario) | Q(cartao__usuario=usuario))
                    )
                except Transacao.DoesNotExist: 
                    return "❌ Transação não encontrada ou você não tem permissão."

                # PROTEÇÃO DE INTEGRIDADE
                if t.fatura_pagamento:
                     return "❌ Erro: Pagamento de fatura não pode ser excluído diretamente."
                if t.categoria and "pagamento fatura" in t.categoria.nome.lower():
                     return "❌ Erro: Transação de 'Pagamento Fatura' não pode ser excluída."
                if t.fatura and t.fatura.paga:
                     return "❌ Erro: Transação em fatura paga não pode ser excluída."

            return {
                "type": "action_proposal",
                "action": "delete_transaction",
                "entity": "transacao",
                "text_fallback": f"Tem certeza que deseja excluir: {t.descricao} (R$ {t.valor})?",
                "data": {
                    "id": t.id,
                    "descricao": t.descricao,
                    "valor": float(t.valor),
                    "data": str(t.data)
                }
            }
        
        return "Ação desconhecida."
    except ValueError as e:
        return f"❌ Valor inválido: {str(e)}"
    except Exception as e:
        print(f"[ERRO CHATBOT] {e}")
        return "❌ Erro interno no bot."


# ... (Function buscar_transacoes remains roughly same, skipping re-paste unless needed) ...
# I will use replace_file_content carefully to target the blocks.




def _buscar_transacoes_func(usuario, texto=None, ano=None, mes=None, categoria_id=None, 
                            conta_id=None, cartao_id=None, tipo=None, limit=10, order_by='data_desc'):
    try:
        # DEFINE qs PRIMEIRO
        qs = Transacao.objects.filter(
            Q(conta__usuario=usuario) | Q(cartao__usuario=usuario)
        ).select_related('categoria', 'conta', 'cartao')
        
        # Validações de ownership
        if conta_id:
            if not Conta.objects.filter(id=conta_id, usuario=usuario).exists():
                return "Conta não encontrada ou não pertence a você."
            qs = qs.filter(conta_id=conta_id)
        
        if cartao_id:
            if not CartaoCredito.objects.filter(id=cartao_id, usuario=usuario).exists():
                return "Cartão não encontrado ou não pertence a você."
            qs = qs.filter(cartao_id=cartao_id)
        
        # Resto dos filtros
        if texto: qs = qs.filter(descricao__icontains=texto)
        if ano: qs = qs.filter(data__year=ano)
        if mes: qs = qs.filter(data__month=mes)
        if tipo: qs = qs.filter(tipo=tipo)
        if categoria_id: qs = qs.filter(categoria_id=categoria_id)
        
        # Ordenação
        if order_by == 'data_asc': 
            qs = qs.order_by('data')
        elif order_by == 'valor_desc': 
            qs = qs.order_by('-valor')
        else: 
            qs = qs.order_by('-data')
        
        # Limit
        if limit: 
            qs = qs[:limit]
        
        if not qs.exists(): 
            return "Nenhuma transação encontrada."
        
        txt = f"**Encontrei {len(qs)} transações:**\n"
        for t in qs:
            origem = t.conta.nome if t.conta else (f"Cartão {t.cartao.nome}" if t.cartao else "-")
            txt += f"- [ID:{t.id}] {t.data.strftime('%d/%m/%Y')} | {t.descricao} | R$ {t.valor} | {origem}\n"
        return txt
        
    except Exception as e: 
        return f"Erro busca: {str(e)}"

def _consultar_gastos_detalhados_func(usuario, tipo, ano=None, mes=None, ano2=None, mes2=None, limit=5):
    try:
        qs = Transacao.objects.filter(Q(conta__usuario=usuario) | Q(cartao__usuario=usuario), tipo='D')
        if ano: qs = qs.filter(data__year=ano)
        if mes: qs = qs.filter(data__month=mes)
        
        if tipo == "maiores_gastos":
            top = qs.order_by('-valor')[:limit]
            txt = f"**Top {limit} Gastos:**\n"
            for t in top: txt += f"- {t.descricao}: R$ {t.valor:,.2f}\n"
            return txt if top.exists() else "Sem dados."
            
        elif tipo == "categoria_mais_gasta":
            res = qs.values('categoria__nome').annotate(total=Sum('valor')).order_by('-total').first()
            return f"🏆 Maior gasto: {res['categoria__nome']} (R$ {res['total']:,.2f})" if res else "Sem dados."

        elif tipo == "gastos_por_categoria":
            res = qs.values('categoria__nome').annotate(total=Sum('valor')).order_by('-total')
            txt = "**Por Categoria:**\n"
            for r in res: txt += f"- {r['categoria__nome'] or 'Outros'}: R$ {r['total']:,.2f}\n"
            return txt if res.exists() else "Sem dados."

        elif tipo == "comparar_periodos":
            if not ano2: return "Precisa ano2."
            val1 = qs.aggregate(Sum('valor'))['valor__sum'] or 0
            qs2 = Transacao.objects.filter(Q(conta__usuario=usuario) | Q(cartao__usuario=usuario), tipo='D', data__year=ano2)
            if mes2: qs2 = qs2.filter(data__month=mes2)
            val2 = qs2.aggregate(Sum('valor'))['valor__sum'] or 0
            return f"P1: {val1} | P2: {val2} | Diff: {val1 - val2}"
        
        return "Tipo inválido."
    except Exception as e: return f"Erro: {str(e)}"

def _consultar_fatura_cartao_func(usuario, cartao_id, mes=None, ano=None, detalhes=False):
    try:
        hoje = datetime.now()
        mes = mes or hoje.month
        ano = ano or hoje.year
        
        transacoes = Transacao.objects.filter(cartao_id=cartao_id, cartao__usuario=usuario, data__month=mes, data__year=ano, tipo='D').order_by('data')
        total = transacoes.aggregate(Sum('valor'))['valor__sum'] or 0
        
        card = CartaoCredito.objects.get(id=cartao_id)
        txt = f"💳 **Fatura {card.nome} - {mes}/{ano}**: R$ {total:,.2f}\n"
        if detalhes:
            for t in transacoes: txt += f"- {t.data.strftime('%d/%m')} {t.descricao}: R$ {t.valor}\n"
        return txt
    except Exception as e: return f"Erro fatura: {str(e)}"

def _consultar_resumo_financeiro_func(usuario, tipo, conta_id=None, ano=None, mes=None, modalidade=None):
    try:
        if tipo == "saldo_total":
            total = 0
            txt = "**Saldo das Contas:**\n"
            for c in Conta.objects.filter(usuario=usuario):
                s = c.saldo_atual
                total += s
                txt += f"- {c.nome}: R$ {s:,.2f}\n"
            return txt + f"\n💰 **Total: R$ {total:,.2f}**"

        elif tipo == "saldo_conta":
            if not conta_id: return "Erro: Conta ID obrigatório."
            c = Conta.objects.get(id=conta_id, usuario=usuario)
            return f"💰 Saldo {c.nome}: R$ {c.saldo_atual:,.2f}"

        # Queries de período
        qs = Transacao.objects.filter(Q(conta__usuario=usuario) | Q(cartao__usuario=usuario))
        if ano: qs = qs.filter(data__year=ano)
        if mes: qs = qs.filter(data__month=mes)
        
        # Filtro de Modalidade
        if modalidade == 'debito':
             qs = qs.filter(conta__isnull=False)
        elif modalidade == 'credito':
             qs = qs.filter(cartao__isnull=False)
        # se modalidade == 'todos' ou None, pega tudo (comportamento padrão)


        if tipo == "receitas_periodo":
            val = qs.filter(tipo='R').aggregate(Sum('valor'))['valor__sum'] or 0
            return f"📈 Receitas: R$ {val:,.2f}"
            
        elif tipo == "despesas_periodo":
            val = qs.filter(tipo='D').aggregate(Sum('valor'))['valor__sum'] or 0
            return f"📉 Despesas: R$ {val:,.2f}"

        elif tipo == "balanco_periodo":
            rec = qs.filter(tipo='R').aggregate(Sum('valor'))['valor__sum'] or 0
            desp = qs.filter(tipo='D').aggregate(Sum('valor'))['valor__sum'] or 0
            saldo = rec - desp
            return f"**Balanço:**\n📈 Rec: {rec:,.2f}\n📉 Desp: {desp:,.2f}\n💵 **Res: {saldo:,.2f}**"
            
        return "Tipo desconhecido."
    except Exception as e: return f"Erro: {str(e)}"

def _analise_picos_func(usuario, tipo, data_inicio=None, data_fim=None):
    try:
        qs = Transacao.objects.filter(Q(conta__usuario=usuario) | Q(cartao__usuario=usuario))
        
        # Filtro Tipo
        if tipo == 'receita': qs = qs.filter(tipo='R')
        else: qs = qs.filter(tipo='D')

        # Filtro Data
        if data_inicio: qs = qs.filter(data__gte=data_inicio)
        if data_fim: qs = qs.filter(data__lte=data_fim)

        # Agregação
        res = qs.annotate(mes=TruncMonth('data')).values('mes').annotate(total=Sum('valor')).order_by('-total')[:3]

        if not res: return "Nenhum dado encontrado para o período."

        emoji = "📈" if tipo == "receita" else "📉"
        txt = f"{emoji} **Meses com Maior {tipo.title()}:**\n"
        for r in res:
            m = r['mes'].strftime('%m/%Y') if r['mes'] else 'Data Inválida'
            txt += f"- {m}: R$ {r['total']:,.2f}\n"

        return txt

    except Exception as e: return f"Erro na análise: {str(e)}"

# --- Novas Funções de Gestão de Entidades ---


# --- Novas Funções de Gestão de Entidades ---

def _gerenciar_categoria_func(usuario, acao, id=None, nome=None, nome_original=None):
    try:
        if acao == "criar":
            return {
                "type": "action_proposal",
                "action": "create_category",
                "entity": "categoria",
                "text_fallback": f"Criar categoria: {nome}",
                "data": {"nome": nome}
            }
        elif acao == "editar":
            c = None
            if id:
                 c = Categoria.objects.get(id=id, usuario=usuario)
            elif nome_original:
                 c = Categoria.objects.filter(usuario=usuario, nome__iexact=nome_original.strip()).first()
            
            if not c: return "Categoria não encontrada (informe o ID ou nome atual correto)."

            return {
                "type": "action_proposal",
                "action": "edit_category",
                "entity": "categoria",
                "text_fallback": f"Renomear categoria '{c.nome}' para '{nome}'",
                "data": {"id": c.id, "nome": nome, "novo_nome": nome}
            }
        elif acao == "excluir":
            c = None
            if id:
                 c = Categoria.objects.get(id=id, usuario=usuario)
            elif nome:
                 c = Categoria.objects.filter(usuario=usuario, nome__iexact=nome.strip()).first()
            
            if not c: return "Categoria não encontrada."

            return {
                "type": "action_proposal",
                "action": "delete_category",
                "entity": "categoria",
                "text_fallback": f"Excluir categoria: {c.nome}",
                "data": {"id": c.id, "nome": c.nome}
            }
        return "Ação inválida."
    except Categoria.DoesNotExist: return "Categoria não encontrada."
    except Exception as e: return f"Erro: {str(e)}"

def _gerenciar_conta_func(usuario, acao, id=None, nome=None, nome_original=None, instituicao=None, saldo_inicial=None):
    try:
        if acao == "criar":
            return {
                "type": "action_proposal",
                "action": "create_account",
                "entity": "conta",
                "text_fallback": f"Criar conta: {nome} (Saldo inicial: {saldo_inicial})",
                "data": {"nome": nome, "instituicao": instituicao, "saldo_inicial": float(saldo_inicial) if saldo_inicial else 0}
            }
        elif acao == "editar":
            c = None
            if id:
                c = Conta.objects.get(id=id, usuario=usuario)
            elif nome_original:
                c = Conta.objects.filter(usuario=usuario, nome__iexact=nome_original.strip()).first()
            
            if not c: return "Conta não encontrada."

            return {
                "type": "action_proposal",
                "action": "edit_account",
                "entity": "conta",
                "text_fallback": f"Editar conta {c.nome}",
                "data": {"id": c.id, "nome": nome, "instituicao": instituicao, "saldo_inicial": float(saldo_inicial) if saldo_inicial is not None else None}
            }
        elif acao == "excluir":
            c = None
            if id:
                c = Conta.objects.get(id=id, usuario=usuario)
            elif nome:
                c = Conta.objects.filter(usuario=usuario, nome__iexact=nome.strip()).first()

            if not c: return "Conta não encontrada."

            return {
                "type": "action_proposal",
                "action": "delete_account",
                "entity": "conta",
                "text_fallback": f"Excluir conta: {c.nome}",
                "data": {"id": c.id, "nome": c.nome}
            }
        return "Ação inválida."
    except Conta.DoesNotExist: return "Conta não encontrada."
    except Exception as e: return f"Erro: {str(e)}"

def _gerenciar_cartao_func(usuario, acao, id=None, nome=None, nome_original=None, limite=None, dia_vencimento=None, dia_fechamento=None, bandeira=None):
    try:
        if acao == "criar":
            return {
                "type": "action_proposal",
                "action": "create_card",
                "entity": "cartao",
                "text_fallback": f"Criar cartão: {nome}",
                "data": {
                    "nome": nome, "limite": float(limite), 
                    "dia_vencimento": dia_vencimento, "dia_fechamento": dia_fechamento, "bandeira": bandeira
                }
            }
        elif acao == "editar":
            c = None
            if id:
                 c = CartaoCredito.objects.get(id=id, usuario=usuario)
            elif nome_original:
                 c = CartaoCredito.objects.filter(usuario=usuario, nome__iexact=nome_original.strip()).first()
            
            if not c: return "Cartão não encontrado."

            return {
                "type": "action_proposal",
                "action": "edit_card",
                "entity": "cartao",
                "text_fallback": f"Editar cartão {c.nome or id}",
                "data": {
                    "id": c.id, "nome": nome, "limite": float(limite) if limite else None,
                    "dia_vencimento": dia_vencimento, "dia_fechamento": dia_fechamento, "bandeira": bandeira
                }
            }
        elif acao == "excluir":
            c = None
            if id:
                c = CartaoCredito.objects.get(id=id, usuario=usuario)
            elif nome:
                c = CartaoCredito.objects.filter(usuario=usuario, nome__iexact=nome.strip()).first()

            if not c: return "Cartão não encontrado."

            return {
                "type": "action_proposal",
                "action": "delete_card",
                "entity": "cartao",
                "text_fallback": f"Excluir cartão: {c.nome}",
                "data": {"id": c.id, "nome": c.nome}
            }
        return "Ação inválida."
    except CartaoCredito.DoesNotExist: return "Cartão não encontrado."
    except Exception as e: return f"Erro: {str(e)}"



# ==============================================================================
# 4. REGISTRO DE FERRAMENTAS (MAPPING)
# ==============================================================================

TOOL_MAPPING = {
    'gerenciar_transacao': _gerenciar_transacao_func,
    'buscar_transacoes': _buscar_transacoes_func,
    'consultar_gastos_detalhados': _consultar_gastos_detalhados_func,
    'consultar_fatura_cartao': _consultar_fatura_cartao_func,
    'gerenciar_categoria': _gerenciar_categoria_func,
    'gerenciar_conta': _gerenciar_conta_func,
    'gerenciar_cartao': _gerenciar_cartao_func,
    'gerenciar_cartao': _gerenciar_cartao_func,
    'consultar_resumo_financeiro': _consultar_resumo_financeiro_func,
    'analise_picos': _analise_picos_func
}

# ==============================================================================
# 5. LÓGICA PRINCIPAL (CHAT LOOP)
# ==============================================================================

def gerar_resposta_chatbot(mensagem_usuario, usuario, historico=None):
    """
    Controlador principal do Chatbot.
    Gerencia o ciclo: User -> Model -> Tool -> Model -> User
    """
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        return "❌ Erro: Chave de API do Gemini não configurada."

    client = genai.Client(api_key=api_key)
    
    # 1. Prepara histórico e instruções
    instruction = get_system_instruction(usuario)
    
    contents = []
    if historico:
        # Adiciona últimas 3 trocas (6 mensagens)
        for msg in historico[-6:]:
            role = 'user' if msg['role'] == 'user' else 'model'
            
            # Se for texto simples
            if isinstance(msg['content'], str):
                contents.append(types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=msg['content'])]
                ))
        
    contents.append(types.Content(
        role='user', 
        parts=[types.Part.from_text(text=mensagem_usuario)]
    ))

    # 2. Configuração da Geração
    generate_config = types.GenerateContentConfig(
        system_instruction=instruction,
        temperature=0.5, # média temperatura para precisão em tools
        tools=[types.Tool(function_declarations=tools_schema)] if tools_schema else None
    )

    try:
        # 3. Primeira chamada ao Modelo
        response = client.models.generate_content(
            model='gemini-3.1-flash-lite',
            contents=contents,
            config=generate_config
        )

        # 4. Verifica se o modelo pediu para executar alguma função
        if response.candidates and response.candidates[0].content.parts:
            part = response.candidates[0].content.parts[0]
            
            if part.function_call:
                # O modelo decidiu chamar uma função!
                fc = part.function_call
                nome_funcao = fc.name
                argumentos = {k: v for k, v in fc.args.items()}
                
                # Procura a função no nosso registro
                funcao_python = TOOL_MAPPING.get(nome_funcao)
                
                if funcao_python:
                    try:
                        # Executa a função real
                        resultado = funcao_python(usuario=usuario, **argumentos)
                        
                        # --- INTERRUPÇÃO PARA VISUALIZAÇÃO/CONFIRMAÇÃO ---
                        # Se a função retornou um Dicionário de Proposta, retornamos IMEDIATAMENTE.
                        # Não passamos para o modelo gerar texto.
                        if isinstance(resultado, dict) and resultado.get('type') == 'action_proposal':
                            return resultado
                            
                        # Se for string (resultado normal), serializa para JSON (str)
                        resultado_json = str(resultado)
                        
                    except Exception as e:
                        resultado_json = f"Erro na execução da ferramenta: {str(e)}"
                else:
                    resultado_json = f"Erro: Ferramenta '{nome_funcao}' não encontrada no sistema."

                # 5. Devolve o resultado para o modelo
                # Adiciona a resposta da função ao histórico
                contents.append(response.candidates[0].content) # O pedido da tool
                contents.append(types.Content(
                    role="tool",
                    parts=[types.Part.from_function_response(
                        name=nome_funcao,
                        response={"result": resultado_json}
                    )]
                ))

                # 6. Segunda chamada (Modelo processa o resultado e responde ao user)
                response_final = client.models.generate_content(
                    model='gemini-3.1-flash-lite',
                    contents=contents,
                    config=generate_config
                )
                
                if response_final.candidates and response_final.candidates[0].content.parts:
                   for part in response_final.candidates[0].content.parts:
                       if part.text:
                           return part.text
                return "Desculpe, não consegui processar sua solicitação."

        # Se não houve chamada de função, retorna o texto direto
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.text:
                    return part.text
        return "Desculpe, não consegui processar sua solicitação."

    except Exception as e:
        return f"Desculpe, ocorreu um erro interno: {str(e)}"

def limpar_historico_chat(session):
    """Limpa o histórico do chat da sessão."""
    if 'chat_history' in session:
        del session['chat_history']

def limpar_cache_contexto(usuario):
    """
    Função legado mantida para compatibilidade.
    Anteriormente usada para limpar cache de contexto do usuário.
    Na nova arquitetura 'Tool-Based', o contexto é montado dinamicamente pelas tools,
    então não há cache persistente para invalidar.
    """
    pass
