from django.core.exceptions import ValidationError
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Sum, Count, Q
from django.shortcuts import get_object_or_404
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from decimal import Decimal

from .models import Transacao, Categoria, Conta, CartaoCredito, FaturaCredito
from .serializers import (
    TransacaoSerializer, TransacaoCreateSerializer, 
    CategoriaSerializer, ContaSerializer, CartaoCreditoSerializer,
    ResumoFinanceiroSerializer, GastosPorCategoriaSerializer,
    FaturaCreditoSerializer
)
from .chatbot import limpar_cache_contexto


class BaseUserViewSet(viewsets.ModelViewSet):
    """Base ViewSet that filters by user and assigns user on create"""
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(usuario=self.request.user)
        limpar_cache_contexto(self.request.user)

    def perform_update(self, serializer):
        serializer.save()
        limpar_cache_contexto(self.request.user)

    def perform_destroy(self, instance):
        instance.delete()
        limpar_cache_contexto(self.request.user)


class CategoriaViewSet(BaseUserViewSet):
    serializer_class = CategoriaSerializer

    def get_queryset(self):
        return Categoria.objects.filter(usuario=self.request.user).order_by('nome')

    def perform_destroy(self, instance):
        """
        Ao excluir uma categoria, move as transações para 'Sem Categoria' (ou cria uma)
        para evitar que fiquem com NULL e sumam dos relatórios/extrato.
        """
        user = self.request.user
        # Verifica se tem transações
        if instance.transacao_set.exists():
            # Busca ou cria categoria de fallback
            fallback, _ = Categoria.objects.get_or_create(nome="Sem Categoria", usuario=user)
            
            # Se a categoria a ser excluída for a própria fallback, não tem o que fazer (vai ficar null msm)
            if instance.id != fallback.id:
                instance.transacao_set.update(categoria=fallback)
        
        instance.delete()
        limpar_cache_contexto(user)


class ContaViewSet(BaseUserViewSet):
    serializer_class = ContaSerializer

    def get_queryset(self):
        return Conta.objects.filter(usuario=self.request.user).order_by('nome')

    @action(detail=True, methods=['get'])
    def saldo(self, request, pk=None):
        """Retorna saldo atualizado da conta"""
        conta = self.get_object()
        serializer = self.get_serializer(conta)
        return Response({'id': conta.id, 'nome': conta.nome, 'saldo_atual': serializer.data['saldo_atual']})


class CartaoCreditoViewSet(BaseUserViewSet):
    serializer_class = CartaoCreditoSerializer

    def get_queryset(self):
        return CartaoCredito.objects.filter(usuario=self.request.user).order_by('nome')


class FaturaViewSet(BaseUserViewSet):
    serializer_class = FaturaCreditoSerializer

    def get_queryset(self):
        qs = FaturaCredito.objects.filter(cartao__usuario=self.request.user).order_by('-mes_referencia')
        
        cartao_id = self.request.query_params.get('cartao')
        if cartao_id:
            qs = qs.filter(cartao_id=cartao_id)
            
        mes = self.request.query_params.get('mes') # YYYY-MM
        if mes:
            qs = qs.filter(mes_referencia__startswith=mes) # Simple logic for YYYY-MM-DD or YYYY-MM

        return qs

    @action(detail=True, methods=['post'])
    def pagar(self, request, pk=None):
        fatura = self.get_object()
        fatura = self.get_object()
        
        # Valor a pagar (default: saldo restante)
        saldo_restante = fatura.valor_total - fatura.valor_pago
        valor_pagar = Decimal(request.data.get('valor', saldo_restante))
        
        if valor_pagar <= 0:
             return Response({'error': 'Valor deve ser positivo'}, status=400)
             
        if valor_pagar > saldo_restante:
             if not request.data.get('force_overpay'): # Opcional: permitir pagar a mais?
                 return Response({'error': f'Valor excede o restante da fatura (R$ {saldo_restante})'}, status=400)
             
        conta_id = request.data.get('conta_id')
        if not conta_id:
             return Response({'error': 'Conta de pagamento necessária'}, status=400)
             
        # Lógica de Pagamento
        conta = get_object_or_404(Conta, pk=conta_id, usuario=request.user)
        
        # Garante categoria 'Pagamento de Fatura'
        cat_pgto, _ = Categoria.objects.get_or_create(nome="Pagamento Fatura", usuario=request.user)
        
        # Descrição com Mês (Importante p/ user request)
        mes_str = fatura.mes_referencia.strftime('%m/%Y')
        desc = f"Pagamento Fatura {fatura.cartao.nome} ({mes_str})"
        if valor_pagar < saldo_restante:
            desc += " - Parcial"

        # Criar Transação de Pagamento
        Transacao.objects.create(
            conta=conta,
            categoria=cat_pgto,
            descricao=desc,
            valor=valor_pagar,
            tipo='D',
            data=datetime.now().date(),
            fatura_pagamento=fatura # VINCULO DE SEGURANÇA
        )
        
        # Atualiza Status da Fatura
        fatura.valor_pago += valor_pagar
        fatura.data_pagamento = datetime.now().date() # Data do último pagamento
        
        if fatura.valor_pago >= fatura.valor_total - Decimal('0.01'): # Tolerância de centavos
            fatura.paga = True
            
        fatura.save()
        
        return Response({
            'status': 'Pagamento registrado', 
            'paga': fatura.paga, 
            'saldo_restante': fatura.valor_total - fatura.valor_pago
        })



class TransacaoViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    from rest_framework.exceptions import ValidationError

    def perform_create(self, serializer):
        data = serializer.validated_data
        cartao = data.get('cartao')
        data_tx = data.get('data')
        
        # Validar criação em fatura PAGA
        if cartao and data_tx:
            # Simula a atribuição da fatura
            mes_ref, _, _ = Transacao.calcular_fatura(cartao, data_tx)
            
            # Tenta achar a fatura
            fatura = FaturaCredito.objects.filter(cartao=cartao, mes_referencia=mes_ref).first()
            if fatura and fatura.status in ['PAGA', 'CREDITO']: # Inconsistência
                # Opções: Adicionar na próxima? (Mudar Data)
                # Para simplificar na criação, retornamos erro pedindo revisão.
                raise ValidationError({
                     "code": "INVOICE_PAID_CREATION",
                     "message": f"A fatura de {mes_ref.strftime('%m/%Y')} já está paga. Não é possível adicionar novas compras nela.",
                     "options": [
                         {"key": "add_next", "label": "Adicionar na próxima fatura (Muda data)"}
                     ]
                })

        serializer.save()
        limpar_cache_contexto(self.request.user)

    def perform_update(self, serializer):
        instance = serializer.instance
        resolution = serializer.validated_data.get('resolution')
        conta_resolucao_id = serializer.validated_data.get('conta_resolucao_id')
        
        # 1. Bloqueia edição de transação de pagamento de fatura
        if instance.fatura_pagamento:
             raise ValidationError("Não é permitido editar o pagamento da fatura diretamente. Use a tela de faturas.")
             
        # Check legado por nome da categoria
        if instance.categoria and "pagamento fatura" in instance.categoria.nome.lower():
             raise ValidationError("Não é permitido editar transação de 'Pagamento Fatura'.")

        # 2. Verifica se a transação pertence a uma fatura PAGA
        if instance.fatura and instance.fatura.paga:
             old_val = instance.valor
             new_val = serializer.validated_data.get('valor', instance.valor)
             
             if old_val != new_val:
                 diff = new_val - old_val # Positivo = Aumento, Negativo = Diminuição
                 
                 # Se nenhuma estratégia foi definida, retorna ERRO com OPÇÕES
                 if not resolution:
                     code = "INVOICE_PAID_INCREASE" if diff > 0 else "INVOICE_PAID_DECREASE"
                     options = []
                     if diff > 0:
                         options = [
                             {"key": "pay_diff", "label": f"Pagar a diferença agora (R$ {diff})", "needs_account": True},
                             {"key": "add_next", "label": "Adicionar na próxima fatura"},
                             {"key": "cancel_edit", "label": "Remover/Cancelar edição"}
                         ]
                     else:
                         options = [
                             {"key": "add_next_credit", "label": "Usar na próxima fatura (Crédito)"}, # Default logic usually
                             {"key": "refund", "label": f"Estornar pra conta (Devolve R$ {abs(diff)})", "needs_account": True},
                             {"key": "keep_credit", "label": "Deixar como está (Crédito no cartão)"}
                         ]
                     
                     raise ValidationError({
                         "code": code,
                         "message": "Fatura já paga. Escolha uma ação para a diferença de valor.",
                         "options": options,
                         "diff": diff
                     })

                 # Executa Estratégia de Resolução
                 user = self.request.user
                 
                 if resolution == 'pay_diff': # Opção A (Aumento)
                     if not conta_resolucao_id: raise ValidationError("Conta para pagamento necessária.")
                     conta = get_object_or_404(Conta, pk=conta_resolucao_id, usuario=user)
                     
                     # Cria pagamento da diferença
                     cat_pgto, _ = Categoria.objects.get_or_create(nome="Pagamento Fatura", usuario=user)
                     Transacao.objects.create(
                        conta=conta,
                        categoria=cat_pgto,
                        descricao=f"Pagamento Diferença Fatura {instance.fatura.cartao.nome}",
                        valor=diff,
                        tipo='D',
                        data=datetime.now().date(),
                        fatura_pagamento=instance.fatura
                     )
                     # Atualiza fatura
                     instance.fatura.valor_pago += diff
                     instance.fatura.save()

                 elif resolution == 'add_next': # Opção B (Aumento) -> Move a transação inteira? OU Cria nova?
                     # O pedido diz "Adicionar na próxima". Melhor mover a data PARA O FUTURO.
                     # Mas isso remove da fatura atual. "Paga" ok.
                     # Vamos mover para Hoje (ou amanhã) para cair na fatura aberta.
                     serializer.validated_data['data'] = datetime.now().date()
                     # Isso fará o sistema recalcular a fatura no save() automático se a lógica de atribuição de fatura rodar.
                     # Como Fatura é FK direta, precisamos limpar a FK para que o sistema (signal?) reatribua? 
                     # Por hora, assumindo que mudar a data tira da fatura paga se reatribuirmos.
                     serializer.validated_data['fatura'] = None # Força re-vínculo

                 elif resolution == 'refund': # Opção B (Diminuição)
                     if not conta_resolucao_id: raise ValidationError("Conta para estorno necessária.")
                     conta = get_object_or_404(Conta, pk=conta_resolucao_id, usuario=user)
                     cat_estorno, _ = Categoria.objects.get_or_create(nome="Estorno", usuario=user)
                     Transacao.objects.create(
                        conta=conta,
                        categoria=cat_estorno,
                        descricao=f"Estorno Diferença Fatura {instance.fatura.cartao.nome}",
                        valor=abs(diff),
                        tipo='R', # Receita
                        data=datetime.now().date()
                     )
                     # Diminui valor pago na fatura pois devolvemos pro usuario? 
                     instance.fatura.valor_pago -= abs(diff)
                     instance.fatura.save()

                 elif resolution in ['keep_credit', 'add_next_credit']: 
                     # Opção A/C (Diminuição)
                     # keep_credit: Apenas salva. O valor da fatura diminui, o valor pago se mantém.
                     # Fatura fica com saldo positivo (Crédito).
                     pass 

                 elif resolution == 'cancel_edit':
                     return # Aborta save

        serializer.save()
        limpar_cache_contexto(self.request.user)

    def perform_destroy(self, instance):
        if instance.fatura_pagamento:
             raise ValidationError("Não é permitido excluir o pagamento da fatura diretamente.")
             
        # Check legado
        if instance.categoria and "pagamento fatura" in instance.categoria.nome.lower():
             raise ValidationError("Não é permitido excluir transação de 'Pagamento Fatura'.")
             
        if instance.fatura and instance.fatura.paga:
             raise ValidationError("Não é permitido excluir uma compra de uma fatura já paga.")
             
        instance.delete()
        limpar_cache_contexto(self.request.user)

    def get_queryset(self):
        # Fix: Usar Q object para incluir transações de cartão (sem conta)
        queryset = Transacao.objects.filter(
            Q(conta__usuario=self.request.user) | Q(cartao__usuario=self.request.user)
        ).order_by('-data')

        # Filtros para o Chatbot e API de Faturas
        tipo = self.request.query_params.get('tipo')
        categoria = self.request.query_params.get('categoria')
        conta = self.request.query_params.get('conta')
        cartao = self.request.query_params.get('cartao')
        fatura = self.request.query_params.get('fatura')
        data_inicio = self.request.query_params.get('data_inicio')
        data_fim = self.request.query_params.get('data_fim')

        if tipo:
            queryset = queryset.filter(tipo=tipo)

        if categoria:
            queryset = queryset.filter(categoria__nome__icontains=categoria)

        if conta:
            queryset = queryset.filter(conta__nome__icontains=conta)
            
        if cartao:
            queryset = queryset.filter(cartao__nome__icontains=cartao)
            
        if fatura:
            queryset = queryset.filter(fatura_id=fatura)

        if data_inicio:
            queryset = queryset.filter(data__gte=data_inicio)

        if data_fim:
            queryset = queryset.filter(data__lte=data_fim)

        return queryset

    def get_serializer_class(self):
        # Usa o serializer otimizado para criação (chatbot) no POST e PUT/PATCH (edição simplificada)
        if self.action in ['create', 'update', 'partial_update']:
            return TransacaoCreateSerializer
        return TransacaoSerializer


class AnalyticsViewSet(viewsets.ViewSet):
    """Endpoints de análise para o Chatbot / Dashboard"""
    permission_classes = [permissions.IsAuthenticated]

    def _get_periodo_params(self, request):
        hoje = datetime.now()
        try:
            mes = int(request.query_params.get('mes', hoje.month))
            ano = int(request.query_params.get('ano', hoje.year))
        except ValueError:
            mes, ano = hoje.month, hoje.year
        return mes, ano

    @action(detail=False, methods=['get'])
    def resumo(self, request):
        """Retorna resumo financeiro do mês (Receitas, Despesas, Saldo)"""
        mes, ano = self._get_periodo_params(request)

        transacoes = Transacao.objects.filter(
            conta__usuario=request.user,
            data__year=ano,
            data__month=mes
        )

        receitas = transacoes.filter(tipo='R').aggregate(Sum('valor'))['valor__sum'] or Decimal('0.00')
        despesas = transacoes.filter(tipo='D').aggregate(Sum('valor'))['valor__sum'] or Decimal('0.00')
        saldo = receitas - despesas

        # Breakdown por categoria
        por_categoria = {}
        gastos_cat = transacoes.filter(tipo='D').values(
            'categoria__nome'
        ).annotate(total=Sum('valor')).order_by('-total')

        for item in gastos_cat:
            por_categoria[item['categoria__nome']] = float(item['total'])

        data = {
            'periodo': f"{mes}/{ano}",
            'total_receitas': receitas,
            'total_despesas': despesas,
            'saldo': saldo,
            'por_categoria': por_categoria
        }

        serializer = ResumoFinanceiroSerializer(data)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def gastos_por_categoria(self, request):
        """Retorna gastos agrupados por categoria"""
        mes, ano = self._get_periodo_params(request)

        # Apenas despesas
        qs = Transacao.objects.filter(
            conta__usuario=request.user,
            data__year=ano,
            data__month=mes,
            tipo='D'
        ).values('categoria__nome').annotate(
            total=Sum('valor'),
            quantidade=Count('id')
        ).order_by('-total')

        total_despesas = sum(item['total'] for item in qs)
        # Proteção contra divisão por zero
        total_divisor = total_despesas if total_despesas and total_despesas > 0 else Decimal('1.00')

        resultado = []
        for item in qs:
            resultado.append({
                'categoria': item['categoria__nome'],
                'total': item['total'],
                'percentual': (item['total'] / total_divisor) * 100,
                'quantidade_transacoes': item['quantidade']
            })

        serializer = GastosPorCategoriaSerializer(resultado, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def historico_anual(self, request):
        """Retorna histórico de Receitas vs Despesas dos últimos 12 meses"""
        hoje = datetime.now()
        dados = []
        
        for i in range(11, -1, -1):
            data_ref = hoje - relativedelta(months=i)
            mes = data_ref.month
            ano = data_ref.year
            
            qs = Transacao.objects.filter(
                conta__usuario=request.user,
                data__year=ano,
                data__month=mes
            )
            
            receitas = qs.filter(tipo='R').aggregate(Sum('valor'))['valor__sum'] or 0
            despesas = qs.filter(tipo='D').aggregate(Sum('valor'))['valor__sum'] or 0
            
            dados.append({
                'mes_ano': f"{mes:02d}/{ano}",
                'receitas': receitas,
                'despesas': despesas
            })
            
        return Response(dados)

    @action(detail=False, methods=['get'])
    def maiores_gastos(self, request):
        """Retorna as 5 maiores despesas do mês selecionado"""
        mes, ano = self._get_periodo_params(request)
        
        qs = Transacao.objects.filter(
            conta__usuario=request.user,
            data__year=ano,
            data__month=mes,
            tipo='D'
        ).order_by('-valor')[:5]
        
        resultado = []
        for t in qs:
            resultado.append({
                'descricao': t.descricao,
                'valor': t.valor,
                'data': t.data,
                'categoria': t.categoria.nome if t.categoria else 'Sem Categoria'
            })
            
        return Response(resultado)


from .models import Objetivo
from .serializers import ObjetivoSerializer

class ObjetivoViewSet(viewsets.ModelViewSet):
    """Viewset para Cofrinho/Objetivos"""
    serializer_class = ObjetivoSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Objetivo.objects.filter(usuario=self.request.user)

    @action(detail=True, methods=['post'])
    def depositar(self, request, pk=None):
        objetivo = self.get_object()
        valor = Decimal(request.data.get('valor', 0))
        conta_id = request.data.get('conta_id')
        
        if valor <= 0:
            return Response({'error': 'Valor deve ser positivo'}, status=400)
            
        conta = get_object_or_404(Conta, pk=conta_id, usuario=request.user)
        
        # 1. Cria transação de saída (Investimento)
        Transacao.objects.create(
            conta=conta,
            objetivo=objetivo,
            valor=valor,
            tipo='I', # Investimento (Sai da Conta)
            data=date.today(),
            descricao=f"Depósito: {objetivo.nome}"
        )
        
        # 2. Atualiza Saldo do Objetivo
        objetivo.valor_atual += valor
        objetivo.save()
        
        return Response({'status': 'Depósito realizado', 'valor_atual': objetivo.valor_atual})

    @action(detail=True, methods=['post'])
    def resgatar(self, request, pk=None):
        objetivo = self.get_object()
        valor = Decimal(request.data.get('valor', 0))
        conta_id = request.data.get('conta_id')
        
        if valor <= 0:
            return Response({'error': 'Valor deve ser positivo'}, status=400)
        
        if valor > objetivo.valor_atual:
             return Response({'error': 'Saldo insuficiente no objetivo'}, status=400)

        conta = get_object_or_404(Conta, pk=conta_id, usuario=request.user)
        
        # 1. Cria transação de entrada (Receita de Resgate)
        Transacao.objects.create(
            conta=conta,
            objetivo=objetivo,
            valor=valor,
            tipo='R', # Receita (Entra na Conta)
            data=date.today(),
            descricao=f"Resgate: {objetivo.nome}"
        )
        
        # 2. Atualiza Saldo do Objetivo
        objetivo.valor_atual -= valor
        objetivo.save()
        
        return Response({'status': 'Resgate realizado', 'valor_atual': objetivo.valor_atual})


from .models import Orcamento
from .serializers import OrcamentoSerializer

class OrcamentoViewSet(viewsets.ModelViewSet):
    """Viewset para Orçamentos (Limites de Gastos)"""
    serializer_class = OrcamentoSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Orcamento.objects.filter(usuario=self.request.user)
