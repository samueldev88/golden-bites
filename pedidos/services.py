from decimal import Decimal

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from fidelidade.models import MovimentoPontos
from fidelidade.services import saldo

from .models import Cliente, Cupom, ItemPedido, Mensagem, Pedido

LIMITE_MENSAGENS = 300  # por pedido
PRECISAO_DESTINO = ("endereco", "rua")  # só localizações verificadas pelo servidor viram pontos no mapa


@transaction.atomic
def criar_pedido(dados, itens, subtotal, cupom=None, avaliacao=None, trocas=None):
    """Cria o pedido e seus itens a partir do formulário validado e do carrinho."""
    if cupom:
        cupom = _reservar_cupom(cupom, subtotal)
    nome_completo = f'{dados["nome"].strip()} {dados["sobrenome"].strip()}'
    cliente, _ = Cliente.objects.update_or_create(
        telefone=dados["telefone"], defaults={"nome": nome_completo},
    )
    # trava o cliente: duas trocas ao mesmo tempo não conseguem gastar o mesmo saldo
    cliente = Cliente.objects.select_for_update().get(pk=cliente.pk)
    trocas = trocas or []
    pontos_trocados = sum(t["pontos"] for t in trocas)
    if pontos_trocados and saldo(cliente) < pontos_trocados:
        raise ValueError("Seu saldo de pontos não cobre as trocas do carrinho. Remova alguma troca.")

    modalidade = dados["modalidade"]
    avaliacao = avaliacao or {}
    taxa = avaliacao.get("taxa")  # None = a consultar
    distancia = avaliacao.get("distancia_km")
    destino = avaliacao.get("destino") if avaliacao.get("precisao") in PRECISAO_DESTINO else None

    pedido = Pedido(
        cliente=cliente,
        modalidade=modalidade,
        bairro_nome=dados["bairro"].strip(),
        distancia_km=None if distancia is None else Decimal(str(distancia)),
        destino_lat=destino["lat"] if destino else None,
        destino_lon=destino["lon"] if destino else None,
        destino_precisao=avaliacao.get("precisao") or "" if destino else "",
        cep=dados.get("cep", ""),
        rua=dados["rua"].strip(),
        numero=dados["numero"].strip(),
        complemento=dados.get("complemento", ""),
        referencia=dados.get("referencia", ""),
        data_agendada=dados.get("data_agendada") if modalidade == Pedido.Modalidade.AGENDADA else None,
        horario_combinado=dados.get("horario_combinado", "") if modalidade == Pedido.Modalidade.AGENDADA else "",
        subtotal=subtotal,
        taxa_entrega=taxa,
        cupom=cupom,
        pontos_resgatados=pontos_trocados,
        forma_pagamento=dados["forma_pagamento"],
        observacoes=dados.get("observacoes", ""),
        status=(
            Pedido.Status.AGUARDANDO_PAGAMENTO if taxa is not None
            else Pedido.Status.AGUARDANDO_CONFIRMACAO
        ),
    )
    pedido.recalcular()
    pedido.save()

    ItemPedido.objects.bulk_create([
        ItemPedido(
            pedido=pedido,
            produto=item["produto"],
            nome=item["produto"].nome,
            preco_unitario=item["produto"].preco_final,
            quantidade=item["quantidade"],
            pontos=item["produto"].pontos,
        )
        for item in itens
    ] + [
        # itens trocados por pontos: preço zero, não geram pontos e guardam quanto custaram
        ItemPedido(
            pedido=pedido,
            produto=troca["produto"],
            nome=troca["produto"].nome,
            preco_unitario=Decimal("0.00"),
            quantidade=troca["quantidade"],
            pontos=0,
            resgate=True,
            pontos_resgate=troca["custo_unitario"],
        )
        for troca in trocas
    ])
    if pontos_trocados:
        MovimentoPontos.objects.create(
            cliente=cliente, pedido=pedido, tipo=MovimentoPontos.RESGATE,
            pontos=-pontos_trocados, observacao=f"Troca de pontos no pedido {pedido.codigo}",
        )
    return pedido


def _reservar_cupom(cupom, subtotal):
    cupom = Cupom.objects.select_for_update().get(pk=cupom.pk)
    valido, mensagem = cupom.validar(subtotal)
    if not valido:
        raise ValueError(mensagem)

    consulta = Cupom.objects.filter(
        pk=cupom.pk,
        ativo=True,
        minimo__lte=subtotal,
    ).filter(Q(validade__isnull=True) | Q(validade__gte=timezone.localdate()))
    if cupom.limite_usos is not None:
        consulta = consulta.filter(usos__lt=cupom.limite_usos)
    if consulta.update(usos=F("usos") + 1) != 1:
        cupom.refresh_from_db()
        _, mensagem = cupom.validar(subtotal)
        raise ValueError(mensagem or "Este cupom não está mais disponível.")
    cupom.usos += 1
    return cupom


def definir_taxa(pedido, taxa):
    """Usado pelo painel: confirma a taxa e libera o pagamento."""
    pedido.taxa_entrega = Decimal(taxa)
    pedido.recalcular()
    if pedido.status == Pedido.Status.AGUARDANDO_CONFIRMACAO:
        pedido.status = Pedido.Status.AGUARDANDO_PAGAMENTO
    pedido.mp_init_point = ""  # força nova preferência com o valor atualizado
    pedido.mp_preference_id = ""
    pedido.save()


# ---------------------------------------------------------------- chat
def mensagens_depois(pedido, depois=0, leitor=None):
    """Mensagens novas (id maior que `depois`). Quem lê marca como lidas as mensagens do outro lado."""
    lista = list(pedido.mensagens.filter(id__gt=depois))
    if leitor and lista:
        outro = Mensagem.ENTREGADOR if leitor == Mensagem.CLIENTE else Mensagem.CLIENTE
        ids = [m.id for m in lista if m.autor == outro and not m.lida]
        if ids:
            Mensagem.objects.filter(id__in=ids).update(lida=True)
    return [
        {"id": m.id, "autor": m.autor, "texto": m.texto,
         "hora": timezone.localtime(m.criado_em).strftime("%H:%M")}
        for m in lista
    ]


def enviar_mensagem(pedido, autor, texto):
    """Salva uma mensagem do chat. Levanta ValueError com um texto amigável quando não pode."""
    texto = " ".join((texto or "").split())[:500]
    if not texto:
        raise ValueError("Escreva uma mensagem.")
    if pedido.mensagens.count() >= LIMITE_MENSAGENS:
        raise ValueError("Este chat chegou ao limite de mensagens.")
    ultima = pedido.mensagens.filter(autor=autor).order_by("-id").first()
    if ultima and (timezone.now() - ultima.criado_em).total_seconds() < 1:
        raise ValueError("Aguarde um instante antes de enviar outra mensagem.")
    return Mensagem.objects.create(pedido=pedido, autor=autor, texto=texto)