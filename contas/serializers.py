from rest_framework import serializers
from .models import Transacao, Categoria, Conta


class CategoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Categoria
        fields = ['nome']


class ContaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conta
        fields = ['nome']


class TransacaoSerializer(serializers.ModelSerializer):
    categoria = CategoriaSerializer(read_only=True)
    conta = ContaSerializer(read_only=True)

    class Meta:
        model = Transacao
        fields = ['id', 'data', 'descricao', 'valor', 'tipo', 'categoria', 'conta']

