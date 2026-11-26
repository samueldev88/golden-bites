from django.db import transaction
from django.db.models import F

from .models import Produto


class EstoqueInsuficiente(Exception):
    """Lançada quando não há unidades suficientes de um produto."""

    def __init__(self, produto):
        self.produto = produto
        super().__init__(f"Estoque insuficiente de {produto.nome} (restam {produto.estoque}).")


def baixar_estoque(itens):
    """
    Desconta o estoque dos itens de um pedido.

    itens: iterável de (produto_id, quantidade).
    Tudo ou nada: se um item não tiver estoque, nada é descontado
    e EstoqueInsuficiente é lançada. O desconto é atômico no banco
    (UPDATE condicional), então dois clientes comprando ao mesmo
    tempo não conseguem levar a mesma última unidade.
    """
    with transaction.atomic():
        for produto_id, qtd in itens:
            produto = Produto.objects.get(pk=produto_id)
            if not produto.controla_estoque:
                continue
            atualizados = Produto.objects.filter(
                pk=produto_id, controla_estoque=True, estoque__gte=qtd
            ).update(estoque=F("estoque") - qtd)
            if not atualizados:
                produto.refresh_from_db()
                raise EstoqueInsuficiente(produto)


def devolver_estoque(itens):
    """Devolve ao estoque as unidades de um pedido cancelado. itens: (produto_id, quantidade)."""
    with transaction.atomic():
        for produto_id, qtd in itens:
            Produto.objects.filter(pk=produto_id, controla_estoque=True).update(
                estoque=F("estoque") + qtd
            )