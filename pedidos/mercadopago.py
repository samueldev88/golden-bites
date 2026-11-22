"""Integração com o Mercado Pago (Checkout Pro) usando a API REST.

Fluxo: criamos uma "preferência" com o total do pedido, enviamos o cliente para o
checkout do Mercado Pago (Pix ou cartão) e confirmamos o pagamento consultando a API
(webhook e retorno do cliente). Nunca confiamos nos dados recebidos sem consultar a API.
"""
import hashlib
import hmac
import logging
import re
from decimal import Decimal

import requests
from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from .models import Pedido

log = logging.getLogger(__name__)

API = "https://api.mercadopago.com"
API_TIMEOUT = (3.05, 8)
PIX_APENAS = ["credit_card", "debit_card", "prepaid_card", "ticket", "atm"]
CARTAO_APENAS = ["bank_transfer", "ticket", "atm"]


class ErroMercadoPago(Exception):
    pass


def validar_assinatura_webhook(payment_id, request_id, assinatura):
    partes = {}
    for trecho in (assinatura or "").split(","):
        chave, separador, valor = trecho.strip().partition("=")
        if separador:
            partes[chave.strip()] = valor.strip()

    timestamp = partes.get("ts", "")
    assinatura_recebida = partes.get("v1", "")
    if not payment_id or not request_id or not timestamp.isdigit():
        return False
    if not re.fullmatch(r"[a-fA-F0-9]{64}", assinatura_recebida):
        return False

    manifesto = f"id:{str(payment_id).lower()};request-id:{request_id};ts:{timestamp};"
    esperada = hmac.new(
        settings.MP_WEBHOOK_SECRET.encode(),
        manifesto.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(esperada, assinatura_recebida.lower())


def _headers():
    if not settings.MP_ACCESS_TOKEN:
        raise ErroMercadoPago("MP_ACCESS_TOKEN não configurado no arquivo .env.")
    return {
        "Authorization": f"Bearer {settings.MP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _url(nome, *args):
    return settings.SITE_URL.rstrip("/") + reverse(nome, args=args)


def criar_preferencia(pedido):
    """Cria a preferência de pagamento e devolve (id, link_de_pagamento)."""
    excluidos = PIX_APENAS if pedido.forma_pagamento == Pedido.Pagamento.PIX else CARTAO_APENAS
    retorno = _url("pedidos:retorno", pedido.codigo)
    nome, _, sobrenome = pedido.cliente.nome.partition(" ")
    pagador = {"name": nome, "surname": sobrenome}
    if pedido.cliente.email:
        pagador["email"] = pedido.cliente.email

    corpo = {
        "items": [{
            "id": pedido.codigo,
            "title": f"Pedido {pedido.codigo} - Golden Bites",
            "description": ", ".join(f"{i.quantidade}x {i.nome}" for i in pedido.itens.all() if not i.resgate)[:250] or "Entrega",
            "quantity": 1,
            "currency_id": "BRL",
            "unit_price": float(pedido.total),
        }],
        "payer": pagador,
        "external_reference": pedido.codigo,
        "statement_descriptor": "GOLDEN BITES",
        "back_urls": {"success": retorno, "pending": retorno, "failure": retorno},
        "payment_methods": {"excluded_payment_types": [{"id": t} for t in excluidos]},
    }
    # O Mercado Pago só aceita retorno automático e webhook em endereços públicos (https)
    if settings.SITE_URL.startswith("https://"):
        corpo["auto_return"] = "approved"
        if settings.MP_WEBHOOK_SECRET:
            corpo["notification_url"] = _url("pedidos:webhook")

    try:
        resposta = requests.post(
            f"{API}/checkout/preferences", json=corpo, headers=_headers(), timeout=API_TIMEOUT,
        )
    except requests.RequestException as erro:
        log.warning("Mercado Pago indisponível ao criar pagamento do pedido %s", pedido.codigo)
        raise ErroMercadoPago(
            "O pagamento está temporariamente indisponível. Seu pedido continua salvo; tente novamente em instantes."
        ) from erro
    if resposta.status_code not in (200, 201):
        log.error("Mercado Pago recusou a preferência: %s %s", resposta.status_code, resposta.text[:400])
        raise ErroMercadoPago("O Mercado Pago não aceitou o pedido. Tente novamente em instantes.")
    dados = resposta.json()
    return dados["id"], dados["init_point"]


def buscar_pagamento(payment_id):
    try:
        resposta = requests.get(
            f"{API}/v1/payments/{payment_id}", headers=_headers(), timeout=API_TIMEOUT,
        )
    except requests.RequestException as erro:
        raise ErroMercadoPago("Não foi possível consultar o pagamento agora.") from erro
    if resposta.status_code != 200:
        raise ErroMercadoPago(f"Pagamento {payment_id} não encontrado ({resposta.status_code}).")
    return resposta.json()


def buscar_por_referencia(codigo):
    """Pagamentos do pedido (external_reference), do mais recente para o mais antigo."""
    try:
        resposta = requests.get(
            f"{API}/v1/payments/search", headers=_headers(), timeout=API_TIMEOUT,
            params={"external_reference": codigo, "sort": "date_created", "criteria": "desc", "limit": 10},
        )
    except requests.RequestException as erro:
        raise ErroMercadoPago("Não foi possível consultar os pagamentos agora.") from erro
    if resposta.status_code != 200:
        raise ErroMercadoPago(f"Busca de pagamentos falhou ({resposta.status_code}): {resposta.text[:200]}")
    return resposta.json().get("results", [])


def sincronizar_pedido(pedido):
    """Confere no Mercado Pago se o pedido já foi pago. Funciona sem webhook (inclusive em localhost)."""
    pagamentos = buscar_por_referencia(pedido.codigo)
    if not pagamentos:
        return pedido
    aprovado = next((p for p in pagamentos if p.get("status") == "approved"), None)
    return aplicar_pagamento(pedido, aprovado or pagamentos[0])


def conferir_pagamento(pedido, intervalo=8):
    """Versão econômica de sincronizar_pedido: no máximo uma consulta a cada `intervalo` segundos."""
    if not pedido.aguarda_pagamento or not pedido.mp_preference_id or not settings.MP_ACCESS_TOKEN:
        return pedido
    chave = f"mp-conferir:{pedido.codigo}"
    if cache.get(chave):
        return pedido
    cache.set(chave, 1, intervalo)
    try:
        return sincronizar_pedido(pedido)
    except Exception:  # noqa: BLE001
        log.exception("Falha ao conferir o pagamento do pedido %s", pedido.codigo)
        return pedido


def aplicar_pagamento(pedido, dados):
    status = dados.get("status", "")
    pedido.mp_payment_id = str(dados.get("id", ""))
    pedido.mp_status = status
    if status == "approved" and pedido.status == Pedido.Status.AGUARDANDO_PAGAMENTO:
        valor = Decimal(str(dados.get("transaction_amount", "0")))
        if abs(valor - pedido.total) <= Decimal("0.01"):
            pedido.status = Pedido.Status.PAGO
        else:
            log.error("Valor divergente no pedido %s: pago %s, esperado %s", pedido.codigo, valor, pedido.total)
            pedido.mp_status = f"approved (valor diferente: pago {valor}, pedido {pedido.total})"
    pedido.save()
    return pedido


def sincronizar(payment_id):
    """Consulta o pagamento no Mercado Pago e atualiza o pedido correspondente."""
    dados = buscar_pagamento(payment_id)
    pedido = Pedido.objects.filter(codigo=dados.get("external_reference", "")).first()
    if pedido is None:
        return None
    return aplicar_pagamento(pedido, dados)