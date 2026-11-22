from django.contrib import admin

from .models import Bairro, FaixaTaxa

admin.site.register(FaixaTaxa)


@admin.register(Bairro)
class BairroAdmin(admin.ModelAdmin):
    list_display = ("nome", "modalidade", "distancia_km", "ativo")
    list_filter = ("modalidade", "ativo")
