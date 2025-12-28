from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Transacao, Conta
from .chatbot import limpar_cache_contexto

@receiver(post_save, sender=Transacao)
@receiver(post_delete, sender=Transacao)
def invalidar_cache_transacao(sender, instance, **kwargs):
    """
    Invalida o cache do chatbot quando uma transação é criada, editada ou excluída.
    Necessário para o chatbot ter sempre dados frescos.
    """
    # Transacao tem relação com Conta, que tem relação com Usuario
    if instance.conta and instance.conta.usuario:
        limpar_cache_contexto(instance.conta.usuario)


@receiver(post_save, sender=Conta)
@receiver(post_delete, sender=Conta)
def invalidar_cache_conta(sender, instance, **kwargs):
    """
    Invalida o cache do chatbot quando uma conta é alterada.
    """
    if instance.usuario:
        limpar_cache_contexto(instance.usuario)
