from django.urls import path

from . import views

app_name = "carrinho"

urlpatterns = [
    path("", views.ver, name="ver"),
    path("adicionar/<int:produto_id>/", views.adicionar, name="adicionar"),
    path("atualizar/<int:produto_id>/", views.atualizar, name="atualizar"),
    path("remover/<int:produto_id>/", views.remover, name="remover"),
    path("trocar/<int:produto_id>/", views.trocar, name="trocar"),
    path("remover-troca/<int:produto_id>/", views.remover_troca, name="remover_troca"),
]