from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver
from django.db.models import Sum
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from .models import Transacao, FaturaCredito

@receiver(pre_save, sender=Transacao)
def vincular_transacao_a_fatura(sender, instance, **kwargs):
    """
    Antes de salvar uma transação de cartão de crédito:
    1. Calcula a qual fatura ela pertence baseada na data e dia de fechamento.
    2. Cria a fatura se não existir.
    3. Associa a transação à fatura.
    """
    # Se for cartão, sempre verifica/recalcula a fatura (para suportar alteração de data)
    if instance.cartao:
        cartao = instance.cartao
        data_transacao = instance.data
        dia_fechamento = cartao.dia_fechamento
        dia_vencimento = cartao.dia_vencimento

        # Lógica de Fechamento
        if data_transacao.day < dia_fechamento:
            # Pertence à fatura que fecha neste mês
            data_base = data_transacao
        else:
            # Pertence à fatura que fecha no mês seguinte
            data_base = data_transacao + relativedelta(months=1)

        # Mes Referencia: 1º dia do mês do fechamento
        mes_referencia = date(data_base.year, data_base.month, 1)
        
        # Datas calculadas da Fatura
        try:
            fechamento_calc = date(data_base.year, data_base.month, dia_fechamento)
        except ValueError: 
            ultimo_dia = data_base + relativedelta(day=31)
            fechamento_calc = ultimo_dia

        # Lógica de Vencimento
        if dia_vencimento > dia_fechamento:
            vencimento_calc = date(fechamento_calc.year, fechamento_calc.month, dia_vencimento)
        else:
            prox_mes = fechamento_calc + relativedelta(months=1)
            try:
                vencimento_calc = date(prox_mes.year, prox_mes.month, dia_vencimento)
            except ValueError:
                vencimento_calc = prox_mes + relativedelta(day=31)

        # Buscar ou Criar Fatura
        fatura, created = FaturaCredito.objects.get_or_create(
            cartao=cartao,
            mes_referencia=mes_referencia,
            defaults={
                'data_fechamento': fechamento_calc,
                'data_vencimento': vencimento_calc,
                'valor_total': 0
            }
        )
        
        # Só atualiza e recalcula se a fatura mudou
        if instance.fatura != fatura:
            instance.fatura = fatura
            # Nota: O post_save vai cuidar de atualizar os totais da fatura antiga e nova
            # porque a transação mudou de 'dono'.
            
    # Se deixou de ser cartão (ex: mudou para conta), remove fatura
    if not instance.cartao and instance.fatura:
        instance.fatura = None


@receiver(post_save, sender=Transacao)
@receiver(post_delete, sender=Transacao)
def atualizar_valor_fatura(sender, instance, **kwargs):
    """
    Atualiza o valor total da fatura sempre que uma transação vinculada é salva ou excluída.
    """
    if instance.fatura:
        fatura = instance.fatura
        # Recalcula soma (Despesas - Receitas)
        despesas = Transacao.objects.filter(fatura=fatura, tipo='D').aggregate(Sum('valor'))['valor__sum'] or 0
        receitas = Transacao.objects.filter(fatura=fatura, tipo='R').aggregate(Sum('valor'))['valor__sum'] or 0
        fatura.valor_total = despesas - receitas
        fatura.save()

