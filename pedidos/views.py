import json
import logging
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from carrinho.cart import Carrinho
from fidelidade.services import (
    aparelho_novo_para_pedido, cliente_do_dispositivo, definir_cookie, formatar_telefone, ip_do_cliente, limitar,
    saldo,
)
from entregas.cep import avaliar, distancia_km, endereco_por_coordenadas, perfil_da_loja, rota_ao_vivo
from entregas.services import minutos_previstos
from catalogo.models import ConfiguracaoLoja, Produto
from catalogo.templatetags.loja_tags import brl

from . import mercadopago as mp
from .forms import AvaliacaoProdutoForm, CheckoutForm
from .models import AvaliacaoProduto, Cupom, Mensagem, Pedido
from .services import criar_pedido, enviar_mensagem, mensagens_depois

log = logging.getLogger(__name__)
SESSAO_PEDIDOS = "pedidos_sessao"


def checkout(request):
    carrinho = Carrinho(request)
    config = ConfiguracaoLoja.obter()
    itens = carrinho.itens()
    trocas = carrinho.itens_troca(config)
    if not itens and not trocas:
        messages.info(request, "Seu carrinho está vazio. Escolha alguns produtos primeiro.")
        return redirect("catalogo:catalogo")

    subtotal = carrinho.subtotal()
    dono = cliente_do_dispositivo(request)  # cliente deste aparelho (se já foi confirmado)

    if request.method == "POST":
        if not limitar(f"checkout:{ip_do_cliente(request)}", 10, 900):
            return HttpResponse("Muitas tentativas de pedido. Aguarde alguns minutos.", status=429)
        form = CheckoutForm(request.POST, config=config, subtotal=subtotal)
        if not config.loja_aberta:
            form.add_error(None, "A loja está fechada para novos pedidos no momento.")
        elif subtotal < config.pedido_minimo:
            form.add_error(None, f"O pedido mínimo é {brl(config.pedido_minimo)}.")
        elif form.is_valid():
            erro = _validar_trocas(trocas, dono, form.cleaned_data["telefone"], config)
            if erro:
                form.add_error(None, erro)
            else:
                try:
                    pedido = criar_pedido(form.cleaned_data, itens, subtotal, cupom=form.cupom_obj,
                                          avaliacao=form.avaliacao, trocas=trocas)
                except ValueError as falha:
                    form.add_error(None, str(falha))
                else:
                    carrinho.limpar()
                    codigos = request.session.get(SESSAO_PEDIDOS, [])
                    if not isinstance(codigos, list):
                        codigos = []
                    codigos = [codigo_salvo for codigo_salvo in codigos if isinstance(codigo_salvo, str)]
                    request.session[SESSAO_PEDIDOS] = [pedido.codigo] + codigos[:19]
                    if pedido.aguarda_pagamento:
                        return redirect("pedidos:pagar", codigo=pedido.codigo)
                    return redirect("pedidos:detalhe", codigo=pedido.codigo)
    else:
        inicial = {}
        if dono:  # aparelho já confirmado: dados do cliente já vêm preenchidos
            primeiro, _, resto = dono.nome.partition(" ")
            inicial = {"nome": primeiro, "sobrenome": resto, "telefone": formatar_telefone(dono.telefone)}
        form = CheckoutForm(config=config, subtotal=subtotal, initial=inicial)

    return render(request, "pedidos/checkout.html", {
        "form": form, "itens": itens, "trocas": trocas, "subtotal": subtotal, "config": config,
        "pontos_usados": sum(t["pontos"] for t in trocas),
    })


def _validar_trocas(trocas, dono, telefone, config):
    """Texto de erro se as trocas de pontos do carrinho não podem ser feitas; vazio se está tudo certo."""
    if not trocas:
        return ""
    if not config.fidelidade_ativa:
        return "O programa de fidelidade está desativado. Remova as trocas de pontos do carrinho."
    if dono is None or dono.telefone != telefone:
        return ("Para trocar pontos, use o aparelho e o WhatsApp confirmados na página de Fidelidade. "
                "Se não for trocar, remova a troca do carrinho.")
    if saldo(dono) < sum(t["pontos"] for t in trocas):
        return "Seu saldo de pontos não cobre as trocas do carrinho. Remova alguma troca."
    return ""


def _ponto(lat, lon):
    """Coordenadas válidas (dentro do Brasil) ou None."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    return {"lat": lat, "lon": lon} if (-34 <= lat <= 6 and -74 <= lon <= -34) else None


def _inteiro(valor, padrao=0):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao


@require_GET
def localizacao(request):
    """Endereço aproximado do ponto do GPS do cliente (preenche rua, número e bairro no checkout)."""
    if not limitar(f"loc:{ip_do_cliente(request)}", 20, 60):
        return JsonResponse({"ok": False}, status=429)
    ponto = _ponto(request.GET.get("lat"), request.GET.get("lon"))
    if ponto is None:
        return JsonResponse({"ok": False}, status=400)
    return JsonResponse({"ok": True, **endereco_por_coordenadas(ponto["lat"], ponto["lon"])})


@require_GET
def cep_info(request):
    """Consulta do CEP no checkout: endereço, distância e tipo de entrega disponível."""
    if not limitar(f"cep:{ip_do_cliente(request)}", 40, 60):
        return JsonResponse({"encontrado": False, "zona": "invalido", "taxa": None,
                             "mensagem": "Muitas consultas seguidas. Aguarde um minuto e tente de novo."}, status=429)
    digitos = re.sub(r"\D", "", request.GET.get("cep", ""))
    if len(digitos) != 8:
        return JsonResponse({"encontrado": False, "zona": "invalido", "taxa": None,
                             "mensagem": "Informe os 8 números do CEP."})
    config = ConfiguracaoLoja.obter()
    resultado = avaliar(digitos, request.GET.get("bairro", ""), config,
                        request.GET.get("numero", ""))
    taxa = resultado.get("taxa")
    resultado["taxa"] = None if taxa is None else float(taxa)
    if resultado.get("zona") == "rapida" and resultado.get("rota_km") is not None:
        # previsão de chegada = agora + preparo + trajeto (ex.: pedido às 22:15, previsão 22:40)
        minutos = minutos_previstos(resultado["rota_km"], config)
        resultado["previsao_min"] = minutos
        resultado["previsao_hora"] = (timezone.localtime() + timedelta(minutes=minutos)).strftime("%H:%M")
    return JsonResponse(resultado)


@require_GET
def cupom(request):
    """Pré-visualização do cupom no checkout (o valor final é sempre recalculado no servidor)."""
    if not limitar(f"cupom:{ip_do_cliente(request)}", 30, 60):
        return JsonResponse({"ok": False, "mensagem": "Muitas tentativas. Aguarde um minuto.", "desconto": 0}, status=429)
    codigo = request.GET.get("codigo", "").strip().upper()
    subtotal = Carrinho(request).subtotal()
    try:
        taxa = Decimal(request.GET["taxa"]) if request.GET.get("taxa") else None
    except InvalidOperation:
        taxa = None
    try:
        obj = Cupom.objects.get(codigo=codigo)
    except Cupom.DoesNotExist:
        return JsonResponse({"ok": False, "mensagem": "Cupom não encontrado.", "desconto": 0})
    ok, mensagem = obj.validar(subtotal)
    if not ok:
        return JsonResponse({"ok": False, "mensagem": mensagem, "desconto": 0})
    return JsonResponse({
        "ok": True, "mensagem": "Cupom aplicado.",
        "desconto": float(obj.desconto_para(subtotal, taxa)),
        "frete_gratis": obj.tipo == Cupom.FRETE,
    })


def _pedido_autorizado(request, codigo):
    pedido = get_object_or_404(Pedido.objects.select_related("cliente"), codigo=codigo)
    codigos = request.session.get(SESSAO_PEDIDOS, [])
    if not isinstance(codigos, list) or codigo not in codigos:
        raise Http404
    return pedido


def detalhe(request, codigo):
    pedido = _pedido_autorizado(request, codigo)
    mp.conferir_pagamento(pedido)  # já atualiza o status se o pagamento foi aprovado
    pedido.garantir_codigo()
    config = ConfiguracaoLoja.obter()
    texto = f"Olá! Sobre o pedido {pedido.codigo} na Golden Bites."
    whatsapp = f"https://wa.me/{config.whatsapp}?text={quote(texto)}" if config.whatsapp else ""
    passos = ["Pedido recebido", "Pago", "Em preparo", "Saiu para entrega", "Entregue"]
    bonus = pedido.movimentos_pontos.filter(tipo="bonus_atraso").first()
    avaliacoes_produtos = list(
        AvaliacaoProduto.objects.filter(pedido=pedido).select_related("produto")
    )
    produtos_avaliados = {avaliacao.produto_id for avaliacao in avaliacoes_produtos}
    produtos_pendentes = []
    produtos_vistos = set()
    if pedido.status == Pedido.Status.ENTREGUE:
        for item in pedido.itens.select_related("produto").filter(produto__isnull=False):
            if item.produto_id not in produtos_avaliados and item.produto_id not in produtos_vistos:
                produtos_pendentes.append(item)
                produtos_vistos.add(item.produto_id)
    cookie_novo = aparelho_novo_para_pedido(request, pedido)  # 1º aparelho do cliente vira "de confiança"
    if cookie_novo:
        messages.success(request, "Seu cartão de fidelidade foi criado neste aparelho! Veja na aba Fidelidade.")
    resposta = render(request, "pedidos/pedido.html", {
        "pedido": pedido, "whatsapp_url": whatsapp, "passos": passos,
        "bonus_pontos": bonus.pontos if bonus else 0,
        "avaliacoes_produtos": avaliacoes_produtos,
        "produtos_pendentes": produtos_pendentes,
        "avaliacao_form": AvaliacaoProdutoForm() if produtos_pendentes else None,
        "mostrar_pagamento_aprovado": (
            request.GET.get("pagamento") == "aprovado" and pedido.status in Pedido.STATUS_PAGOS
        ),
    })
    if cookie_novo:
        definir_cookie(resposta, cookie_novo)
    return resposta


@require_POST
def avaliar_produto(request, codigo, produto_id):
    pedido = _pedido_autorizado(request, codigo)
    if pedido.status != Pedido.Status.ENTREGUE:
        return HttpResponse(status=403)
    produto = get_object_or_404(Produto, pk=produto_id)
    if not pedido.itens.filter(produto=produto).exists():
        raise Http404
    if AvaliacaoProduto.objects.filter(pedido=pedido, produto=produto).exists():
        messages.info(request, "Este produto deste pedido já foi avaliado. Obrigado!")
        return redirect("pedidos:detalhe", codigo=codigo)
    if not limitar(f"avaliacao:{codigo}:{produto_id}:{ip_do_cliente(request)}", 5, 3600):
        messages.error(request, "Muitas tentativas de avaliação. Tente novamente mais tarde.")
        return redirect("pedidos:detalhe", codigo=codigo)

    form = AvaliacaoProdutoForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Escolha uma nota e escreva um comentário com pelo menos 5 caracteres.")
        return redirect("pedidos:detalhe", codigo=codigo)

    _, criada = AvaliacaoProduto.objects.get_or_create(
        pedido=pedido, produto=produto,
        defaults=form.cleaned_data,
    )
    if criada:
        messages.success(request, f"Obrigado por avaliar {produto.nome}!")
    else:
        messages.info(request, "Este produto deste pedido já foi avaliado. Obrigado!")
    return redirect("pedidos:detalhe", codigo=codigo)


def pagar(request, codigo):
    """Cria (ou reaproveita) a preferência e envia o cliente ao Mercado Pago."""
    pedido = _pedido_autorizado(request, codigo)
    if not limitar(f"pagar:{codigo}:{ip_do_cliente(request)}", 10, 60):
        return HttpResponse("Muitas tentativas de pagamento. Aguarde um minuto.", status=429)
    if not pedido.aguarda_pagamento:
        return redirect("pedidos:detalhe", codigo=codigo)

    if pedido.total <= 0:  # totalmente coberto por pontos/cupom: não há o que cobrar
        pedido.status = Pedido.Status.PAGO
        pedido.save()
        messages.success(request, "Pedido confirmado! Nenhum pagamento foi necessário.")
        return redirect("pedidos:detalhe", codigo=codigo)

    forma = request.GET.get("forma")
    if forma in Pedido.Pagamento.values and forma != pedido.forma_pagamento:
        pedido.forma_pagamento = forma
        pedido.mp_init_point = ""
        pedido.mp_preference_id = ""
        pedido.save()

    if not pedido.mp_init_point:
        try:
            pedido.mp_preference_id, pedido.mp_init_point = mp.criar_preferencia(pedido)
            pedido.save()
        except Exception as erro:  # noqa: BLE001
            log.exception("Falha ao criar pagamento do pedido %s", codigo)
            messages.error(request, str(erro) if isinstance(erro, mp.ErroMercadoPago)
                           else "Não foi possível abrir o pagamento agora. Tente novamente.")
            return redirect("pedidos:detalhe", codigo=codigo)
    return redirect(pedido.mp_init_point)


def retorno(request, codigo):
    """Para onde o Mercado Pago devolve o cliente depois do pagamento."""
    pedido = _pedido_autorizado(request, codigo)
    if not limitar(f"retorno:{codigo}:{ip_do_cliente(request)}", 10, 60):
        return HttpResponse("Muitas tentativas de retorno. Aguarde um minuto.", status=429)
    payment_id = request.GET.get("payment_id") or request.GET.get("collection_id")
    if payment_id and payment_id != "null":
        try:
            mp.sincronizar(payment_id)
        except Exception:  # noqa: BLE001
            log.exception("Falha ao sincronizar pagamento %s", payment_id)
    pedido.refresh_from_db()
    if pedido.aguarda_pagamento and pedido.mp_preference_id and settings.MP_ACCESS_TOKEN:
        try:
            mp.sincronizar_pedido(pedido)
        except Exception:  # noqa: BLE001
            log.exception("Falha ao conferir o pagamento do pedido %s", codigo)
    if pedido.status in Pedido.STATUS_PAGOS:
        return redirect(f"{reverse('pedidos:detalhe', args=[codigo])}?pagamento=aprovado")
    elif request.GET.get("status") in ("failure", "rejected"):
        messages.error(request, "O pagamento não foi concluído. Você pode tentar de novo abaixo.")
    return redirect("pedidos:detalhe", codigo=codigo)


@require_GET
def rastreio(request, codigo):
    """Posição do entregador e do destino, para o mapa ao vivo da página do pedido."""
    pedido = _pedido_autorizado(request, codigo)
    if not limitar(f"rastreio:{codigo}:{ip_do_cliente(request)}", 40, 60):
        return JsonResponse({"erro": "Muitas consultas. Aguarde um minuto."}, status=429)
    config = ConfiguracaoLoja.obter()
    ativo = pedido.status == Pedido.Status.SAIU_ENTREGA
    dados = {
        "ativo": ativo, "status": pedido.status,
        "loja": {"lat": config.latitude, "lon": config.longitude},
        "destino": None, "entregador": None, "rota": None, "restante_km": None, "eta_min": None,
        "previsao": None, "atraso_min": 0, "pontos_atraso": 0,
    }
    if pedido.prazo_entrega:
        dados["previsao"] = timezone.localtime(pedido.prazo_entrega).strftime("%H:%M")
        dados["atraso_min"] = pedido.atraso_min
        dados["pontos_atraso"] = pedido.pontos_atraso
    if pedido.destino_lat is not None and pedido.destino_lon is not None:
        dados["destino"] = {"lat": pedido.destino_lat, "lon": pedido.destino_lon}
    recente = pedido.entregador_em and (timezone.now() - pedido.entregador_em).total_seconds() <= 180
    if ativo and recente and pedido.entregador_lat is not None:
        dados["entregador"] = {"lat": pedido.entregador_lat, "lon": pedido.entregador_lon}
        if dados["destino"]:
            # trajeto real pelas ruas, do entregador até o cliente (recalculado de tempos em tempos)
            rota = rota_ao_vivo(
                pedido.codigo,
                {"lat": pedido.entregador_lat, "lon": pedido.entregador_lon},
                {"lat": pedido.destino_lat, "lon": pedido.destino_lon},
                perfil_da_loja(config),
            )
            if rota:
                dados["rota"] = rota["geometria"]
                km = rota["km"]
            else:
                km = distancia_km(pedido.entregador_lat, pedido.entregador_lon,
                                  pedido.destino_lat, pedido.destino_lon) * 1.3  # sem rota: estimativa
            dados["restante_km"] = round(km, 1)
            dados["eta_min"] = max(1, round(km / max(config.velocidade_bike_kmh, 1) * 60))
    return JsonResponse(dados)


@require_GET
def chat_lista(request, codigo):
    pedido = _pedido_autorizado(request, codigo)
    if not limitar(f"chat-leitura:{codigo}:{ip_do_cliente(request)}", 60, 60):
        return JsonResponse({"erro": "Muitas consultas. Aguarde um minuto."}, status=429)
    return JsonResponse({
        "ativo": pedido.chat_ativo,
        "mensagens": mensagens_depois(pedido, _inteiro(request.GET.get("depois")), leitor=Mensagem.CLIENTE),
    })


@require_POST
def chat_enviar(request, codigo):
    pedido = _pedido_autorizado(request, codigo)
    if not limitar(f"chat-envio:{codigo}:{ip_do_cliente(request)}", 20, 60):
        return JsonResponse({"ok": False, "erro": "Muitas mensagens. Aguarde um minuto."}, status=429)
    if not pedido.chat_ativo:
        return JsonResponse({"ok": False, "erro": "O chat fica aberto enquanto o pedido está em andamento."}, status=403)
    try:
        mensagem = enviar_mensagem(pedido, Mensagem.CLIENTE, request.POST.get("texto"))
    except ValueError as erro:
        return JsonResponse({"ok": False, "erro": str(erro)}, status=400)
    return JsonResponse({"ok": True, "id": mensagem.id})


@require_GET
def status_pedido(request, codigo):
    """Usado pela página do pedido para se atualizar sozinha quando o pagamento é aprovado."""
    pedido = _pedido_autorizado(request, codigo)
    if not limitar(f"status:{codigo}:{ip_do_cliente(request)}", 40, 60):
        return JsonResponse({"erro": "Muitas consultas. Aguarde um minuto."}, status=429)
    mp.conferir_pagamento(pedido)
    return JsonResponse({"status": pedido.status, "pago": pedido.status in Pedido.STATUS_PAGOS})


def verificar(request, codigo):
    """Botão "Já paguei": confere o pagamento agora, sem esperar o intervalo."""
    pedido = _pedido_autorizado(request, codigo)
    if not limitar(f"verificar:{codigo}:{ip_do_cliente(request)}", 5, 60):
        return HttpResponse("Muitas consultas de pagamento. Aguarde um minuto.", status=429)
    if pedido.aguarda_pagamento:
        try:
            mp.sincronizar_pedido(pedido)
        except Exception:  # noqa: BLE001
            log.exception("Falha ao verificar o pagamento do pedido %s", codigo)
            messages.error(request, "Não conseguimos consultar o Mercado Pago agora. Tente de novo em instantes.")
            return redirect("pedidos:detalhe", codigo=codigo)
        if pedido.status in Pedido.STATUS_PAGOS:
            return redirect(f"{reverse('pedidos:detalhe', args=[codigo])}?pagamento=aprovado")
        else:
            messages.info(request, "Ainda não identificamos o pagamento. O Pix pode levar alguns instantes; "
                                   "esta página se atualiza sozinha quando ele for confirmado.")
    return redirect("pedidos:detalhe", codigo=codigo)


@csrf_exempt
@require_POST
def webhook(request):
    """Notificações do Mercado Pago. Sempre consultamos a API antes de atualizar o pedido."""
    tipo = request.GET.get("type") or request.GET.get("topic")
    payment_id = request.GET.get("data.id") or request.GET.get("id")
    if request.body:
        try:
            corpo = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            return HttpResponse(status=400)
        if not isinstance(corpo, dict):
            return HttpResponse(status=400)
        tipo = tipo or corpo.get("type")
        dados = corpo.get("data")
        if isinstance(dados, dict):
            payment_id = payment_id or dados.get("id")

    if not settings.MP_WEBHOOK_SECRET:
        log.error("Webhook do Mercado Pago recusado: MP_WEBHOOK_SECRET não está configurado.")
        return HttpResponse(status=503)
    if not payment_id or not mp.validar_assinatura_webhook(
        payment_id,
        request.headers.get("x-request-id", ""),
        request.headers.get("x-signature", ""),
    ):
        log.warning("Webhook do Mercado Pago recusado por assinatura inválida.")
        return HttpResponse(status=401)

    if tipo == "payment" and payment_id:
        try:
            mp.sincronizar(payment_id)
        except Exception:  # noqa: BLE001
            log.exception("Webhook: falha ao sincronizar pagamento %s", payment_id)
            return HttpResponse(status=500)  # o Mercado Pago tenta de novo
    return HttpResponse(status=200)


def meus_pedidos(request):
    codigos = request.session.get(SESSAO_PEDIDOS, [])
    if not isinstance(codigos, list):
        codigos = []
    pedidos = list(Pedido.objects.filter(codigo__in=codigos))
    pedidos.sort(key=lambda p: codigos.index(p.codigo))
    return render(request, "pedidos/meus_pedidos.html", {"pedidos": pedidos})