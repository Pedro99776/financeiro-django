from rest_framework import serializers
from django.db.models import Sum
from datetime import datetime
from decimal import Decimal
from .models import Transacao, Categoria, Conta, CartaoCredito, FaturaCredito, Objetivo, Orcamento


class CategoriaSerializer(serializers.ModelSerializer):
    """Serializer para Categorias"""
    class Meta:
        model = Categoria
        fields = ['id', 'nome']
        read_only_fields = ['id']


class ContaSerializer(serializers.ModelSerializer):
    """Serializer para Contas"""

    class Meta:
        model = Conta
        fields = ['id', 'nome', 'instituicao', 'saldo_inicial', 'saldo_atual']
        read_only_fields = ['id', 'saldo_atual']



class FaturaCreditoSerializer(serializers.ModelSerializer):
    """Serializer para Faturas"""
    status = serializers.SerializerMethodField()
    
    class Meta:
        model = FaturaCredito
        fields = ['id', 'mes_referencia', 'data_fechamento', 'data_vencimento', 'valor_total', 'paga', 'data_pagamento', 'status']

    def get_status(self, obj):
        hoje = datetime.now().date()
        if obj.paga:
            return "Paga"
        elif hoje > obj.data_vencimento:
            return "Atrasada"
        elif hoje > obj.data_fechamento:
            return "Fechada"
        else:
            return "Aberta"


class CartaoCreditoSerializer(serializers.ModelSerializer):
    """Serializer para Cartões de Crédito"""
    class Meta:
        model = CartaoCredito
        fields = ['id', 'nome', 'limite', 'dia_fechamento', 'dia_vencimento', 'conta_pagamento', 'bandeira', 'ativo']
        read_only_fields = ['id']


class TransacaoSerializer(serializers.ModelSerializer):
    """Serializer para Transações (Leitura/Escrita Padrão)"""
    categoria_nome = serializers.CharField(source='categoria.nome', read_only=True, allow_null=True)
    conta_nome = serializers.CharField(source='conta.nome', read_only=True, allow_null=True)
    cartao_nome = serializers.CharField(source='cartao.nome', read_only=True, allow_null=True)
    
    # Campos para resolução de conflito em faturas pagas
    resolution = serializers.CharField(write_only=True, required=False)
    conta_resolucao_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = Transacao
        fields = [
            'id', 'data', 'descricao', 'valor', 'tipo',
            'categoria', 'categoria_nome',
            'conta', 'conta_nome',
            'cartao', 'cartao_nome',
            'resolution', 'conta_resolucao_id'
        ]
        read_only_fields = ['id']


class TransacaoCreateSerializer(serializers.Serializer):
    """Serializer otimizado para interação via chatbot / IA"""
    id = serializers.IntegerField(read_only=True)
    descricao = serializers.CharField(max_length=200)
    valor = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0.01)
    tipo = serializers.ChoiceField(choices=[('D', 'Despesa'), ('R', 'Receita')])
    
    # Campos opcionais (allow_blank para permitir string vazia do frontend)
    categoria_nome = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    conta_nome = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    cartao_nome = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    
    data = serializers.DateField(required=False)

    def validate(self, data):
        """Validações customizadas"""
        # Se não vier data, usa hoje
        if not data.get('data'):
            data['data'] = datetime.now().date()

        return data

    def create(self, validated_data):
        """Cria transação com lookup inteligente de categoria/conta"""
        # Remove usuario do validated_data para não quebrar o create (injetado pelo perform_create)
        validated_data.pop('usuario', None)
        
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

        # Buscar cartão (Novo)
        cartao_nome = validated_data.pop('cartao_nome', None)
        cartao = None
        if cartao_nome:
            cartao = CartaoCredito.objects.filter(usuario=usuario, nome__iexact=cartao_nome).first()
            if cartao:
                conta = None # Prioridade para cartão

        # Buscar conta (apenas se não tiver cartão)
        conta_nome = validated_data.pop('conta_nome', None)
        if not cartao:
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
        else:
            conta = None # Garante Null se for Cartão

        # Criar transação
        transacao = Transacao.objects.create(
            categoria=categoria,
            conta=conta,
            cartao=cartao, # Novo
            **validated_data
        )

        return transacao

    def update(self, instance, validated_data):
        """Atualiza transação com lookup inteligente de categoria/conta"""
        usuario = self.context['request'].user
        
        # 1. Atualizar campos simples
        instance.descricao = validated_data.get('descricao', instance.descricao)
        instance.valor = validated_data.get('valor', instance.valor)
        instance.tipo = validated_data.get('tipo', instance.tipo)
        instance.data = validated_data.get('data', instance.data)

        # 2. Resolver Categoria (se fornecida)
        if 'categoria_nome' in validated_data:
            categoria_nome = validated_data.get('categoria_nome')
            if categoria_nome:
                categoria, _ = Categoria.objects.get_or_create(nome=categoria_nome, usuario=usuario)
                instance.categoria = categoria
            # Se vier vazio, não altera ou seta null? No chatbot.js, sempre enviamos o valor do input.
            # Vamos assumir que se o usuário limpar o input, ele quer remover a categoria?
            # Ou manter a anterior? Por segurança, se string vazia, remove categoria.
            elif categoria_nome == "":
                 instance.categoria = None

        # 3. Resolver Conta/Cartão (se fornecidos)
        # Lógica: Se vier cartao_nome, tenta setar cartão e limpar conta.
        # Se vier conta_nome, tenta setar conta e limpar cartão.
        # O frontend envia ambos? O dropdown seleciona um. O outro vem vazio.
        
        cartao_nome = validated_data.get('cartao_nome')
        conta_nome = validated_data.get('conta_nome')

        if cartao_nome:
            cartao = CartaoCredito.objects.filter(usuario=usuario, nome__iexact=cartao_nome).first()
            if cartao:
                instance.cartao = cartao
                instance.conta = None # Transação de cartão não tem conta associada diretamente na origem
        
        elif conta_nome:
            try:
                conta = Conta.objects.get(nome__iexact=conta_nome, usuario=usuario)
                instance.conta = conta
                instance.cartao = None
            except Conta.DoesNotExist:
                raise serializers.ValidationError({'conta_nome': f'Conta "{conta_nome}" não encontrada'})

        instance.save()
        return instance


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


class ObjetivoSerializer(serializers.ModelSerializer):
    """Serializer para Objetivos (Cofrinho)"""
    class Meta:
        model = Objetivo
        fields = '__all__'
        read_only_fields = ['usuario', 'valor_atual']

    def create(self, validated_data):
        validated_data['usuario'] = self.context['request'].user
        return super().create(validated_data)

class OrcamentoSerializer(serializers.ModelSerializer):
    """Serializer para Orçamentos (Metas de Gastos)"""
    categoria_nome = serializers.CharField(source='categoria.nome', read_only=True)
    valor_gasto = serializers.SerializerMethodField()
    percentual = serializers.SerializerMethodField()

    class Meta:
        model = Orcamento
        fields = ['id', 'categoria', 'categoria_nome', 'valor_limite', 'valor_gasto', 'percentual']
        read_only_fields = ['id', 'valor_gasto', 'percentual']

    def get_valor_gasto(self, obj):
        hoje = datetime.now()
        gastos = Transacao.objects.filter(
            categoria=obj.categoria, # Categoria já pertence ao usuário
            conta__usuario=obj.usuario,
            data__year=hoje.year,
            data__month=hoje.month,
            tipo='D'
        ).aggregate(Sum('valor'))['valor__sum'] or Decimal(0)
        return gastos

    def get_percentual(self, obj):
        gasto = self.get_valor_gasto(obj)
        if obj.valor_limite > 0:
            return (gasto / obj.valor_limite) * 100
        return 0

    def create(self, validated_data):
        validated_data['usuario'] = self.context['request'].user
        return super().create(validated_data)
