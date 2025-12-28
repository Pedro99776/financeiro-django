from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Sum, Count, Q
from datetime import datetime
from decimal import Decimal

from .models import Transacao, Categoria, Conta
from .serializers import (
    TransacaoSerializer, TransacaoCreateSerializer,
    CategoriaSerializer, ContaSerializer,
    ResumoFinanceiroSerializer, GastosPorCategoriaSerializer
)


class BaseUserViewSet(viewsets.ModelViewSet):
    """Base ViewSet that filters by user and assigns user on create"""
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(usuario=self.request.user)


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


class TransacaoViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = Transacao.objects.filter(conta__usuario=self.request.user).order_by('-data')

        # Filtros para o Chatbot
        tipo = self.request.query_params.get('tipo')
        categoria = self.request.query_params.get('categoria')
        conta = self.request.query_params.get('conta')
        data_inicio = self.request.query_params.get('data_inicio')
        data_fim = self.request.query_params.get('data_fim')

        if tipo:
            queryset = queryset.filter(tipo=tipo)

        if categoria:
            queryset = queryset.filter(categoria__nome__icontains=categoria)

        if conta:
            queryset = queryset.filter(conta__nome__icontains=conta)

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
