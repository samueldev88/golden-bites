from django.urls import path

from . import views

app_name = "catalogo"

urlpatterns = [
    path("", views.home, name="home"),
    path("catalogo/", views.catalogo, name="catalogo"),
    path("produto/<slug:slug>/", views.produto, name="produto"),
    path("sobre/", views.sobre, name="sobre"),
    path("politicas/", views.politicas, name="politicas"),
]