"""Rastreio da entrega: o celular do entregador envia a posição, o cliente acompanha no mapa.

A posição só é guardada e só é mostrada enquanto o pedido está em "Saiu para entrega".
"""
import json
import re
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import Pedido

# "endereco" = achado pelo número; "pino"/"gps" = o cliente marcou no mapa
PONTOS_PRECISOS = {"endereco", "pino", "gps"}


def _numero(valor, minimo, maximo):
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return None
    return n if minimo <= n <= maximo else None


@require_GET
def posicao(request, codigo):
    """O cliente consulta a cada poucos segundos. O código do pedido funciona como segredo."""
    pedido = get_object_or_404(Pedido, codigo=codigo)
    ativo = pedido.status == Pedido.Status.SAIU_ENTREGA
    moto = None
    if ativo and pedido.entregador_lat is not None and pedido.entregador_em:
        moto = {
            "lat": pedido.entregador_lat,
            "lon": pedido.entregador_lon,
            "ha_segundos": int((timezone.now() - pedido.entregador_em).total_seconds()),
        }
    resposta = JsonResponse({"status": pedido.status, "ativo": ativo, "moto": moto})
    resposta["Cache-Control"] = "no-store"
    return resposta


@login_required
@require_POST
def atualizar_posicao(request, codigo):
    """O celular do entregador (logado no painel) envia latitude e longitude."""
    pedido = get_object_or_404(Pedido, codigo=codigo)
    if pedido.status != Pedido.Status.SAIU_ENTREGA:
        return JsonResponse({"ok": False, "erro": "O pedido não está em entrega."}, status=409)
    try:
        corpo = json.loads(request.body)
    except ValueError:
        corpo = {}
    lat = _numero(corpo.get("lat"), -90, 90)
    lon = _numero(corpo.get("lon"), -180, 180)
    if lat is None or lon is None:
        return JsonResponse({"ok": False, "erro": "Posição inválida."}, status=400)
    # update() em vez de save(): não dispara a sincronização de pontos de fidelidade
    Pedido.objects.filter(pk=pedido.pk).update(
        entregador_lat=lat, entregador_lon=lon, entregador_em=timezone.now()
    )
    return JsonResponse({"ok": True})


@login_required
def entregador(request, codigo):
    """Tela do entregador: endereço completo, navegação, WhatsApp e compartilhar localização."""
    pedido = get_object_or_404(Pedido.objects.select_related("cliente"), codigo=codigo)
    endereco = f"{pedido.rua}, {pedido.numero}, {pedido.bairro_nome}"
    if pedido.cep:
        endereco += f", {pedido.cep}"
    telefone = re.sub(r"\D", "", pedido.cliente.telefone)
    if len(telefone) <= 11:
        telefone = "55" + telefone
    ponto_preciso = pedido.destino_lat is not None and pedido.destino_precisao in PONTOS_PRECISOS
    if ponto_preciso:
        destino = f"{pedido.destino_lat},{pedido.destino_lon}"
    else:
        destino = quote(endereco)
    return render(request, "pedidos/entregador.html", {
        "pedido": pedido,
        "url_google": f"https://www.google.com/maps/dir/?api=1&travelmode=bicycling&destination={destino}",
        "url_waze": f"https://waze.com/ul?q={quote(endereco)}&navigate=yes",
        "url_whatsapp": f"https://wa.me/{telefone}",
        "em_entrega": pedido.status == Pedido.Status.SAIU_ENTREGA,
        "ponto_preciso": ponto_preciso,
    })