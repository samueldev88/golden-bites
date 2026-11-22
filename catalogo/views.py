from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache

from entregas.models import Bairro, FaixaTaxa

from .forms import SolicitacaoLGPDForm
from .models import Categoria, Produto


def _contexto_entrega():
    faixas = list(FaixaTaxa.objects.filter(ativa=True))
    return {
        "faixas": faixas,
        "limite_km": faixas[-1].km_max if faixas else None,
        "bairros_rapida": Bairro.objects.filter(ativo=True, modalidade=Bairro.RAPIDA),
        "bairros_agendada": Bairro.objects.filter(ativo=True, modalidade=Bairro.AGENDADA),
    }


def home(request):
    destaques = Produto.objects.filter(disponivel=True, destaque=True).prefetch_related("fotos")[:8]
    promocoes = [
        p for p in Produto.objects.filter(disponivel=True, preco_promocional__isnull=False).prefetch_related("fotos")
        if p.em_promocao
    ]
    ctx = {"destaques": destaques, "promocoes": promocoes}
    ctx.update(_contexto_entrega())
    return render(request, "catalogo/home.html", ctx)


def catalogo(request):
    categorias = Categoria.objects.filter(ativa=True)
    produtos = Produto.objects.select_related("categoria").prefetch_related("fotos")
    return render(request, "catalogo/catalogo.html", {"categorias": categorias, "produtos": produtos})


def produto(request, slug):
    """Detalhes do produto: todas as fotos, a descrição completa e o botão de adicionar."""
    item = get_object_or_404(Produto.objects.select_related("categoria").prefetch_related("fotos"), slug=slug)
    relacionados = Produto.objects.filter(disponivel=True).exclude(pk=item.pk).prefetch_related("fotos")
    if item.categoria_id:
        relacionados = relacionados.filter(categoria_id=item.categoria_id)
    resumo_avaliacoes = item.avaliacoes.aggregate(total=Count("id"), media=Avg("nota"))
    pagina_avaliacoes = Paginator(
        item.avaliacoes.select_related("pedido__cliente"), 10,
    ).get_page(request.GET.get("avaliacao_pagina"))
    return render(request, "catalogo/produto.html", {
        "p": item,
        "relacionados": relacionados[:4],
        "avaliacoes": pagina_avaliacoes.object_list,
        "pagina_avaliacoes": pagina_avaliacoes,
        "total_avaliacoes": resumo_avaliacoes["total"],
        "media_avaliacoes": resumo_avaliacoes["media"],
    })


def sobre(request):
    return render(request, "catalogo/sobre.html", _contexto_entrega())


@never_cache
def politicas(request):
    form = SolicitacaoLGPDForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(
            request,
            "Solicitação recebida. A Golden Bites vai verificar as informações e responder pelo contato informado.",
        )
        return redirect(f"{reverse('catalogo:politicas')}#solicitacao-lgpd")
    return render(request, "catalogo/politicas.html", {"form": form}, status=400 if request.method == "POST" else 200)