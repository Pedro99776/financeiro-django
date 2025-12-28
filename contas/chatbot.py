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

📊 DADOS ATUALIZADOS DO USUÁRIO:
{resumo_financeiro}

✅ SUAS CAPACIDADES:
1. Responder perguntas sobre saldo, gastos, receitas e transações
2. Analisar padrões de gastos por categoria
3. Comparar gastos entre períodos
4. Fornecer insights financeiros baseados APENAS nos dados acima
5. Usar Markdown: **negrito** para valores importantes, *itálico* para ênfase

⚠️ LIMITAÇÕES IMPORTANTES:
Você NÃO pode fazer cálculos com dados que não foram fornecidos

🚫 PERGUNTAS NÃO-FINANCEIRAS:
- Se a pergunta não for sobre finanças pessoais, responda educadamente:
  "Sou especializado em ajudar com suas finanças. Posso responder sobre saldo, gastos, receitas ou transações. Como posso ajudar nisso?"
- Exemplo: clima, notícias, esportes → redirecionar para finanças
- NUNCA invente informações sobre outros assuntos

📌 REGRAS DE OURO:
- Use EXATAMENTE os valores fornecidos (não invente números)
- Se um dado não estiver disponível, seja honesto: "Não tenho essa informação no momento"
- Formate valores monetários: R$ 1.234,56
- Mantenha foco em finanças pessoais
"""

    # 3. Monta conversa com histórico
    contents = []
    
    # Adiciona últimas 5 trocas (10 mensagens) para contexto if historico
    if historico:
        for msg in historico[-10:]:
            # Mapeia role 'assistant' (do frontend/app) para 'model' (do Gemini) se necessário
            role = 'user' if msg['role'] == 'user' else 'model'
            contents.append(types.Content(
                role=role,
                parts=[types.Part.from_text(text=msg['content'])]
            ))
    
    # Adiciona mensagem atual
    contents.append(types.Content(
        role='user', 
        parts=[types.Part.from_text(text=mensagem_usuario)]
    ))

    # 4. Chama Gemini
    try:
        # Configuração do modelo
        generate_content_config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.7,
            max_output_tokens=500,
            top_p=0.95,
            top_k=40,
        )

        response = client.models.generate_content(
            model='gemini-2.0-flash', 
            contents=contents,
            config=generate_content_config
        )
        
        resposta_texto = response.text
        
        # Validação básica de resposta
        if not resposta_texto or len(resposta_texto.strip()) < 10:
            return "Desculpe, tive dificuldade em processar sua pergunta. Pode reformular?"
        
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
            txt_transacoes += f"  {icone} {t.data.strftime('%d/%m/%Y')} | {descricao} | {t.categoria.nome} | R$ {t.valor:,.2f}\n"
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

    # === MONTA CONTEXTO FINAL ===
    contexto_final = f"{txt_contas}\n{txt_resumo}\n{txt_transacoes}\n{txt_categorias}"
    
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
