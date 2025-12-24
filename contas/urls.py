from django.urls import path
from . import views

urlpatterns = [
    path('', views.listagem_transacoes, name='listagem'),
    path('update/<int:pk>/', views.update_transacao, name='update_transacao'),
    path('delete/<int:pk>/', views.delete_transacao, name='delete_transacao'),
    path('nova-categoria/', views.nova_categoria, name='nova_categoria'),
    path('nova-conta/', views.nova_conta, name='nova_conta'),
    path('importar/', views.importar_extrato, name='importar_extrato'),
    path('nova-transacao/', views.nova_transacao, name='nova_transacao'),

]