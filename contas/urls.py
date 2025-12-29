from django.contrib.auth.views import LogoutView
from django.urls import path, include  # Added 'include'
from . import views, api_views  # Added 'api_views'
from rest_framework.routers import DefaultRouter  # Added DefaultRouter

# Configuração da API REST
router = DefaultRouter()
router.register(r'api/transacoes', api_views.TransacaoViewSet, basename='api-transacao')
router.register(r'api/categorias', api_views.CategoriaViewSet, basename='api-categoria')
router.register(r'api/contas', api_views.ContaViewSet, basename='api-conta')
router.register(r'api/analytics', api_views.AnalyticsViewSet, basename='api-analytics')

urlpatterns = [
    path('', views.listagem_transacoes, name='listagem'),
    path('nova/', views.nova_transacao, name='nova_transacao'), # Changed from 'nova-transacao/'
    path('nova-categoria/', views.nova_categoria, name='nova_categoria'),
    path('nova-conta/', views.nova_conta, name='nova_conta'),
    path('update/<int:pk>/', views.update_transacao, name='update_transacao'),
    path('delete/<int:pk>/', views.delete_transacao, name='delete_transacao'),
    path('importar/', views.importar_extrato, name='importar_extrato'),
    path('logout/', LogoutView.as_view(next_page='login'), name='logout'), # Retained from original

    # Endpoint legado para gráfico (pode ser substituído pelo api/analytics no futuro)
    path('transacoes-api/', views.transacoes_api, name='transacoes_api'),
    path('gerenciar/', views.gerenciar, name='gerenciar'),
    
    # --- API DRF Router ---Endpoints
    path('api/chat/', views.chat_api, name='chat_api'),
    path('api/chat/limpar/', views.limpar_historico_chat_api, name='limpar_historico_chat'),

    # Inclui rotas do router
    path('', include(router.urls)),
]