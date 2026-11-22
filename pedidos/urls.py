from django.urls import path

from . import views

app_name = "pedidos"

urlpatterns = [
    path("finalizar/", views.checkout, name="checkout"),
    path("cep/", views.cep_info, name="cep"),
    path("localizacao/", views.localizacao, name="localizacao"),
    path("cupom/", views.cupom, name="cupom"),
    path("meus/", views.meus_pedidos, name="meus"),
    path("webhook/", views.webhook, name="webhook"),
    path("<str:codigo>/", views.detalhe, name="detalhe"),
    path("<str:codigo>/avaliar/<int:produto_id>/", views.avaliar_produto, name="avaliar_produto"),
    path("<str:codigo>/pagar/", views.pagar, name="pagar"),
    path("<str:codigo>/status/", views.status_pedido, name="status"),
    path("<str:codigo>/rastreio/", views.rastreio, name="rastreio"),
    path("<str:codigo>/chat/", views.chat_lista, name="chat"),
    path("<str:codigo>/chat/enviar/", views.chat_enviar, name="chat_enviar"),
    path("<str:codigo>/verificar/", views.verificar, name="verificar"),
    path("<str:codigo>/retorno/", views.retorno, name="retorno"),
]