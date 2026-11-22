import csv
import re
import secrets
from io import BytesIO
from uuid import uuid4
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.files.base import ContentFile
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.views import LoginView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.paginator import Paginator
from django.db.models import Avg, Count, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.forms import DateInput, modelform_factory
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from PIL import Image, ImageOps

from catalogo.models import Categoria, ConfiguracaoLoja, FotoProduto, Produto
from catalogo.templatetags.loja_tags import brl
from catalogo.validators import MAX_UPLOAD_BYTES, validar_imagem_produto
from entregas.models import Bairro, FaixaTaxa
from fidelidade.models import Dispositivo, MovimentoPontos
from fidelidade.services import gerar_codigo_vinculo, ip_do_cliente, limitar
from fidelidade.services import saldo as saldo_cliente
from financeiro import relatorios
from financeiro.models import Lancamento
from pedidos import mercadopago as mp
from pedidos.models import AvaliacaoPedido, AvaliacaoProduto, Cliente, Cupom, Mensagem, Pedido
from pedidos.services import definir_taxa, enviar_mensagem, mensagens_depois

staff_required = user_passes_test(lambda u: u.is_staff, login_url="painel:login")
S = Pedido.Status


class LoginSeguro(LoginView):
    """Login do painel com limite de tentativas por endereço (barra quem tenta adivinhar a senha)."""

    template_name = "painel/login.html"
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        if not limitar(f"login:{ip_do_cliente(request)}", 8, 900):
            form = self.get_form()
            form.add_error(None, "Muitas tentativas de entrada. Aguarde 15 minutos e tente de novo.")
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)


class StaffMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_staff


def _voltar_para(request, padrao):
    destino = request.POST.get("next", "")
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        return redirect(destino)
    return redirect(padrao)


# ---------------------------------------------------------------- dashboard
@staff_required
def dashboard(request):
    hoje = timezone.localdate()
    pagos_hoje = relatorios.pedidos_pagos(hoje, hoje).aggregate(t=Sum("total"))["t"] or Decimal("0")
    pagos_mes = relatorios.pedidos_pagos(hoje.replace(day=1), hoje).aggregate(t=Sum("total"))["t"] or Decimal("0")
    return render(request, "painel/dashboard.html", {
        "pedidos_hoje": Pedido.objects.filter(criado_em__date=hoje).count(),
        "aguardando_confirmacao": Pedido.objects.filter(status=S.AGUARDANDO_CONFIRMACAO).count(),
        "em_andamento": Pedido.objects.filter(status__in=[S.PAGO, S.EM_PREPARO, S.SAIU_ENTREGA]).count(),
        "entradas_hoje": pagos_hoje,
        "vendas_mes": pagos_mes,
        "recentes": Pedido.objects.select_related("cliente")[:8],
    })


# ------------------------------------------------------------------ produtos
@staff_required
@require_POST
def produto_alternar(request, pk, campo):
    if campo in ("disponivel", "destaque"):
        produto = get_object_or_404(Produto, pk=pk)
        setattr(produto, campo, not getattr(produto, campo))
        produto.save(update_fields=[campo])
    return redirect("painel:produtos_lista")


@staff_required
@require_POST
def produto_promocao(request, pk):
    """Promoção rápida: aplica X% de desconto ou remove a promoção."""
    produto = get_object_or_404(Produto, pk=pk)
    if request.POST.get("remover"):
        produto.preco_promocional = None
        messages.success(request, f"Promoção de {produto.nome} removida.")
    else:
        try:
            pct = Decimal(request.POST.get("percentual", "").replace(",", "."))
        except InvalidOperation:
            pct = Decimal("0")
        if not (Decimal("0") < pct < Decimal("100")):
            messages.error(request, "Informe um desconto entre 1% e 99%.")
            return redirect("painel:produtos_lista")
        produto.preco_promocional = (produto.preco * (100 - pct) / 100).quantize(Decimal("0.01"))
        messages.success(request, f"{produto.nome}: {pct:.0f}% de desconto, agora {brl(produto.preco_promocional)}.")
    produto.save(update_fields=["preco_promocional"])
    return redirect("painel:produtos_lista")


MAX_FOTOS_EXTRAS = 10
MAX_BYTES_FOTO = MAX_UPLOAD_BYTES


def _otimizar_imagem(arquivo):
    """Valida a imagem, corrige a rotação do celular, reduz para até 1600 px e salva em WEBP (carrega mais rápido)."""
    imagem = Image.open(arquivo)
    imagem.load()
    imagem = ImageOps.exif_transpose(imagem)
    if imagem.mode not in ("RGB", "RGBA"):
        imagem = imagem.convert("RGB")
    imagem.thumbnail((1600, 1600))
    saida = BytesIO()
    imagem.save(saida, "WEBP", quality=82)
    return ContentFile(saida.getvalue(), name=f"{uuid4().hex}.webp")


@staff_required
def produto_fotos(request, pk):
    produto = get_object_or_404(Produto.objects.prefetch_related("fotos"), pk=pk)
    if request.method == "POST":
        existentes = produto.fotos.count()
        salvas = 0
        for arquivo in request.FILES.getlist("fotos"):
            if existentes + salvas >= MAX_FOTOS_EXTRAS:
                messages.error(request, f"O limite é de {MAX_FOTOS_EXTRAS} fotos extras por produto.")
                break
            if arquivo.size > MAX_BYTES_FOTO:
                messages.error(request, f"{arquivo.name}: o arquivo passa de 8 MB.")
                continue
            try:
                validar_imagem_produto(arquivo)
                conteudo = _otimizar_imagem(arquivo)
            except Exception:  # noqa: BLE001 - arquivo corrompido, não é imagem ou grande demais
                messages.error(request, f"{arquivo.name}: não é uma imagem válida.")
                continue
            FotoProduto.objects.create(produto=produto, imagem=conteudo, ordem=existentes + salvas)
            salvas += 1
        if salvas:
            messages.success(request, f"{salvas} foto(s) adicionada(s).")
        return redirect("painel:produto_fotos", pk=pk)
    return render(request, "painel/produto_fotos.html", {
        "produto": produto, "fotos": produto.fotos.all(), "maximo": MAX_FOTOS_EXTRAS,
    })


@staff_required
@require_POST
def foto_remover(request, pk):
    foto = get_object_or_404(FotoProduto, pk=pk)
    produto_id = foto.produto_id
    foto.imagem.delete(save=False)  # apaga o arquivo também
    foto.delete()
    messages.success(request, "Foto removida.")
    return redirect("painel:produto_fotos", pk=produto_id)


@staff_required
@require_POST
def foto_mover(request, pk, direcao):
    foto = get_object_or_404(FotoProduto, pk=pk)
    if direcao in ("subir", "descer"):
        fotos = list(foto.produto.fotos.all())
        i = next(n for n, f in enumerate(fotos) if f.pk == foto.pk)
        j = i - 1 if direcao == "subir" else i + 1
        if 0 <= j < len(fotos):
            fotos[i], fotos[j] = fotos[j], fotos[i]
            for ordem, f in enumerate(fotos):
                if f.ordem != ordem:
                    FotoProduto.objects.filter(pk=f.pk).update(ordem=ordem)
    return redirect("painel:produto_fotos", pk=foto.produto_id)


# ------------------------------------------------------------------- pedidos
@staff_required
def pedidos_lista(request):
    status = request.GET.get("status", "")
    pedidos = Pedido.objects.select_related("cliente")
    if status in Pedido.Status.values:
        pedidos = pedidos.filter(status=status)
    return render(request, "painel/pedidos.html", {
        "pedidos": pedidos[:200], "status_atual": status, "status_opcoes": Pedido.Status.choices,
    })


@staff_required
def pedido_detalhe(request, codigo):
    pedido = get_object_or_404(Pedido.objects.select_related("cliente", "cupom"), codigo=codigo)
    pedido.garantir_codigo()
    if request.method == "POST":
        acao = request.POST.get("acao")
        if acao == "status":
            novo = request.POST.get("status")
            if novo in Pedido.Status.values:
                pedido.status = novo
                pedido.save(update_fields=["status", "atualizado_em"])
                messages.success(request, "Status atualizado.")
        elif acao == "verificar":
            try:
                mp.sincronizar_pedido(pedido)
            except Exception as erro:  # noqa: BLE001
                messages.error(request, f"Não consegui consultar o Mercado Pago: {erro}")
            else:
                if pedido.status == S.PAGO:
                    messages.success(request, "Pagamento confirmado no Mercado Pago.")
                else:
                    messages.info(request, f"Mercado Pago: {pedido.mp_status or 'nenhum pagamento encontrado ainda'}.")
        elif acao == "taxa":
            try:
                taxa = Decimal(request.POST.get("taxa", "").replace(",", "."))
                if taxa < 0:
                    raise InvalidOperation
            except InvalidOperation:
                messages.error(request, "Informe um valor de taxa válido.")
            else:
                definir_taxa(pedido, taxa)
                messages.success(request, "Taxa confirmada. O cliente já pode pagar pelo link do pedido.")
        return redirect("painel:pedido_detalhe", codigo=codigo)
    return render(request, "painel/pedido_detalhe.html", {
        "pedido": pedido, "status_opcoes": Pedido.Status.choices,
    })


@staff_required
@require_POST
def pedido_avancar(request, codigo):
    pedido = get_object_or_404(Pedido, codigo=codigo)
    if pedido.status == S.SAIU_ENTREGA:
        messages.error(request, "A entrega é confirmada com o código de 4 dígitos do cliente, no Modo entregador.")
        return redirect("painel:entregador", codigo=codigo)
    if pedido.proximo:
        pedido.status = pedido.proximo[0]
        pedido.save(update_fields=["status", "atualizado_em"])
        messages.success(request, f"Pedido {pedido.codigo}: {pedido.get_status_display().lower()}.")
    return _voltar_para(request, "painel:andamento")


@staff_required
def andamento(request):
    """Quadro com os pedidos em aberto, por etapa."""
    etapas = [
        ("Taxa a confirmar", S.AGUARDANDO_CONFIRMACAO),
        ("Aguardando pagamento", S.AGUARDANDO_PAGAMENTO),
        ("Pagos (novos)", S.PAGO),
        ("Em preparo", S.EM_PREPARO),
        ("Saiu para entrega", S.SAIU_ENTREGA),
    ]
    # confere no Mercado Pago os pedidos que aguardam pagamento (no máximo a cada 8 s por pedido)
    for pendente in Pedido.objects.filter(status=S.AGUARDANDO_PAGAMENTO).exclude(mp_preference_id="")[:15]:
        mp.conferir_pagamento(pendente)
    abertos = Pedido.objects.select_related("cliente").prefetch_related("itens")
    novas = {
        r["pedido_id"]: r["n"]
        for r in Mensagem.objects.filter(autor=Mensagem.CLIENTE, lida=False)
        .values("pedido_id").annotate(n=Count("id")).order_by()
    }
    colunas = []
    for titulo, status in etapas:
        pedidos = list(abertos.filter(status=status).order_by("data_agendada", "criado_em"))
        for p in pedidos:
            p.msgs_novas = novas.get(p.id, 0)
        colunas.append({"titulo": titulo, "status": status.value, "pedidos": pedidos})
    return render(request, "painel/andamento.html", {"colunas": colunas})


# ------------------------------------------------------- modo entregador
@staff_required
def entregador(request, codigo):
    """Tela do celular do entregador: compartilha a localização e conversa com o cliente."""
    pedido = get_object_or_404(Pedido.objects.select_related("cliente"), codigo=codigo)
    return render(request, "painel/entregador.html", {"pedido": pedido})


@staff_required
@require_POST
def entregador_confirmar(request, codigo):
    """Confirma a entrega: o cliente passa o código de 4 dígitos ao entregador."""
    pedido = get_object_or_404(Pedido, codigo=codigo)
    if pedido.status != S.SAIU_ENTREGA:
        return JsonResponse({"ok": False, "erro": "Este pedido não está em entrega."}, status=400)
    if pedido.tentativas_codigo >= 5:
        return JsonResponse({
            "ok": False, "bloqueado": True,
            "erro": "Muitas tentativas erradas. Peça ao responsável para confirmar a entrega no painel.",
        }, status=403)
    pedido.garantir_codigo()
    digitado = re.sub(r"[^0-9]", "", request.POST.get("codigo", ""))
    if not secrets.compare_digest(digitado, pedido.codigo_entrega):
        Pedido.objects.filter(pk=pedido.pk).update(tentativas_codigo=F("tentativas_codigo") + 1)
        restantes = max(0, 4 - pedido.tentativas_codigo)
        return JsonResponse({"ok": False, "erro": f"Código incorreto. Restam {restantes} tentativa(s)."}, status=400)
    pedido.status = S.ENTREGUE
    pedido.save(update_fields=["status", "atualizado_em"])  # registra a hora e credita pontos de atraso, se houver
    return JsonResponse({"ok": True})


@staff_required
@require_POST
def entregador_posicao(request, codigo):
    pedido = get_object_or_404(Pedido, codigo=codigo)
    try:
        lat, lon = float(request.POST["lat"]), float(request.POST["lon"])
    except (KeyError, ValueError):
        return JsonResponse({"ok": False}, status=400)
    if not (-34 <= lat <= 6 and -74 <= lon <= -34):
        return JsonResponse({"ok": False}, status=400)
    # update() direto: não dispara o salvamento completo do pedido a cada atualização do GPS
    Pedido.objects.filter(pk=pedido.pk).update(entregador_lat=lat, entregador_lon=lon, entregador_em=timezone.now())
    return JsonResponse({"ok": True})


@staff_required
def entregador_chat(request, codigo):
    pedido = get_object_or_404(Pedido, codigo=codigo)
    try:
        depois = int(request.GET.get("depois", 0))
    except ValueError:
        depois = 0
    return JsonResponse({
        "ativo": pedido.chat_ativo,
        "mensagens": mensagens_depois(pedido, depois, leitor=Mensagem.ENTREGADOR),
    })


@staff_required
@require_POST
def entregador_chat_enviar(request, codigo):
    pedido = get_object_or_404(Pedido, codigo=codigo)
    if not pedido.chat_ativo:
        return JsonResponse({"ok": False, "erro": "O chat fica aberto enquanto o pedido está em andamento."}, status=403)
    try:
        mensagem = enviar_mensagem(pedido, Mensagem.ENTREGADOR, request.POST.get("texto"))
    except ValueError as erro:
        return JsonResponse({"ok": False, "erro": str(erro)}, status=400)
    return JsonResponse({"ok": True, "id": mensagem.id})


# ------------------------------------------------------------------ entregas
@staff_required
def entregas(request):
    abertos = Pedido.objects.select_related("cliente").exclude(status__in=[S.ENTREGUE, S.CANCELADO])
    return render(request, "painel/entregas.html", {
        "agendadas": abertos.filter(modalidade=Pedido.Modalidade.AGENDADA).order_by("data_agendada", "criado_em"),
        "rapidas": abertos.filter(
            modalidade=Pedido.Modalidade.RAPIDA, status__in=[S.PAGO, S.EM_PREPARO, S.SAIU_ENTREGA]
        ).order_by("criado_em"),
    })


# ---------------------------------------------------------------- relatórios
@staff_required
def relatorios_view(request):
    inicio, fim, ativo = relatorios.resolver_periodo(request.GET)
    contexto = relatorios.gerar(inicio, fim)
    contexto.update(presets=relatorios.PRESETS, preset_ativo=ativo,
                    de=inicio.isoformat(), ate=fim.isoformat())
    return render(request, "painel/relatorios.html", contexto)


@staff_required
def avaliacoes(request):
    queryset = AvaliacaoProduto.objects.select_related("pedido__cliente", "produto")
    resumo = queryset.aggregate(total=Count("id"), media=Avg("nota"))
    pagina = Paginator(queryset, 25).get_page(request.GET.get("pagina"))
    antigas = Paginator(
        AvaliacaoPedido.objects.select_related("pedido__cliente"), 25,
    ).get_page(request.GET.get("antigas_pagina"))
    return render(request, "painel/avaliacoes.html", {
        "avaliacoes_produtos": pagina.object_list,
        "pagina": pagina,
        "total": resumo["total"],
        "media": resumo["media"],
        "avaliacoes_antigas": antigas.object_list,
        "pagina_antigas": antigas,
    })


def _decimal_br(valor):
    return f"{valor:.2f}".replace(".", ",")


@staff_required
def relatorio_exportar(request):
    inicio, fim, _ = relatorios.resolver_periodo(request.GET)
    resposta = HttpResponse(content_type="text/csv; charset=utf-8")
    resposta["Content-Disposition"] = f'attachment; filename="golden-bites-{inicio}-{fim}.csv"'
    resposta.write("\ufeff")  # para o Excel abrir com acentos
    escritor = csv.writer(resposta, delimiter=";")
    escritor.writerow(["Data", "Tipo", "Categoria", "Descrição", "Valor (R$)"])
    for p in relatorios.pedidos_pagos(inicio, fim).select_related("cliente").order_by("pago_em"):
        escritor.writerow([
            timezone.localtime(p.pago_em).strftime("%d/%m/%Y"), "Entrada", "Pedido do site",
            f"Pedido {p.codigo} - {p.cliente.nome}", _decimal_br(p.total),
        ])
    for l in relatorios.lancamentos(inicio, fim).order_by("data", "id"):
        escritor.writerow([
            l.data.strftime("%d/%m/%Y"), l.get_tipo_display(), l.get_categoria_display(),
            l.descricao, _decimal_br(l.valor),
        ])
    return resposta


# ---------------------------------------------------------------- fidelidade
@staff_required
def fidelidade(request):
    config = ConfiguracaoLoja.obter()
    clientes = Cliente.objects.annotate(
        pontos=Coalesce(Sum("movimentos_pontos__pontos"), Value(0))
    ).order_by("-pontos", "nome")
    meta = max(config.pontos_resgate, 1)
    aparelhos = {r["cliente_id"]: r["n"] for r in Dispositivo.objects.values("cliente_id").annotate(n=Count("id")).order_by()}
    clientes = list(clientes)
    for c in clientes:
        c.trocas = c.pontos // meta
        c.aparelhos = aparelhos.get(c.id, 0)
    return render(request, "painel/fidelidade.html", {"clientes": clientes, "meta": meta})


@staff_required
@require_POST
def fidelidade_vinculo(request, pk):
    """Gera um código manual de recuperação quando o cliente perdeu o aparelho confiável."""
    cliente = get_object_or_404(Cliente, pk=pk)
    codigo = gerar_codigo_vinculo(cliente)
    messages.success(
        request,
        f"Código de {cliente.nome}: {codigo} (vale 15 minutos). Envie pelo WhatsApp do cliente "
        f"({cliente.telefone}) e só depois de conferir que é ele.",
    )
    return redirect("painel:fidelidade")


@staff_required
@require_POST
def fidelidade_remover_aparelhos(request, pk):
    """Desliga todos os aparelhos do cliente (celular perdido ou suspeita de uso indevido)."""
    cliente = get_object_or_404(Cliente, pk=pk)
    removidos, _ = Dispositivo.objects.filter(cliente=cliente).delete()
    Cliente.objects.filter(pk=cliente.pk).update(versao_recuperacao=F("versao_recuperacao") + 1)  # código antigo deixa de valer
    messages.success(request, f"{removidos} aparelho(s) de {cliente.nome} desligado(s) e o código de recuperação foi trocado.")
    return redirect("painel:fidelidade")


@staff_required
@require_POST
def fidelidade_ajuste(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    try:
        pontos = int(request.POST.get("pontos", ""))
    except ValueError:
        pontos = 0
    if pontos == 0:
        messages.error(request, "Informe uma quantidade de pontos diferente de zero (use - para descontar).")
    elif saldo_cliente(cliente) + pontos < 0:
        messages.error(request, "O saldo não pode ficar negativo.")
    else:
        MovimentoPontos.objects.create(
            cliente=cliente, tipo=MovimentoPontos.AJUSTE, pontos=pontos,
            observacao=request.POST.get("observacao", "").strip()[:160] or "Ajuste manual",
        )
        messages.success(request, f"{pontos:+d} ponto(s) para {cliente.nome}.")
    return redirect("painel:fidelidade")


# ---------------------------------------------------------------- configuração
class ConfiguracaoView(StaffMixin, UpdateView):
    form_class = modelform_factory(ConfiguracaoLoja, exclude=[])
    template_name = "painel/form.html"
    success_url = reverse_lazy("painel:configuracao")

    def get_object(self, queryset=None):
        return ConfiguracaoLoja.obter()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(titulo="Configurações da loja", url_voltar=reverse("painel:dashboard"))
        return ctx

    def form_valid(self, form):
        messages.success(self.request, "Configurações salvas.")
        return super().form_valid(form)


# ------------------------------------------------- CRUD genérico (fábrica)
def registrar(slug, modelo, campos, colunas, singular, plural, *, template_lista="painel/lista.html",
              widgets=None, queryset=None, criar=True, editar=True, excluir=True):
    """Gera lista, criar, editar e excluir para um modelo e devolve as rotas."""
    nome_lista = f"painel:{slug}_lista"
    form = modelform_factory(modelo, fields=campos, widgets=widgets or {})

    class Lista(StaffMixin, ListView):
        template_name = template_lista

        def get_queryset(self):
            return queryset() if queryset else modelo.objects.all()

        def get_context_data(self, **kwargs):
            ctx = super().get_context_data(**kwargs)
            linhas = []
            for obj in ctx["object_list"]:
                linhas.append({
                    "obj": obj,
                    "celulas": [funcao(obj) for _, funcao in colunas],
                    "editar": reverse(f"painel:{slug}_editar", args=[obj.pk]) if editar else None,
                    "excluir": reverse(f"painel:{slug}_excluir", args=[obj.pk]) if excluir else None,
                })
            ctx.update(
                plural=plural, singular=singular, linhas=linhas,
                cabecalhos=[nome for nome, _ in colunas],
                url_novo=reverse(f"painel:{slug}_novo") if criar else None,
            )
            return ctx

    class _Form:
        form_class = form
        template_name = "painel/form.html"
        success_url = reverse_lazy(nome_lista)

        def get_context_data(self, **kwargs):
            ctx = super().get_context_data(**kwargs)
            ctx["url_voltar"] = reverse(nome_lista)
            return ctx

    class Criar(StaffMixin, _Form, CreateView):
        def get_context_data(self, **kwargs):
            ctx = super().get_context_data(**kwargs)
            ctx["titulo"] = f"Novo: {singular}"
            return ctx

        def form_valid(self, f):
            messages.success(self.request, f"{singular} salvo.")
            return super().form_valid(f)

    class Editar(StaffMixin, _Form, UpdateView):
        model = modelo

        def get_context_data(self, **kwargs):
            ctx = super().get_context_data(**kwargs)
            ctx["titulo"] = f"Editar: {singular}"
            return ctx

        def form_valid(self, f):
            messages.success(self.request, f"{singular} atualizado.")
            return super().form_valid(f)

    class Excluir(StaffMixin, DeleteView):
        model = modelo
        template_name = "painel/excluir.html"
        success_url = reverse_lazy(nome_lista)

        def get_context_data(self, **kwargs):
            ctx = super().get_context_data(**kwargs)
            ctx.update(singular=singular, url_voltar=reverse(nome_lista))
            return ctx

        def form_valid(self, f):
            messages.success(self.request, f"{singular} removido.")
            return super().form_valid(f)

    Criar.model = modelo
    rotas = [path(f"{slug}/", Lista.as_view(), name=f"{slug}_lista")]
    if criar:
        rotas.append(path(f"{slug}/novo/", Criar.as_view(), name=f"{slug}_novo"))
    if editar:
        rotas.append(path(f"{slug}/<int:pk>/editar/", Editar.as_view(), name=f"{slug}_editar"))
    if excluir:
        rotas.append(path(f"{slug}/<int:pk>/excluir/", Excluir.as_view(), name=f"{slug}_excluir"))
    return rotas


def _sim_nao(valor):
    return "Sim" if valor else "Não"


def _km(valor):
    return "—" if valor is None else f"{valor:.1f} km".replace(".", ",")


ROTAS_CRUD = []
ROTAS_CRUD += registrar(
    "produtos", Produto,
    ["categoria", "nome", "descricao", "preco", "preco_promocional", "foto", "disponivel", "destaque",
     "pontos", "permite_troca", "pontos_troca", "ordem"],
    [], "produto", "Produtos", template_lista="painel/produtos.html",
    queryset=lambda: Produto.objects.select_related("categoria").prefetch_related("fotos"),
)
ROTAS_CRUD += registrar(
    "categorias", Categoria, ["nome", "ordem", "ativa"],
    [("Nome", lambda o: o.nome), ("Ordem", lambda o: o.ordem), ("Ativa", lambda o: _sim_nao(o.ativa))],
    "categoria", "Categorias",
)
ROTAS_CRUD += registrar(
    "faixas", FaixaTaxa, ["km_min", "km_max", "taxa", "ativa"],
    [("De", lambda o: _km(o.km_min)), ("Até", lambda o: _km(o.km_max)),
     ("Taxa", lambda o: brl(o.taxa)), ("Ativa", lambda o: _sim_nao(o.ativa))],
    "faixa de taxa", "Faixas de taxa de entrega",
)
ROTAS_CRUD += registrar(
    "bairros", Bairro, ["nome", "modalidade", "distancia_km", "ativo"],
    [("Nome", lambda o: o.nome), ("Modalidade", lambda o: o.get_modalidade_display()),
     ("Distância", lambda o: _km(o.distancia_km)), ("Ativo", lambda o: _sim_nao(o.ativo))],
    "bairro", "Bairros e regiões atendidos",
)
ROTAS_CRUD += registrar(
    "cupons", Cupom, ["codigo", "tipo", "valor", "minimo", "validade", "limite_usos", "ativo"],
    [("Código", lambda o: o.codigo), ("Tipo", lambda o: o.get_tipo_display()),
     ("Valor", lambda o: o.valor), ("Usos", lambda o: o.usos), ("Ativo", lambda o: _sim_nao(o.ativo))],
    "cupom", "Cupons",
    widgets={"validade": DateInput(attrs={"type": "date"}, format="%Y-%m-%d")},
)
ROTAS_CRUD += registrar(
    "clientes", Cliente, ["nome", "telefone", "email"],
    [("Nome", lambda o: o.nome), ("WhatsApp", lambda o: o.telefone), ("E-mail", lambda o: o.email or "—"),
     ("Pedidos", lambda o: o.n_pedidos), ("Total gasto", lambda o: brl(o.gasto or 0))],
    "cliente", "Clientes", criar=False, excluir=False,
    queryset=lambda: Cliente.objects.annotate(
        n_pedidos=Count("pedidos"),
        gasto=Sum("pedidos__total", filter=~Q(pedidos__status=S.CANCELADO)),
    ),
)
ROTAS_CRUD += registrar(
    "lancamentos", Lancamento, ["data", "tipo", "categoria", "descricao", "valor"],
    [("Data", lambda o: o.data.strftime("%d/%m/%Y")), ("Tipo", lambda o: o.get_tipo_display()),
     ("Categoria", lambda o: o.get_categoria_display()), ("Descrição", lambda o: o.descricao),
     ("Valor", lambda o: brl(o.valor))],
    "lançamento", "Entradas e saídas (lançamentos)",
    widgets={"data": DateInput(attrs={"type": "date"}, format="%Y-%m-%d")},
)