from rest_framework import serializers
from django.db.models import Sum
from datetime import datetime
from .models import Transacao, Categoria, Conta


class CategoriaSerializer(serializers.ModelSerializer):
    """Serializer para Categorias"""
    class Meta:
        model = Categoria
        fields = ['id', 'nome']
        read_only_fields = ['id']


class ContaSerializer(serializers.ModelSerializer):
    """Serializer para Contas"""
    saldo_atual = serializers.SerializerMethodField()

    class Meta:
        model = Conta
        fields = ['id', 'nome', 'instituicao', 'saldo_inicial', 'saldo_atual']
        read_only_fields = ['id', 'saldo_atual']

    def get_saldo_atual(self, obj):
        """Calcula saldo atual baseado nas transações"""
        receitas = Transacao.objects.filter(
            conta=obj,
            tipo='R'
        ).aggregate(Sum('valor'))['valor__sum'] or 0

        despesas = Transacao.objects.filter(
            conta=obj,
            tipo='D'
        ).aggregate(Sum('valor'))['valor__sum'] or 0

        return float(obj.saldo_inicial + receitas - despesas)


class TransacaoSerializer(serializers.ModelSerializer):
    """Serializer para Transações (Leitura/Escrita Padrão)"""
    categoria_nome = serializers.CharField(source='categoria.nome', read_only=True)
    conta_nome = serializers.CharField(source='conta.nome', read_only=True)

    class Meta:
        model = Transacao
        fields = [
            'id', 'data', 'descricao', 'valor', 'tipo',
            'categoria', 'categoria_nome',
            'conta', 'conta_nome'
        ]
        read_only_fields = ['id']


class TransacaoCreateSerializer(serializers.Serializer):
    """Serializer otimizado para interação via chatbot / IA"""
    descricao = serializers.CharField(max_length=200)
    valor = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0.01)
    tipo = serializers.ChoiceField(choices=[('D', 'Despesa'), ('R', 'Receita')])
    categoria_nome = serializers.CharField(max_length=100, required=False)
    conta_nome = serializers.CharField(max_length=100, required=False)
    data = serializers.DateField(required=False)

    def validate(self, data):
        """Validações customizadas"""
        # Se não vier data, usa hoje
        if not data.get('data'):
            data['data'] = datetime.now().date()

        return data

    def create(self, validated_data):
        """Cria transação com lookup inteligente de categoria/conta"""
        usuario = self.context['request'].user

        # Buscar ou criar categoria
        categoria_nome = validated_data.pop('categoria_nome', None)
        if categoria_nome:
            categoria, _ = Categoria.objects.get_or_create(
                nome=categoria_nome,
                usuario=usuario
            )
        else:
            # Usa categoria padrão "Importados"
            categoria, _ = Categoria.objects.get_or_create(
                nome="Importados",
                usuario=usuario
            )

        # Buscar conta
        conta_nome = validated_data.pop('conta_nome', None)
        if conta_nome:
            try:
                conta = Conta.objects.get(
                    nome__iexact=conta_nome,
                    usuario=usuario
                )
            except Conta.DoesNotExist:
                raise serializers.ValidationError({
                    'conta_nome': f'Conta "{conta_nome}" não encontrada'
                })
        else:
            # Usa primeira conta do usuário se não especificado
            conta = Conta.objects.filter(usuario=usuario).first()
            if not conta:
                raise serializers.ValidationError({
                    'conta_nome': 'Você precisa criar uma conta primeiro'
                })

        # Criar transação
        transacao = Transacao.objects.create(
            categoria=categoria,
            conta=conta,
            **validated_data
        )

        return transacao


class ResumoFinanceiroSerializer(serializers.Serializer):
    """Serializer para resumo financeiro (Analytics)"""
    periodo = serializers.CharField()
    total_receitas = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_despesas = serializers.DecimalField(max_digits=10, decimal_places=2)
    saldo = serializers.DecimalField(max_digits=10, decimal_places=2)
    por_categoria = serializers.DictField()


class GastosPorCategoriaSerializer(serializers.Serializer):
    """Serializer para gastos por categoria (Analytics)"""
    categoria = serializers.CharField()
    total = serializers.DecimalField(max_digits=10, decimal_places=2)
    percentual = serializers.DecimalField(max_digits=5, decimal_places=2)
    quantidade_transacoes = serializers.IntegerField()
