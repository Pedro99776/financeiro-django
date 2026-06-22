from django.http import Http404
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum, Q
from django.db import IntegrityError, transaction
from datetime import date, datetime, timedelta
import calendar
from decimal import Decimal

from .models import Transacao, Categoria, Conta, CartaoCredito, FaturaCredito
from .forms import UploadFileForm, TransacaoForm, CategoriaForm, ContaForm, CartaoCreditoForm
from .utils import importar_extrato_via_microsservico
from .serializers import TransacaoSerializer
from .chatbot import gerar_resposta_chatbot, limpar_historico_chat

# --- API VIEWS (DRF) ---
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Sum
from django.db.models.functions import TruncMonth, TruncDay, ExtractMonth


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chat_api(request):
    """
    Endpoint para conversar com o Chatbot.
    Mantém histórico na sessão do usuário.
    """
    mensagem = request.data.get('message')
    if not mensagem:
        return Response({'error': 'Mensagem vazia'}, status=400)

    # Recupera histórico da sessão
    historico = request.session.get('chat_history', [])

    # Gera resposta usando o módulo chatbot.py
    resposta = gerar_resposta_chatbot(mensagem, request.user, historico)

    # Verifica se é uma proposta de ação (Dicionário) ou Texto simples
    if isinstance(resposta, dict) and resposta.get('type') == 'action_proposal':
        # Se for ação, mandamos o objeto completo para o frontend renderizar o card
        # No histórico, salvamos o texto de fallback para manter a integridade da conversa
        historico.append({'role': 'user', 'content': mensagem})
        historico.append({'role': 'assistant', 'content': resposta.get('text_fallback', 'Proposta de transação gerada.')})
        
        # Atualiza sessão
        request.session['chat_history'] = historico[-20:]
        
        return Response({'response': resposta, 'is_action': True})
    else:
        # Resposta de texto normal
        historico.append({'role': 'user', 'content': mensagem})
        historico.append({'role': 'assistant', 'content': resposta})
        request.session['chat_history'] = historico[-20:]
        
        return Response({'response': resposta, 'is_action': False})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def limpar_historico_chat_api(request):
    """Endpoint para limpar memória do chat"""
    limpar_historico_chat(request.session)
    return Response({'status': 'ok'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def transacoes_api(request):
    hoje = datetime.now()

    # --- 1. LÓGICA DE FILTROS ---
    eh_ano_inteiro = request.GET.get('ano_inteiro') == 'true'

    try:
        ano_filtrado = int(request.GET.get('ano'))
    except (TypeError, ValueError):
        ano_filtrado = hoje.year

    try:
        mes_filtrado = int(request.GET.get('mes'))
    except (TypeError, ValueError):
        mes_filtrado = hoje.month

    # --- NOVOS FILTROS AVANÇADOS ---
    data_inicio = request.GET.get('data_inicio')  # YYYY-MM-DD
    data_fim = request.GET.get('data_fim')
    contas_ids = request.GET.get('contas')  # "1,2,3"
    categorias_ids = request.GET.get('categorias')
    tipo_transacao = request.GET.get('tipo')  # 'R', 'D', ou None

    # ✅ PERSISTÊNCIA: Salva os filtros na sessão do usuário
    request.session['filtro_ano'] = ano_filtrado
    request.session['filtro_mes'] = mes_filtrado
    request.session['filtro_ano_inteiro'] = eh_ano_inteiro

    # --- 2. QUERYSET PRINCIPAL ---
    # ✅ SEGURANÇA: Filtra transações das contas OU cartões do usuário logado
    from django.db.models import Q
    transacoes_qs = Transacao.objects.select_related('categoria', 'conta', 'cartao').filter(
        Q(conta__usuario=request.user) | Q(cartao__usuario=request.user)
    ).order_by('-data')

    # Aplicar filtro de período (Data customizada tem prioridade)
    if data_inicio or data_fim:
        if data_inicio:
            transacoes_qs = transacoes_qs.filter(data__gte=data_inicio)
        
        if data_fim:
            transacoes_qs = transacoes_qs.filter(data__lte=data_fim)
        else:
            # Se forneceu início mas não fim, considera até Hoje (conforme solicitado)
            transacoes_qs = transacoes_qs.filter(data__lte=hoje.date())
    else:
        # Fallback: Ano/Mês tradicional
        transacoes_qs = transacoes_qs.filter(data__year=ano_filtrado)
        if not eh_ano_inteiro:
            transacoes_qs = transacoes_qs.filter(data__month=mes_filtrado)

    # Filtrar por contas e cartões específicos
    if contas_ids or request.GET.get('cartoes'):
        q_filtro = Q()
        
        if contas_ids:
            try:
                ids_contas = [int(id.strip()) for id in contas_ids.split(',') if id.strip()]
                q_filtro |= Q(conta_id__in=ids_contas)
            except ValueError: pass

        cartoes_ids = request.GET.get('cartoes')
        if cartoes_ids:
            try:
                ids_cartoes = [int(id.strip()) for id in cartoes_ids.split(',') if id.strip()]
                q_filtro |= Q(cartao_id__in=ids_cartoes)
            except ValueError: pass
            
        transacoes_qs = transacoes_qs.filter(q_filtro)
    
    # Filtrar por categorias específicas
    if categorias_ids:
        try:
            ids_list = [int(id.strip()) for id in categorias_ids.split(',') if id.strip()]
            transacoes_qs = transacoes_qs.filter(categoria_id__in=ids_list)
        except ValueError:
            pass
    
    # Filtrar por tipo de transação
    if tipo_transacao in ['R', 'D']:
        transacoes_qs = transacoes_qs.filter(tipo=tipo_transacao)

    # --- 3. CÁLCULOS TOTAIS ---
    total_receitas = transacoes_qs.filter(tipo='R').aggregate(Sum('valor'))['valor__sum'] or 0
    total_despesas = transacoes_qs.filter(tipo='D').aggregate(Sum('valor'))['valor__sum'] or 0
    saldo = total_receitas - total_despesas

    # --- 4. DADOS PARA GRÁFICO DE FLUXO (BARRA) ---
    if eh_ano_inteiro:
        # Inicializa os 12 meses com zero para garantir ordem cronológica (Jan -> Dez)
        dados_dict = {m: {'R': 0, 'D': 0} for m in range(1, 13)}

        # Agrupa por número do mês (1 a 12)
        # Limpa ordenação (.order_by()) para garantir que o GROUP BY seja feito apenas pelo mês/tipo
        dados_agrupados = transacoes_qs.order_by().annotate(mes_num=ExtractMonth('data')).values('mes_num', 'tipo').annotate(
            total=Sum('valor'))

        for item in dados_agrupados:
            mes_idx = item['mes_num']
            tipo = item['tipo']
            valor = float(item['total'])
            if mes_idx in dados_dict:
                dados_dict[mes_idx][tipo] += valor

        # Definição manual de labels para garantir PT-BR e ordem correta
        meses_nomes = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
        grafico_labels = meses_nomes
        grafico_receitas = [dados_dict[m]['R'] for m in range(1, 13)]
        grafico_despesas = [dados_dict[m]['D'] for m in range(1, 13)]
    else:
        # 1. Determina o Range de Datas Completo
        dt_start = None
        dt_end = None

        if data_inicio:
             dt_start = datetime.strptime(data_inicio, '%Y-%m-%d').date()
        else:
             dt_start = date(ano_filtrado, mes_filtrado, 1)

        if data_fim:
             dt_end = datetime.strptime(data_fim, '%Y-%m-%d').date()
        else:
             # Se tem inicio mas nao fim, assume ate hoje (conforme filtro qs)
             if data_inicio:
                  dt_end = hoje.date()
             else:
                  # Mes completo
                  _, last_day = calendar.monthrange(ano_filtrado, mes_filtrado)
                  dt_end = date(ano_filtrado, mes_filtrado, last_day)

        # 2. Inicializa dicionário com TODOS os dias do range
        dados_dict_dias = {}
        curr = dt_start
        while curr <= dt_end:
             label = curr.strftime("%d")
             dados_dict_dias[label] = {'R': 0, 'D': 0}
             curr += timedelta(days=1)

        # 3. Busca dados agrupados
        dados_agrupados = transacoes_qs.order_by().annotate(periodo=TruncDay('data')).values('periodo', 'tipo').annotate(
            total=Sum('valor')).order_by('periodo')
        formato_data = "%d"

        # 4. Preenche com valores reais
        for item in dados_agrupados:
            label = item['periodo'].strftime(formato_data)
            tipo = item['tipo']
            valor = float(item['total'])
            
            # Proteção: Se a transação estiver fora do range (improvável pelo filtro, mas possível em edge cases)
            if label in dados_dict_dias:
                dados_dict_dias[label][tipo] += valor

        grafico_labels = sorted(dados_dict_dias.keys())
        grafico_receitas = [dados_dict_dias[label]['R'] for label in grafico_labels]
        grafico_despesas = [dados_dict_dias[label]['D'] for label in grafico_labels]

    # --- 5. DADOS PARA GRÁFICOS DE ROSCA (CATEGORIAS) ---
    rec_cat = transacoes_qs.filter(tipo='R').values('categoria__nome').annotate(total=Sum('valor')).order_by('-total')
    cat_receitas_labels = [item['categoria__nome'] for item in rec_cat]
    cat_receitas_data = [float(item['total']) for item in rec_cat]

    desp_cat = transacoes_qs.filter(tipo='D').values('categoria__nome').annotate(total=Sum('valor')).order_by('-total')
    cat_despesas_labels = [item['categoria__nome'] for item in desp_cat]
    cat_despesas_data = [float(item['total']) for item in desp_cat]

    # --- 6. SALDO EM CAIXA ATUAL (ACUMULADO) ---
    # Soma dos saldos iniciais de todas as contas + todas as receitas e despesas históricas
    contas = Conta.objects.filter(usuario=request.user)
    
    total_inicial = contas.aggregate(Sum('saldo_inicial'))['saldo_inicial__sum'] or 0
    
    # Todas as transações até hoje (para saldo acumulado)
    todas_transacoes = Transacao.objects.filter(conta__usuario=request.user)
    hist_receitas = todas_transacoes.filter(tipo='R').aggregate(Sum('valor'))['valor__sum'] or 0
    hist_despesas = todas_transacoes.filter(tipo='D').aggregate(Sum('valor'))['valor__sum'] or 0
    
    saldo_caixa_atual = total_inicial + hist_receitas - hist_despesas

    # --- 6.1 FATURAS EM ABERTO ---
    faturas_aberto = FaturaCredito.objects.filter(
        cartao__usuario=request.user, 
        paga=False
    ).aggregate(Sum('valor_total'))['valor_total__sum'] or 0

    # --- 7. SERIALIZER E RESPOSTA ---
    serializer = TransacaoSerializer(transacoes_qs, many=True)

    return Response({
        'transacoes': serializer.data,
        'saldo': saldo, # Saldo do período
        'saldo_caixa_atual': saldo_caixa_atual, # Saldo Bancário
        'faturas_aberto': faturas_aberto, # Total de Faturas
        'total_receitas': total_receitas,
        'total_despesas': total_despesas,
        'grafico_labels': grafico_labels,
        'grafico_receitas': grafico_receitas,
        'grafico_despesas': grafico_despesas,
        'cat_receitas_labels': cat_receitas_labels,
        'cat_receitas_data': cat_receitas_data,
        'cat_despesas_labels': cat_despesas_labels,
        'cat_despesas_data': cat_despesas_data,
    })


@login_required
def listagem_transacoes(request):
    # A view agora apenas renderiza o template base.
    # O JavaScript no frontend será responsável por chamar a API e preencher os dados.
    hoje = datetime.now()
    
    # ✅ UX: Recupera filtros da sessão ou usa defaults (Data atual)
    ano_filtrado = request.session.get('filtro_ano', hoje.year)
    mes_filtrado = request.session.get('filtro_mes', hoje.month)
    eh_ano_inteiro = request.session.get('filtro_ano_inteiro', False)

    contexto = {
        'ano_atual': ano_filtrado,    # Nome da variável no template é 'ano_atual', mas agora reflete o filtro
        'mes_atual': mes_filtrado,
        'eh_ano_inteiro': eh_ano_inteiro
    }
    return render(request, 'contas/listagem.html', contexto)


@login_required
def nova_transacao(request):
    # Verifica inicial: Usuário tem onde lançar?
    tem_conta = Conta.objects.filter(usuario=request.user).exists()
    tem_cartao = CartaoCredito.objects.filter(usuario=request.user).exists()

    if not tem_conta and not tem_cartao:
        messages.warning(request, "Você precisa criar uma Conta ou Cartão antes de lançar transações! Redirecionamos você para o gerenciamento.")
        return redirect('gerenciar')

    if request.method == 'POST':
        # ✅ CORREÇÃO: Passa o usuário para o form
        form = TransacaoForm(request.POST, user=request.user)
        if form.is_valid():
            transacao = form.save(commit=False)
            if not transacao.descricao:
                transacao.descricao = "Sem descrição"
            transacao.save()
            messages.success(request, "Transação adicionada com sucesso!")
            return redirect('listagem')
        else:
            # Feedback explícito em caso de erro no POST
            messages.error(request, "Erro ao salvar transação. Verifique os campos e tente novamente.")
    else:
        # ✅ CORREÇÃO: Passa o usuário para o form
        form = TransacaoForm(user=request.user)

    return render(request, 'contas/form_transacao.html', {'form': form})

@login_required
def update_transacao(request, pk):
    # ✅ SEGURANÇA ROBUSTA: Busca a transação e verifica permissão manualmente
    # Isso evita problemas com queries complexas (Q objects) em transações órfãs de conta
    transacao = get_object_or_404(Transacao, pk=pk)
    
    # Verifica se pertence ao usuário (seja via Conta ou Cartão)
    dono = False
    if transacao.conta and transacao.conta.usuario == request.user:
        dono = True
    elif transacao.cartao and transacao.cartao.usuario == request.user:
        dono = True
        
    if not dono:
        raise Http404("Você não tem permissão para editar esta transação.")

    if request.method == 'POST':
        form = TransacaoForm(request.POST, instance=transacao, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Transação atualizada com sucesso!")
            return redirect('listagem')
    else:
        form = TransacaoForm(instance=transacao, user=request.user)

    return render(request, 'contas/form_transacao.html', {'form': form})


@login_required
def delete_transacao(request, pk):
    # ✅ SEGURANÇA ROBUSTA: Busca a transação e verifica permissão manualmente
    transacao = get_object_or_404(Transacao, pk=pk)
    
    # Verifica se pertence ao usuário
    dono = False
    if transacao.conta and transacao.conta.usuario == request.user:
        dono = True
    elif transacao.cartao and transacao.cartao.usuario == request.user:
        dono = True
        
    if not dono:
        raise Http404("Você não tem permissão para excluir esta transação.")
        
    transacao.delete()
    messages.success(request, "Transação excluída com sucesso!")
    return redirect('listagem')


@login_required
def nova_categoria(request):
    if request.method == 'POST':
        form = CategoriaForm(request.POST)
        if form.is_valid():
            categoria = form.save(commit=False)
            categoria.usuario = request.user  # ✅ ASSOCIA AO USUÁRIO LOGADO
            categoria.save()
            messages.success(request, "Categoria criada com sucesso!")
            return redirect('listagem')
    else:
        form = CategoriaForm()

    return render(request, 'contas/form_generico.html', {'form': form, 'titulo': 'Nova Categoria'})


@login_required
def nova_conta(request):
    if request.method == 'POST':
        form = ContaForm(request.POST)
        if form.is_valid():
            conta = form.save(commit=False)
            conta.usuario = request.user  # ✅ ASSOCIA AO USUÁRIO LOGADO
            conta.save()
            messages.success(request, "Conta criada com sucesso!")
            return redirect('listagem')
    else:
        form = ContaForm()

    return render(request, 'contas/form_generico.html', {'form': form, 'titulo': 'Nova Conta'})


@login_required
def importar_extrato(request):
    # ✅ SEGURANÇA: Busca apenas categorias do usuário logado
    categorias = Categoria.objects.filter(usuario=request.user)

    if request.method == 'POST':

        # --- CENÁRIO 1: USUÁRIO ENVIOU O ARQUIVO PDF ---
        if 'arquivo' in request.FILES:
            # ✅ CORREÇÃO: Passa o usuário para o form
            form = UploadFileForm(request.POST, request.FILES, user=request.user)
            if form.is_valid():
                arquivo = request.FILES['arquivo']
                conta_id = request.POST.get('conta')

                # ✅ SEGURANÇA: Valida que a conta pertence ao usuário
                conta = get_object_or_404(Conta, id=conta_id, usuario=request.user)

                # Prepara lista de nomes para a IA
                nomes_categorias = [c.nome for c in categorias]

                # Envia ao microsserviço PDF to MD
                try:
                    dados_brutos = importar_extrato_via_microsservico(arquivo, nomes_categorias)

                    if not dados_brutos:
                        messages.error(request, "O microsserviço não encontrou transações no arquivo. Verifique se o PDF ou CSV contém um extrato bancário válido.")
                        return redirect('importar_extrato')

                    # Serializa dados para a sessão
                    dados_serializaveis = []
                    seen_hashes = set() # Controle de duplicidade no próprio arquivo

                    for item in dados_brutos:
                        item_copy = item.copy()
                        if isinstance(item_copy.get('data'), (date, datetime)):
                            item_copy['data'] = item_copy['data'].strftime('%Y-%m-%d')
                        
                        # Detecção de Potencial Duplicidade (Pagamento de Fatura)
                        desc_upper = (item_copy.get('descricao') or "").upper()
                        # Keywords comuns de pagamento de cartão/fatura
                        keywords = ["FATURA", "CARTAO", "INT ITAU MC", "PAGAMENTO TITULO", "PAGAR FAT", "CREDIT CARD"]
                        if any(k in desc_upper for k in keywords):
                             item_copy['alerta_duplicidade'] = True
                             item_copy['motivo_alerta'] = "Possível pagamento de fatura (Duplicidade)"

                        # Detecção de Duplicidade Exata (Hash)
                        try:
                            # Converte para Decimal para garantir hash idêntico ao Model
                            val_dec = Decimal(str(item_copy.get('valor', 0)))
                            h_check = Transacao.gerar_hash(item_copy['data'], val_dec, item_copy.get('descricao'))
                            
                            is_dup = False
                            if Transacao.objects.filter(hash_id=h_check).exists():
                                is_dup = True
                                item_copy['motivo_alerta'] = "Transação já importada (Idêntica)"
                            elif h_check in seen_hashes:
                                is_dup = True
                                item_copy['motivo_alerta'] = "Duplicada neste arquivo"
                                
                            if is_dup:
                                item_copy['alerta_duplicidade'] = True
                                
                            seen_hashes.add(h_check)
                            
                        except Exception as e:
                            pass

                        dados_serializaveis.append(item_copy)

                    request.session['transacoes_temp'] = dados_serializaveis
                    request.session['conta_temp_id'] = conta_id

                    messages.info(request, "Analise os dados abaixo antes de confirmar.")

                    return render(request, 'contas/importar.html', {
                        'form': form,
                        'preview': True,
                        'transacoes_temp': dados_serializaveis,
                        'categorias': categorias,
                        'cartoes': CartaoCredito.objects.filter(usuario=request.user)
                    })

                except Exception as e:
                    messages.error(request, f"Erro crítico: {e}")
                    return redirect('importar_extrato')

        # --- CENÁRIO 2: USUÁRIO CLICOU EM "CONFIRMAR IMPORTAÇÃO" ---
        elif 'confirmar_dados' in request.POST and 'cancelar' not in request.POST:
            conta_id = request.session.get('conta_temp_id')
            # Busca cartões para uso no loop (fallback se usuário selecionou cartão na tabela)
            
            # ✅ SEGURANÇA: Valida que a conta pertence ao usuário (se houver conta)
            conta = None
            if conta_id:
                conta = get_object_or_404(Conta, pk=conta_id, usuario=request.user)

            # Recupera dados editados pelo usuário
            lista_datas = request.POST.getlist('data')
            lista_descricoes = request.POST.getlist('descricao')
            lista_valores = request.POST.getlist('valor')
            lista_tipos = request.POST.getlist('tipo')
            lista_categorias = request.POST.getlist('categoria')
            lista_cartoes = request.POST.getlist('cartao') # Novo campo

            count = 0
            skipped = 0
            
            try:
                with transaction.atomic():
                    for i in range(len(lista_datas)):
                        # Verifica categoria
                        cat_id = lista_categorias[i]
                        categoria = None
                        
                        if cat_id:
                            try:
                                categoria = Categoria.objects.get(id=cat_id, usuario=request.user)
                            except (Categoria.DoesNotExist, ValueError):
                                pass
                        
                        if not categoria:
                             categoria, _ = Categoria.objects.get_or_create(
                                nome="Importados", usuario=request.user
                            )
                        
                        # Verifica Cartão (Prioridade sobre Conta)
                        cartao_id = lista_cartoes[i] if len(lista_cartoes) > i else None
                        cartao_obj = None
                        conta_final = conta
                        
                        if cartao_id:
                             # Se tem cartão selecionado, ignora a conta principal
                             try:
                                 cartao_obj = CartaoCredito.objects.get(pk=cartao_id, usuario=request.user)
                                 conta_final = None # Transação de cartão não move saldo de conta imediatamente
                             except CartaoCredito.DoesNotExist:
                                 pass
                        
                        if not conta_final and not cartao_obj:
                             # Se não tem nem conta nem cartão (ex: erro no form), ignora ou usa default?
                             # Idealmente deve ter conta_id da sessão.
                             pass

                        # Cria a transação (com tratamento de duplicidade)
                        try:
                            # Converte valor para Decimal para consistência do hash
                            val_dec = Decimal(lista_valores[i])
                            
                            # Converte data string para objeto date
                            # O formato vindo do input type="date" é YYYY-MM-DD
                            data_str = lista_datas[i]
                            data_obj = datetime.strptime(data_str, '%Y-%m-%d').date()
                            
                            # ✅ FIX: Usa savepoint para evitar que erro de duplicidade quebre o loop
                            with transaction.atomic():
                                t = Transacao(
                                    data=data_obj,
                                    descricao=lista_descricoes[i],
                                    valor=val_dec,
                                    tipo=lista_tipos[i],
                                    conta=conta_final,
                                    cartao=cartao_obj, # Novo
                                    categoria=categoria
                                )
                                t.save()
                            count += 1
                        except IntegrityError:
                            skipped += 1
                            continue

                messages.success(request, f"{count} transações importadas com sucesso! ({skipped} duplicadas ignoradas)")
            except Exception as e:
                messages.error(request, f"Erro ao salvar: {str(e)}")

            # Limpa sessão
            if 'transacoes_temp' in request.session: del request.session['transacoes_temp']
            if 'conta_temp_id' in request.session: del request.session['conta_temp_id']

            return redirect('listagem')
        
        # --- CENÁRIO 3: CANCELAR ---
        elif 'cancelar' in request.POST:
            if 'transacoes_temp' in request.session:
                del request.session['transacoes_temp']
            if 'conta_temp_id' in request.session:
                del request.session['conta_temp_id']
            messages.info(request, "Importação cancelada.")
            return redirect('importar_extrato')
            
    # --- GET: Renderiza o Preview ou o Upload ---
    transacoes_temp = request.session.get('transacoes_temp')
    conta_temp_id = request.session.get('conta_temp_id')
    
    context = {
        'form': UploadFileForm(user=request.user),
        'preview': bool(transacoes_temp),
        'transacoes_temp': transacoes_temp or [],
        'cartoes': CartaoCredito.objects.filter(usuario=request.user),
        'categorias': Categoria.objects.filter(usuario=request.user).order_by('nome')
    }
    
    if conta_temp_id:
        try:
            context['conta_selecionada'] = Conta.objects.get(pk=conta_temp_id)
        except: pass

    return render(request, 'contas/importar.html', context)



@login_required
def gerenciar(request):
    """
    Renderiza a página de gerenciamento de Categorias e Contas.
    O frontend (gerenciar.html) se comunica via API.
    """
    return render(request, 'contas/gerenciar.html', {'nbar': 'gerenciar'})


@login_required
def faturas(request):
    """
    Renderiza a página de Faturas.
    """
    return render(request, 'contas/faturas.html', {'nbar': 'faturas'})


@login_required
def objetivos(request):
    """
    Renderiza a página de Objetivos (Cofrinho).
    """
    return render(request, 'contas/objetivos.html', {'nbar': 'objetivos'})
@login_required
def orcamentos(request):
    """
    Renderiza a página de Orçamentos (Metas de Gastos).
    """
    return render(request, 'contas/orcamentos.html', {'nbar': 'orcamentos'})

@login_required
def estatisticas(request):
    """
    Renderiza a página de Estatísticas (Dashboard Avançado).
    """
    return render(request, 'contas/estatisticas.html', {'nbar': 'estatisticas'})
