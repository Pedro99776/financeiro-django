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
    STATUS_CHOICES = (
        ('ABERTA', 'Aberta'),
        ('FECHADA', 'Fechada'),
        ('PAGA', 'Paga'),
        ('PARCIAL', 'Parcialmente Paga'),
        ('CREDITO', 'Crédito/Excedente'),
        ('INCONSISTENTE', 'Inconsistente')
    )
    cartao = models.ForeignKey(CartaoCredito, on_delete=models.CASCADE)
    mes_referencia = models.DateField()  # Ex: 2025-01-01
    data_fechamento = models.DateField()
    data_vencimento = models.DateField()
    valor_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valor_pago = models.DecimalField(max_digits=10, decimal_places=2, default=0)  
    paga = models.BooleanField(default=False) # Mantido para compatibilidade, mas o status deve virar a verdade
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ABERTA')
    requer_atencao = models.BooleanField(default=False) # Flag para inconsistências
    data_pagamento = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"Fatura {self.cartao.nome} - {self.mes_referencia.strftime('%m/%Y')} [{self.status}]"


class Transacao(models.Model):
    TIPO_CHOICES = (
        ('R', 'Receita'),
        ('D', 'Despesa'),
        ('I', 'Investimento/Aplicação'),
    )

    tipo = models.CharField(max_length=1, choices=TIPO_CHOICES, default='D')
    objetivo = models.ForeignKey('Objetivo', on_delete=models.SET_NULL, null=True, blank=True)
    
    conta = models.ForeignKey(Conta, on_delete=models.CASCADE, null=True, blank=True)
    cartao = models.ForeignKey(CartaoCredito, on_delete=models.CASCADE, null=True, blank=True)
    fatura = models.ForeignKey(FaturaCredito, on_delete=models.SET_NULL, null=True, blank=True)
    fatura_pagamento = models.ForeignKey(FaturaCredito, on_delete=models.SET_NULL, null=True, blank=True, related_name='pagamentos')
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True)

    data = models.DateField()
    descricao = models.CharField(max_length=200, blank=True, null=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    tipo = models.CharField(max_length=1, choices=TIPO_CHOICES, default='D')
    observacoes = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.descricao} - R$ {self.valor}"

    @staticmethod
    def calcular_fatura(cartao, data_transacao):
        """Calcula a fatura e datas baseada no cartão e data."""
        from dateutil.relativedelta import relativedelta
        from datetime import date
        
        dia_fechamento = cartao.dia_fechamento
        dia_vencimento = cartao.dia_vencimento

        if data_transacao.day < dia_fechamento:
            data_base = data_transacao
        else:
            data_base = data_transacao + relativedelta(months=1)

        mes_referencia = date(data_base.year, data_base.month, 1)
        
        try:
            fechamento_calc = date(data_base.year, data_base.month, dia_fechamento)
        except ValueError: 
            fechamento_calc = data_base + relativedelta(day=31)

        if dia_vencimento > dia_fechamento:
            vencimento_calc = date(fechamento_calc.year, fechamento_calc.month, dia_vencimento)
        else:
            prox_mes = fechamento_calc + relativedelta(months=1)
            try:
                vencimento_calc = date(prox_mes.year, prox_mes.month, dia_vencimento)
            except ValueError:
                vencimento_calc = prox_mes + relativedelta(day=31)
                
        return mes_referencia, fechamento_calc, vencimento_calc


class Objetivo(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    nome = models.CharField(max_length=100)
    descricao = models.TextField(null=True, blank=True)
    valor_alvo = models.DecimalField(max_digits=12, decimal_places=2)
    valor_atual = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    data_limite = models.DateField(null=True, blank=True)
    concluida = models.BooleanField(default=False)
    cor = models.CharField(max_length=7, default="#28a745") # Hex Color
    icone = models.CharField(max_length=50, blank=True, null=True) # FontAwesome class

    def __str__(self):
        return f"{self.nome} ({self.valor_atual}/{self.valor_alvo})"

