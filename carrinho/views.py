from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from catalogo.models import ConfiguracaoLoja, Produto
from fidelidade.services import cliente_do_dispositivo, saldo

from .cart import Carrinho


def _inteiro(valor, padrao=1):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao


def ver(request):
    carrinho = Carrinho(request)
    itens = carrinho.itens()
    subtotal = carrinho.subtotal()
    loja = ConfiguracaoLoja.obter()
    trocas = carrinho.itens_troca(loja)
    return render(request, "carrinho/carrinho.html", {
        "itens": itens,
        "trocas": trocas,
        "pontos_usados": sum(t["pontos"] for t in trocas),
        "subtotal": subtotal,
        "abaixo_do_minimo": subtotal < loja.pedido_minimo,
    })


@require_POST
def adicionar(request, produto_id):
    produto = get_object_or_404(Produto, pk=produto_id, disponivel=True)
    quantidade = max(_inteiro(request.POST.get("quantidade"), 1), 1)
    carrinho = Carrinho(request)
    carrinho.adicionar(produto.id, quantidade)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({
            "ok": True,
            "quantidade": carrinho.dados.get(str(produto.id), 0),
            "quantidade_total": carrinho.quantidade_total,
            "mensagem": f"{produto.nome} adicionado ao carrinho",
        })

    destino = request.POST.get("next", "")
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        return redirect(destino)
    return redirect("carrinho:ver")


@require_POST
def atualizar(request, produto_id):
    produto = get_object_or_404(Produto, pk=produto_id)
    carrinho = Carrinho(request)
    carrinho.definir(produto_id, _inteiro(request.POST.get("quantidade"), 1))
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({
            "ok": True,
            "quantidade": carrinho.dados.get(str(produto.id), 0),
            "quantidade_total": carrinho.quantidade_total,
        })
    return redirect("carrinho:ver")


@require_POST
def remover(request, produto_id):
    Carrinho(request).remover(produto_id)
    messages.info(request, "Item removido do carrinho.")
    return redirect("carrinho:ver")


@require_POST
def trocar(request, produto_id):
    """Coloca 1 unidade do item no carrinho como troca de pontos (só para aparelho de confiança)."""
    config = ConfiguracaoLoja.obter()
    if not config.fidelidade_ativa:
        messages.error(request, "O programa de fidelidade não está ativo no momento.")
        return redirect("fidelidade:pagina")
    cliente = cliente_do_dispositivo(request)
    if cliente is None:
        messages.error(request, "Para trocar pontos, confirme este aparelho na página de Fidelidade.")
        return redirect("fidelidade:pagina")
    produto = get_object_or_404(Produto, pk=produto_id, disponivel=True, permite_troca=True, pontos__gt=0)
    carrinho = Carrinho(request)
    custo = produto.custo_troca(config)
    if saldo(cliente) - carrinho.pontos_reservados(config) < custo:
        messages.error(request, f"Você precisa de {custo} pontos livres para trocar por este item.")
        return redirect("fidelidade:pagina")
    carrinho.adicionar_troca(produto.id)
    messages.success(request, f"{produto.nome} entrou no carrinho como troca de pontos.")
    return redirect("carrinho:ver")


@require_POST
def remover_troca(request, produto_id):
    Carrinho(request).remover_troca(produto_id)
    messages.info(request, "Troca removida do carrinho. Seus pontos continuam com você.")
    return redirect("carrinho:ver")