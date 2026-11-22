from django.contrib import admin

from .models import Lancamento


@admin.register(Lancamento)
class LancamentoAdmin(admin.ModelAdmin):
    list_display = ("data", "tipo", "categoria", "descricao", "valor")
    list_filter = ("tipo", "categoria")