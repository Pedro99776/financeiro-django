from django.db import models
from django.db.models import Sum
from django.contrib.auth.models import User

import hashlib



class Categoria(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    nome = models.CharField(max_length=100)
    dt_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nome


class Conta(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    nome = models.CharField(max_length=100)  # Ex: Nubank, Carteira
    saldo_inicial = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    instituicao = models.CharField(max_length=100, blank=True, null=True)  # Para uso futuro na importação

    def __str__(self):
        return self.nome

    @property
    def saldo_atual(self):
        receitas = self.transacao_set.filter(tipo='R').aggregate(Sum('valor'))['valor__sum'] or 0
        despesas = self.transacao_set.filter(tipo='D').aggregate(Sum('valor'))['valor__sum'] or 0
        return self.saldo_inicial + receitas - despesas



class CartaoCredito(models.Model):
    BANDEIRA_CHOICES = (
        ('VISA', 'Visa'),
        ('MASTERCARD', 'Mastercard'),
    )
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    nome = models.CharField(max_length=100)
    limite = models.DecimalField(max_digits=10, decimal_places=2)
    dia_fechamento = models.IntegerField()
    dia_vencimento = models.IntegerField()
    conta_pagamento = models.ForeignKey(Conta, on_delete=models.SET_NULL, null=True, blank=True)
    bandeira = models.CharField(max_length=20, choices=BANDEIRA_CHOICES)
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.nome} - Fim {self.bandeira}"


class FaturaCredito(models.Model):
    cartao = models.ForeignKey(CartaoCredito, on_delete=models.CASCADE)
    mes_referencia = models.DateField()  # Ex: 2025-01-01
    data_fechamento = models.DateField()
    data_vencimento = models.DateField()
    valor_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    paga = models.BooleanField(default=False)
    data_pagamento = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"Fatura {self.cartao.nome} - {self.mes_referencia.strftime('%m/%Y')}"


class Transacao(models.Model):
    TIPO_CHOICES = (
        ('R', 'Receita'),
        ('D', 'Despesa'),
    )

    conta = models.ForeignKey(Conta, on_delete=models.CASCADE, null=True, blank=True)
    cartao = models.ForeignKey(CartaoCredito, on_delete=models.CASCADE, null=True, blank=True)
    fatura = models.ForeignKey(FaturaCredito, on_delete=models.SET_NULL, null=True, blank=True)
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True)

    data = models.DateField()
    descricao = models.CharField(max_length=200, blank=True, null=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    tipo = models.CharField(max_length=1, choices=TIPO_CHOICES, default='D')
    observacoes = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.descricao} - R$ {self.valor}"

    # Campo para controle de duplicidade
    hash_id = models.CharField(max_length=32, blank=True, null=True, unique=True)

    @staticmethod
    def gerar_hash(data, valor, descricao):
        """Gera um hash único baseado nos dados da transação."""
        # Garante string 'None' se for None, para manter compatibilidade com registros antigos
        # porem idealmente description nao deveria ser None.
        # Check logic: f"{self.descricao}" uses str(self.descricao). 
        # If None -> 'None'.
        
        string_unica = f"{data}{valor}{descricao}"
        return hashlib.md5(string_unica.encode('utf-8')).hexdigest()

    def save(self, *args, **kwargs):
        # Gera o hash automaticamente antes de salvar se não existir
        if not self.hash_id:
            self.hash_id = Transacao.gerar_hash(self.data, self.valor, self.descricao)

        super().save(*args, **kwargs)