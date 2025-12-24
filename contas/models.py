from django.db import models
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


class Transacao(models.Model):
    TIPO_CHOICES = (
        ('R', 'Receita'),
        ('D', 'Despesa'),
    )

    conta = models.ForeignKey(Conta, on_delete=models.CASCADE)
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

    def save(self, *args, **kwargs):
        # Gera o hash automaticamente antes de salvar se não existir
        if not self.hash_id:
            # Cria uma string única: DATA + VALOR + DESCRIÇÃO
            string_unica = f"{self.data}{self.valor}{self.descricao}"
            self.hash_id = hashlib.md5(string_unica.encode('utf-8')).hexdigest()

        super().save(*args, **kwargs)