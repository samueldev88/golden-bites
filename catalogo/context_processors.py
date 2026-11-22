from .models import ConfiguracaoLoja


def loja(request):
    carrinho = request.session.get("carrinho", {})
    trocas = request.session.get("trocas", {})
    quantidade = (sum(carrinho.values()) if isinstance(carrinho, dict) else 0) + \
                 (sum(trocas.values()) if isinstance(trocas, dict) else 0)
    return {
        "loja": ConfiguracaoLoja.obter(), "carrinho_qtd": quantidade,
        "carrinho_mapa": carrinho if isinstance(carrinho, dict) else {},
    }