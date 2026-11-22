from django.contrib import admin

from .models import MovimentoPontos


@admin.register(MovimentoPontos)
class MovimentoPontosAdmin(admin.ModelAdmin):
    list_display = ("cliente", "tipo", "pontos", "pedido", "criado_em")
    list_filter = ("tipo",)