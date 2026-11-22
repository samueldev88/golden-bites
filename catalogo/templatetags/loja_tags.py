from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def brl(valor):
    """Formata como moeda brasileira: R$ 1.234,50."""
    if valor is None or valor == "":
        return "—"
    try:
        valor = Decimal(valor)
    except (InvalidOperation, TypeError):
        return "—"
    texto = f"{valor:,.2f}"
    texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


@register.filter
def no_carrinho(mapa, produto_id):
    """Quantidade do produto no carrinho (0 se não estiver)."""
    try:
        return int((mapa or {}).get(str(produto_id), 0))
    except (TypeError, ValueError):
        return 0