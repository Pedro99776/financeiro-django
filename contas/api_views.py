from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Sum, Count, Q
from django.shortcuts import get_object_or_404
from datetime import datetime
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
        if fatura.paga:
             return Response({'error': 'Fatura já paga'}, status=400)
             
        conta_id = request.data.get('conta_id')
        if not conta_id:
             return Response({'error': 'Conta de pagamento necessária'}, status=400)
             
        # Lógica de Pagamento
        conta = get_object_or_404(Conta, pk=conta_id, usuario=request.user)
        
        if conta.saldo_atual < fatura.valor_total:
             # Opcional: Permitir saldo negativo? Sim.
             pass
             
        # Criar Transação de Pagamento
        Transacao.objects.create(
            conta=conta,
            descricao=f"Pagamento Fatura {fatura.cartao.nome}",
            valor=fatura.valor_total,
            tipo='D',
            data=datetime.now().date(),
            categoria=Categoria.objects.filter(usuario=request.user, nome="Pagamento de Cartão").first() # Ideal: Categoria 'Pagamento'
        )
        
        fatura.paga = True
        fatura.data_pagamento = datetime.now().date()
        fatura.save()
        
        return Response({'status': 'Fatura paga com sucesso'})



class TransacaoViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save()
        limpar_cache_contexto(self.request.user)

    def perform_update(self, serializer):
        serializer.save()
        limpar_cache_contexto(self.request.user)

    def perform_destroy(self, instance):
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
        # Usa o serializer otimizado para criação (chatbot) no POST
        if self.action == 'create':
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
