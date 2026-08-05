from django.db.models.signals import pre_save, post_save, post_delete
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.db.models import Sum
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from .models import Transacao, FaturaCredito
from .utils import wake_up_PDF_to_MD_HF

@receiver(pre_save, sender=Transacao)
def vincular_transacao_a_fatura(sender, instance, **kwargs):
    """
    1. Rastreia fatura antiga (para atualizar se mudar).
    2. Calcula/Vincula nova fatura (se for cartão).
    """
    # A. Rastrear Fatura Antiga
    instance._old_fatura_pk = None
    instance._old_fatura_pagamento_pk = None
    instance._old_conta_pk = None
    
    if instance.pk:
        try:
            old = Transacao.objects.get(pk=instance.pk)
            instance._old_fatura_pk = old.fatura_id
            instance._old_fatura_pagamento_pk = old.fatura_pagamento_id
            instance._old_conta_pk = old.conta_id
        except Transacao.DoesNotExist:
            pass

    # B. Se for cartão, sempre verifica/recalcula a fatura (para suportar alteração de data)
    if instance.cartao and instance.data: # data is needed
        mes_ref, fechamento, vencimento = Transacao.calcular_fatura(instance.cartao, instance.data)

        # Buscar ou Criar Fatura
        fatura, created = FaturaCredito.objects.get_or_create(
            cartao=instance.cartao,
            mes_referencia=mes_ref,
            defaults={
                'data_fechamento': fechamento,
                'data_vencimento': vencimento,
                'valor_total': 0
            }
        )
        
        # Só atualiza fk se mudou
        if instance.fatura_id != fatura.id:
            instance.fatura = fatura

    # Se deixou de ser cartão, remove fatura
    if not instance.cartao and instance.fatura:
        instance.fatura = None


@receiver(post_save, sender=Transacao)
@receiver(post_delete, sender=Transacao)
def atualizar_valor_fatura(sender, instance, **kwargs):
    """
    Signal Unificado: Atualiza Totais e Status da Fatura.
    Rastreia a fatura ATUAL e a ANTIGA (se houve mudança).
    """
    faturas_ids = set()

    # 1. Identifica IDs de Faturas Afetadas
    if instance.fatura_id: 
        faturas_ids.add(instance.fatura_id)
    if instance.fatura_pagamento_id: 
        faturas_ids.add(instance.fatura_pagamento_id)
    
    # Adiciona as antigas (capturadas no pre_save)
    if getattr(instance, '_old_fatura_pk', None):
        faturas_ids.add(instance._old_fatura_pk)
    if getattr(instance, '_old_fatura_pagamento_pk', None):
        faturas_ids.add(instance._old_fatura_pagamento_pk)
    
    for fid in faturas_ids:
        try:
            fatura = FaturaCredito.objects.get(pk=fid)
            
            # Estado Anterior (para detecção de inconsistência)
            estava_paga = fatura.paga
            
            # A. Calcula Totais
            despesas = Transacao.objects.filter(fatura=fatura, tipo='D').aggregate(Sum('valor'))['valor__sum'] or 0
            receitas = Transacao.objects.filter(fatura=fatura, tipo='R').aggregate(Sum('valor'))['valor__sum'] or 0
            nova_fatura_total = despesas - receitas

            novo_valor_pago = fatura.pagamentos.aggregate(Sum('valor'))['valor__sum'] or 0
            
            # Atualiza valores
            fatura.valor_total = nova_fatura_total
            fatura.valor_pago = novo_valor_pago
            
            # B. Define Status
            saldo = fatura.valor_total - fatura.valor_pago
            hoje = date.today()
            
            # ✅ CORRIGIDO: Inicializa variáveis
            novo_status = 'ABERTA'
            nova_flag_paga = False
            atencao = False  # ← CRÍTICO: Inicializar aqui!

            # Lógica de status
            if saldo <= 0.01 and saldo >= -0.01:
                novo_status = 'PAGA'
                nova_flag_paga = True
                atencao = False  # Tudo ok
                
            elif saldo < -0.01:
                novo_status = 'CREDITO'
                nova_flag_paga = True
                atencao = True  # Pagou mais que devia
                
            elif fatura.valor_pago > 0:
                novo_status = 'PARCIAL'
                nova_flag_paga = False
                atencao = False  # Parcial é normal
                
            else:
                # Nenhum pagamento ainda
                # ✅ NOVO: Detecta atraso
                if hoje > fatura.data_vencimento:
                    novo_status = 'ATRASADA'
                    atencao = True  # Atrasado!
                elif hoje > fatura.data_fechamento:
                    novo_status = 'FECHADA'
                else:
                    novo_status = 'ABERTA'
                
                nova_flag_paga = False
                # atencao já está corretamente setado acima

            # C. Detecção de Inconsistência (Mudança após Paga)
            if estava_paga and not nova_flag_paga:
                # Estava paga, agora não está mais
                # Significa que valor aumentou sem pagamento adicional
                novo_status = 'INCONSISTENTE'
                atencao = True
            
            # Atualiza fatura
            fatura.status = novo_status
            fatura.paga = nova_flag_paga
            fatura.requer_atencao = atencao
            fatura.save()

        except FaturaCredito.DoesNotExist:
            # Fatura foi deletada, ignora
            continue


@receiver(post_save, sender=Transacao)
@receiver(post_delete, sender=Transacao)
def atualizar_saldo_conta(sender, instance, **kwargs):
    """
    Atualiza o saldo atual da conta vinculada à transação
    """
    from .models import Conta
    contas_ids = set()
    if instance.conta_id:
        contas_ids.add(instance.conta_id)
        
    if getattr(instance, '_old_conta_pk', None):
        contas_ids.add(instance._old_conta_pk)
        
    for cid in contas_ids:
        try:
            conta = Conta.objects.get(pk=cid)
            receitas = Transacao.objects.filter(conta=conta, tipo='R').aggregate(Sum('valor'))['valor__sum'] or 0
            despesas = Transacao.objects.filter(conta=conta, tipo__in=['D', 'I']).aggregate(Sum('valor'))['valor__sum'] or 0
            conta.saldo_atual = conta.saldo_inicial + receitas - despesas
            conta.save()
        except Conta.DoesNotExist:
            continue

@receiver(user_logged_in)
def acordar_PDF_TO_MD_hf(sender, user, request, **kwargs):
    """
    Ao fazer login, envia um request em background para o microsserviço
    do Hugging Face para que ele saia do estado 'sleeping'.
    """
    wake_up_PDF_to_MD_HF()