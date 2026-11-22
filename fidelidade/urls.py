from django.urls import path

from . import views

app_name = "fidelidade"

urlpatterns = [
    path("", views.pagina, name="pagina"),
    path("vincular/", views.vincular, name="vincular"),
    path("gerar-codigo-dispositivo/", views.gerar_codigo_dispositivo, name="gerar_codigo_dispositivo"),
    path("novo-codigo/", views.novo_codigo, name="novo_codigo"),
    path("sair/", views.sair, name="sair"),
]