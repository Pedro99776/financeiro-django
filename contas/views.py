from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from django.db import IntegrityError
from datetime import date, datetime

from .models import Transacao, Categoria, Conta
from .forms import TransacaoForm, CategoriaForm, ContaForm, UploadFileForm
from .utils import importar_extrato_com_ia

from django.db.models import Sum
from django.db.models.functions import TruncDay, TruncMonth
import json

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .serializers import TransacaoSerializer


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

    # --- 2. QUERYSET PRINCIPAL ---
    # ✅ SEGURANÇA: Filtra apenas transações das contas do usuário logado
    transacoes_qs = Transacao.objects.select_related('categoria', 'conta').filter(
        data__year=ano_filtrado,
        conta__usuario=request.user  # ✅ FILTRO CRÍTICO
    ).order_by('-data')

    if not eh_ano_inteiro:
        transacoes_qs = transacoes_qs.filter(data__month=mes_filtrado)

    # --- 3. CÁLCULOS TOTAIS ---
    total_receitas = transacoes_qs.filter(tipo='R').aggregate(Sum('valor'))['valor__sum'] or 0
    total_despesas = transacoes_qs.filter(tipo='D').aggregate(Sum('valor'))['valor__sum'] or 0
    saldo = total_receitas - total_despesas

    # --- 4. DADOS PARA GRÁFICO DE FLUXO (BARRA) ---
    if eh_ano_inteiro:
        dados_agrupados = transacoes_qs.annotate(periodo=TruncMonth('data')).values('periodo', 'tipo').annotate(
            total=Sum('valor')).order_by('periodo')
        formato_data = "%b"
    else:
        dados_agrupados = transacoes_qs.annotate(periodo=TruncDay('data')).values('periodo', 'tipo').annotate(
            total=Sum('valor')).order_by('periodo')
        formato_data = "%d"

    dados_dict = {}
    for item in dados_agrupados:
        label = item['periodo'].strftime(formato_data)
        tipo = item['tipo']
        valor = float(item['total'])
        if label not in dados_dict: dados_dict[label] = {'R': 0, 'D': 0}
        dados_dict[label][tipo] = valor

    grafico_labels = sorted(dados_dict.keys())
    grafico_receitas = [dados_dict[label]['R'] for label in grafico_labels]
    grafico_despesas = [dados_dict[label]['D'] for label in grafico_labels]

    # --- 5. DADOS PARA GRÁFICOS DE ROSCA (CATEGORIAS) ---
    rec_cat = transacoes_qs.filter(tipo='R').values('categoria__nome').annotate(total=Sum('valor')).order_by('-total')
    cat_receitas_labels = [item['categoria__nome'] for item in rec_cat]
    cat_receitas_data = [float(item['total']) for item in rec_cat]

    desp_cat = transacoes_qs.filter(tipo='D').values('categoria__nome').annotate(total=Sum('valor')).order_by('-total')
    cat_despesas_labels = [item['categoria__nome'] for item in desp_cat]
    cat_despesas_data = [float(item['total']) for item in desp_cat]

    # --- 6. SERIALIZER E RESPOSTA ---
    serializer = TransacaoSerializer(transacoes_qs, many=True)

    return Response({
        'transacoes': serializer.data,
        'saldo': saldo,
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
    contexto = {
        'ano_atual': hoje.year,
        'mes_atual': hoje.month,
        'eh_ano_inteiro': request.session.get('filtro_ano_inteiro', False)
    }
    return render(request, 'contas/listagem.html', contexto)


@login_required
def nova_transacao(request):
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
        # ✅ CORREÇÃO: Passa o usuário para o form
        form = TransacaoForm(user=request.user)

    return render(request, 'contas/form_transacao.html', {'form': form})


@login_required
def update_transacao(request, pk):
    # ✅ SEGURANÇA: Garante que só pode editar transações próprias
    transacao = get_object_or_404(Transacao, pk=pk, conta__usuario=request.user)

    if request.method == 'POST':
        form = TransacaoForm(request.POST, instance=transacao, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Transação atualizada com sucesso!")
            return redirect('listagem')
    else:
        form = TransacaoForm(instance=transacao, user=request.user)

    return render(request, 'contas/form.html', {'form': form})


@login_required
def delete_transacao(request, pk):
    # ✅ SEGURANÇA: Garante que só pode deletar transações próprias
    transacao = get_object_or_404(Transacao, pk=pk, conta__usuario=request.user)
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

                # Chama a IA
                try:
                    dados_brutos = importar_extrato_com_ia(arquivo, nomes_categorias)

                    if not dados_brutos:
                        messages.error(request, "A IA não encontrou transações ou houve um erro.")
                        return redirect('importar_extrato')

                    # Serializa dados para a sessão
                    dados_serializaveis = []
                    for item in dados_brutos:
                        item_copy = item.copy()
                        if isinstance(item_copy.get('data'), (date, datetime)):
                            item_copy['data'] = item_copy['data'].strftime('%Y-%m-%d')
                        dados_serializaveis.append(item_copy)

                    request.session['transacoes_temp'] = dados_serializaveis
                    request.session['conta_temp_id'] = conta_id

                    messages.info(request, "Analise os dados abaixo antes de confirmar.")

                    return render(request, 'contas/importar.html', {
                        'form': form,
                        'preview': True,
                        'transacoes_temp': dados_serializaveis,
                        'categorias': categorias
                    })

                except Exception as e:
                    messages.error(request, f"Erro crítico: {e}")
                    return redirect('importar_extrato')

        # --- CENÁRIO 2: USUÁRIO CLICOU EM "CONFIRMAR IMPORTAÇÃO" ---
        elif 'confirmar_dados' in request.POST:
            conta_id = request.session.get('conta_temp_id')

            # ✅ SEGURANÇA: Valida que a conta pertence ao usuário
            conta = get_object_or_404(Conta, id=conta_id, usuario=request.user)

            lista_datas = request.POST.getlist('data')
            lista_descricoes = request.POST.getlist('descricao')
            lista_valores = request.POST.getlist('valor')
            lista_tipos = request.POST.getlist('tipo')
            lista_categorias = request.POST.getlist('categoria')

            count = 0
            try:
                for i in range(len(lista_datas)):
                    cat_id = lista_categorias[i]

                    if cat_id:
                        # ✅ SEGURANÇA: Valida que a categoria pertence ao usuário
                        categoria = get_object_or_404(Categoria, id=cat_id, usuario=request.user)
                    else:
                        categoria, _ = Categoria.objects.get_or_create(
                            nome="Importados",
                            usuario=request.user
                        )

                    Transacao.objects.create(
                        data=lista_datas[i],
                        descricao=lista_descricoes[i],
                        valor=lista_valores[i],
                        tipo=lista_tipos[i],
                        conta=conta,
                        categoria=categoria
                    )
                    count += 1

                # Limpa a sessão
                if 'transacoes_temp' in request.session:
                    del request.session['transacoes_temp']
                if 'conta_temp_id' in request.session:
                    del request.session['conta_temp_id']

                messages.success(request, f"{count} transações importadas com sucesso!")
                return redirect('listagem')

            except Exception as e:
                messages.error(request, f"Erro ao salvar: {e}")
                return redirect('importar_extrato')

        # --- CENÁRIO 3: CANCELAR ---
        elif 'cancelar' in request.POST:
            if 'transacoes_temp' in request.session:
                del request.session['transacoes_temp']
            if 'conta_temp_id' in request.session:
                del request.session['conta_temp_id']
            messages.info(request, "Importação cancelada.")
            return redirect('importar_extrato')

    else:
        # ✅ CORREÇÃO: Passa o usuário para o form
        form = UploadFileForm(user=request.user)

    return render(request, 'contas/importar.html', {'form': form, 'categorias': categorias})