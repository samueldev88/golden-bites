from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "painel"

urlpatterns = [
    path("login/", views.LoginSeguro.as_view(), name="login"),
    path("sair/", auth_views.LogoutView.as_view(next_page="painel:login"), name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("andamento/", views.andamento, name="andamento"),
    path("pedidos/", views.pedidos_lista, name="pedidos"),
    path("pedidos/<str:codigo>/", views.pedido_detalhe, name="pedido_detalhe"),
    path("pedidos/<str:codigo>/avancar/", views.pedido_avancar, name="pedido_avancar"),
    path("entregas/", views.entregas, name="entregas"),
    path("entrega/<str:codigo>/", views.entregador, name="entregador"),
    path("entrega/<str:codigo>/posicao/", views.entregador_posicao, name="entregador_posicao"),
    path("entrega/<str:codigo>/confirmar/", views.entregador_confirmar, name="entregador_confirmar"),
    path("entrega/<str:codigo>/chat/", views.entregador_chat, name="entregador_chat"),
    path("entrega/<str:codigo>/chat/enviar/", views.entregador_chat_enviar, name="entregador_chat_enviar"),
    path("relatorios/", views.relatorios_view, name="relatorios"),
    path("relatorios/exportar/", views.relatorio_exportar, name="relatorio_exportar"),
    path("avaliacoes/", views.avaliacoes, name="avaliacoes"),
    path("fidelidade/", views.fidelidade, name="fidelidade"),
    path("fidelidade/<int:pk>/ajuste/", views.fidelidade_ajuste, name="fidelidade_ajuste"),
    path("fidelidade/<int:pk>/vinculo/", views.fidelidade_vinculo, name="fidelidade_vinculo"),
    path("fidelidade/<int:pk>/aparelhos/remover/", views.fidelidade_remover_aparelhos, name="fidelidade_remover_aparelhos"),
    path("configuracao/", views.ConfiguracaoView.as_view(), name="configuracao"),
    path("produtos/<int:pk>/alternar/<str:campo>/", views.produto_alternar, name="produto_alternar"),
    path("produtos/<int:pk>/promocao/", views.produto_promocao, name="produto_promocao"),
    path("produtos/<int:pk>/fotos/", views.produto_fotos, name="produto_fotos"),
    path("fotos/<int:pk>/remover/", views.foto_remover, name="foto_remover"),
    path("fotos/<int:pk>/mover/<str:direcao>/", views.foto_mover, name="foto_mover"),
] + views.ROTAS_CRUD