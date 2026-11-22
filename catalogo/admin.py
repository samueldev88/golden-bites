from django.contrib import admin

from .models import Categoria, ConfiguracaoLoja, FotoProduto, Produto, SolicitacaoLGPD

admin.site.register(ConfiguracaoLoja)


@admin.register(SolicitacaoLGPD)
class SolicitacaoLGPDAdmin(admin.ModelAdmin):
    list_display = ("nome", "tipo", "status", "criado_em")
    list_filter = ("status", "tipo", "criado_em")
    search_fields = ("nome", "email", "telefone", "codigo_pedido")
    readonly_fields = ("criado_em", "atualizado_em")
    list_editable = ("status",)
    ordering = ("-criado_em",)


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ("nome", "ordem", "ativa")


class FotoInline(admin.TabularInline):
    model = FotoProduto
    extra = 0


@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ("nome", "categoria", "preco", "preco_promocional", "disponivel", "destaque")
    list_filter = ("categoria", "disponivel", "destaque")
    search_fields = ("nome",)
    inlines = [FotoInline]