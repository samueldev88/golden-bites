"""Consultas dos relatórios do painel (entradas, saídas e desempenho das vendas)."""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone

from pedidos.models import ItemPedido, Pedido

from .models import Lancamento

ZERO = Decimal("0.00")
ROTULOS_CATEGORIA = dict(Lancamento.CATEGORIAS)
ROTULOS_PAGAMENTO = dict(Pedido.Pagamento.choices)
ROTULOS_MODALIDADE = dict(Pedido.Modalidade.choices)

PRESETS = [("hoje", "Hoje"), ("7d", "7 dias"), ("30d", "30 dias"), ("mes", "Este mês"), ("ano", "Este ano")]


def resolver_periodo(get):
    """Devolve (inicio, fim, preset_ativo) a partir dos parâmetros da URL."""
    hoje = timezone.localdate()
    if get.get("de") and get.get("ate"):
        try:
            inicio, fim = date.fromisoformat(get["de"]), date.fromisoformat(get["ate"])
            if inicio > fim:
                inicio, fim = fim, inicio
            return inicio, fim, "personalizado"
        except ValueError:
            pass
    preset = get.get("periodo", "30d")
    intervalos = {
        "hoje": (hoje, hoje),
        "7d": (hoje - timedelta(days=6), hoje),
        "30d": (hoje - timedelta(days=29), hoje),
        "mes": (hoje.replace(day=1), hoje),
        "ano": (date(hoje.year, 1, 1), hoje),
    }
    if preset not in intervalos:
        preset = "30d"
    return (*intervalos[preset], preset)


def pedidos_pagos(inicio, fim):
    return Pedido.objects.filter(
        status__in=Pedido.STATUS_PAGOS, pago_em__date__gte=inicio, pago_em__date__lte=fim
    )


def lancamentos(inicio, fim):
    return Lancamento.objects.filter(data__gte=inicio, data__lte=fim)


def _mes(valor):
    return (valor.year, valor.month)


def _barras(inicio, fim, pagos, lanc):
    dias = (fim - inicio).days + 1
    por_dia = dias <= 45
    if por_dia:
        ent_pedidos = {r["k"]: r["t"] for r in pagos.annotate(k=TruncDate("pago_em")).values("k")
                       .annotate(t=Sum("total")).order_by("k")}
        ent_lanc = {r["data"]: r["t"] for r in lanc.filter(tipo=Lancamento.ENTRADA).values("data")
                    .annotate(t=Sum("valor")).order_by("data")}
        saidas = {r["data"]: r["t"] for r in lanc.filter(tipo=Lancamento.SAIDA).values("data")
                  .annotate(t=Sum("valor")).order_by("data")}
        chaves = [inicio + timedelta(days=i) for i in range(dias)]
        rotulo = lambda c: c.strftime("%d/%m")  # noqa: E731
    else:
        ent_pedidos = {_mes(r["k"]): r["t"] for r in pagos.annotate(k=TruncMonth("pago_em")).values("k")
                       .annotate(t=Sum("total")).order_by("k")}
        ent_lanc = {_mes(r["k"]): r["t"] for r in lanc.filter(tipo=Lancamento.ENTRADA)
                    .annotate(k=TruncMonth("data")).values("k").annotate(t=Sum("valor")).order_by("k")}
        saidas = {_mes(r["k"]): r["t"] for r in lanc.filter(tipo=Lancamento.SAIDA)
                  .annotate(k=TruncMonth("data")).values("k").annotate(t=Sum("valor")).order_by("k")}
        chaves = []
        atual = (inicio.year, inicio.month)
        while atual <= (fim.year, fim.month):
            chaves.append(atual)
            atual = (atual[0] + (atual[1] == 12), 1 if atual[1] == 12 else atual[1] + 1)
        rotulo = lambda c: f"{c[1]:02d}/{c[0]}"  # noqa: E731

    linhas = []
    for c in chaves:
        entrada = (ent_pedidos.get(c) or ZERO) + (ent_lanc.get(c) or ZERO)
        saida = saidas.get(c) or ZERO
        linhas.append({"rotulo": rotulo(c), "entrada": entrada, "saida": saida})
    maximo = max([max(l["entrada"], l["saida"]) for l in linhas] + [Decimal("0.01")])
    for l in linhas:
        for chave, destino in (("entrada", "h_ent"), ("saida", "h_sai")):
            valor = l[chave]
            l[destino] = 0 if valor <= 0 else max(int(round(valor / maximo * 100)), 3)
    return linhas


def gerar(inicio, fim):
    pagos = pedidos_pagos(inicio, fim)
    lanc = lancamentos(inicio, fim)

    agg = pagos.aggregate(
        total=Sum("total"), n=Count("id"), taxas=Sum("taxa_entrega"),
        desc_cupom=Sum("desconto"), desc_fid=Sum("desconto_fidelidade"),
    )
    entradas_pedidos = agg["total"] or ZERO
    n_pedidos = agg["n"] or 0
    entradas_avulsas = lanc.filter(tipo=Lancamento.ENTRADA).aggregate(t=Sum("valor"))["t"] or ZERO
    saidas_total = lanc.filter(tipo=Lancamento.SAIDA).aggregate(t=Sum("valor"))["t"] or ZERO
    entradas_total = entradas_pedidos + entradas_avulsas

    receita_item = ExpressionWrapper(
        F("quantidade") * F("preco_unitario"), output_field=DecimalField(max_digits=12, decimal_places=2)
    )
    top_produtos = list(
        ItemPedido.objects.filter(pedido__in=pagos).values("nome")
        .annotate(qtd=Sum("quantidade"), receita=Sum(receita_item)).order_by("-qtd", "nome")[:10]
    )
    por_pagamento = [
        {"rotulo": ROTULOS_PAGAMENTO.get(r["forma_pagamento"], r["forma_pagamento"]), "total": r["t"], "n": r["n"]}
        for r in pagos.values("forma_pagamento").annotate(t=Sum("total"), n=Count("id")).order_by("-t")
    ]
    por_modalidade = [
        {"rotulo": ROTULOS_MODALIDADE.get(r["modalidade"], r["modalidade"]), "total": r["t"], "n": r["n"]}
        for r in pagos.values("modalidade").annotate(t=Sum("total"), n=Count("id")).order_by("-t")
    ]
    saidas_por_categoria = [
        {"rotulo": ROTULOS_CATEGORIA.get(r["categoria"], r["categoria"]), "total": r["t"]}
        for r in lanc.filter(tipo=Lancamento.SAIDA).values("categoria").annotate(t=Sum("valor")).order_by("-t")
    ]
    cancelados = Pedido.objects.filter(
        status=Pedido.Status.CANCELADO, criado_em__date__gte=inicio, criado_em__date__lte=fim
    ).count()

    return {
        "inicio": inicio, "fim": fim,
        "entradas_pedidos": entradas_pedidos, "entradas_avulsas": entradas_avulsas,
        "entradas_total": entradas_total, "saidas_total": saidas_total,
        "saldo": entradas_total - saidas_total,
        "n_pedidos": n_pedidos,
        "ticket_medio": (entradas_pedidos / n_pedidos) if n_pedidos else ZERO,
        "taxas_entrega": agg["taxas"] or ZERO,
        "descontos": (agg["desc_cupom"] or ZERO) + (agg["desc_fid"] or ZERO),
        "cancelados": cancelados,
        "top_produtos": top_produtos,
        "por_pagamento": por_pagamento,
        "por_modalidade": por_modalidade,
        "saidas_por_categoria": saidas_por_categoria,
        "barras": _barras(inicio, fim, pagos, lanc),
        "lancamentos": list(lanc[:50]),
    }