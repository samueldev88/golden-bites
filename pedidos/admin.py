from django.contrib import admin

from .models import Cliente, Cupom, ItemPedido, Pedido

admin.site.register(Cupom)
admin.site.register(Cliente)


class ItemInline(admin.TabularInline):
    model = ItemPedido
    extra = 0


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "cliente", "modalidade", "status", "total", "criado_em")
    list_filter = ("status", "modalidade")
    search_fields = ("codigo", "cliente__nome", "cliente__telefone")
    inlines = [ItemInline]
