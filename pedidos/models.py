from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string

from catalogo.models import ConfiguracaoLoja, Produto
from entregas.models import Bairro
from entregas.services import minutos_previstos

CENTAVOS = Decimal("0.01")
ZERO = Decimal("0.00")


class Cupom(models.Model):
    PERCENTUAL = "percentual"
    VALOR = "valor"
    FRETE = "frete"
    TIPOS = [
        (PERCENTUAL, "Percentual sobre os produtos (%)"),
        (VALOR, "Valor fixo (R$)"),
        (FRETE, "Frete grátis"),
    ]

    codigo = models.CharField(max_length=30, unique=True)
    tipo = models.CharField(max_length=12, choices=TIPOS, default=PERCENTUAL)
    valor = models.DecimalField(
        max_digits=8, decimal_places=2, default=ZERO,
        help_text="% ou R$, conforme o tipo. Ignorado no frete grátis.",
    )
    minimo = models.DecimalField("Pedido mínimo (R$)", max_digits=8, decimal_places=2, default=ZERO)
    validade = models.DateField(null=True, blank=True)
    limite_usos = models.PositiveIntegerField(null=True, blank=True, help_text="Vazio = ilimitado.")
    usos = models.PositiveIntegerField(default=0, editable=False)
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return self.codigo

    def save(self, *args, **kwargs):
        self.codigo = self.codigo.strip().upper()
        super().save(*args, **kwargs)

    def validar(self, subtotal):
        """Retorna (ok, mensagem)."""
        if not self.ativo:
            return False, "Este cupom não está ativo."
        if self.validade and self.validade < timezone.localdate():
            return False, "Este cupom expirou."
        if self.limite_usos is not None and self.usos >= self.limite_usos:
            return False, "Este cupom atingiu o limite de usos."
        if subtotal < self.minimo:
            return False, f"Pedido mínimo para este cupom: R$ {self.minimo:.2f}".replace(".", ",")
        return True, ""

    def desconto_para(self, subtotal, taxa):
        subtotal = Decimal(subtotal)
        if self.tipo == self.PERCENTUAL:
            valor = subtotal * self.valor / Decimal("100")
        elif self.tipo == self.VALOR:
            valor = min(self.valor, subtotal)
        else:  # frete grátis
            valor = Decimal(taxa) if taxa is not None else ZERO
        return valor.quantize(CENTAVOS, rounding=ROUND_HALF_UP)


class Cliente(models.Model):
    nome = models.CharField(max_length=120)
    telefone = models.CharField(max_length=20, unique=True)
    email = models.EmailField(blank=True)
    versao_recuperacao = models.PositiveSmallIntegerField(default=1, editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} ({self.telefone})"


class Pedido(models.Model):
    class Status(models.TextChoices):
        AGUARDANDO_CONFIRMACAO = "aguardando_confirmacao", "Aguardando confirmação da entrega"
        AGUARDANDO_PAGAMENTO = "aguardando_pagamento", "Aguardando pagamento"
        PAGO = "pago", "Pago"
        EM_PREPARO = "em_preparo", "Em preparo"
        SAIU_ENTREGA = "saiu_entrega", "Saiu para entrega"
        ENTREGUE = "entregue", "Entregue"
        CANCELADO = "cancelado", "Cancelado"

    class Modalidade(models.TextChoices):
        RAPIDA = "rapida", "Entrega rápida"
        AGENDADA = "agendada", "Entrega agendada"

    class Pagamento(models.TextChoices):
        PIX = "pix", "Pix"
        CARTAO = "cartao", "Cartão"

    STATUS_PAGOS = ["pago", "em_preparo", "saiu_entrega", "entregue"]
    # próximo passo do fluxo: status atual -> (novo status, texto do botão)
    PROXIMOS = {
        "aguardando_pagamento": ("pago", "Confirmar pagamento"),
        "pago": ("em_preparo", "Iniciar preparo"),
        "em_preparo": ("saiu_entrega", "Saiu para entrega"),
        "saiu_entrega": ("entregue", "Marcar entregue"),
    }

    codigo = models.CharField(max_length=12, unique=True, editable=False)
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="pedidos")
    modalidade = models.CharField(max_length=10, choices=Modalidade.choices)
    bairro = models.ForeignKey(Bairro, null=True, blank=True, on_delete=models.SET_NULL)
    bairro_nome = models.CharField(max_length=100)
    cep = models.CharField(max_length=9, blank=True)
    rua = models.CharField(max_length=150)
    numero = models.CharField(max_length=20)
    complemento = models.CharField(max_length=80, blank=True)
    referencia = models.CharField(max_length=120, blank=True)
    data_agendada = models.DateField(null=True, blank=True)
    horario_combinado = models.CharField("Horário desejado", max_length=80, blank=True)
    distancia_km = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    # destino no mapa (só guardado quando a localização é confiável) e posição ao vivo do entregador
    destino_lat = models.FloatField(null=True, blank=True, editable=False)
    destino_lon = models.FloatField(null=True, blank=True, editable=False)
    destino_precisao = models.CharField(max_length=10, blank=True, editable=False)
    entregador_lat = models.FloatField(null=True, blank=True, editable=False)
    entregador_lon = models.FloatField(null=True, blank=True, editable=False)
    entregador_em = models.DateTimeField(null=True, blank=True, editable=False)
    # previsão de entrega (só entrega rápida), horário real e código de confirmação
    prazo_entrega = models.DateTimeField(null=True, blank=True, editable=False)
    entregue_em = models.DateTimeField(null=True, blank=True, editable=False)
    codigo_entrega = models.CharField(max_length=4, blank=True, editable=False)
    tentativas_codigo = models.PositiveSmallIntegerField(default=0, editable=False)

    subtotal = models.DecimalField(max_digits=8, decimal_places=2, default=ZERO)
    taxa_entrega = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    desconto = models.DecimalField(max_digits=8, decimal_places=2, default=ZERO)
    total = models.DecimalField(max_digits=8, decimal_places=2, default=ZERO)
    cupom = models.ForeignKey(Cupom, null=True, blank=True, on_delete=models.SET_NULL)
    pontos_resgatados = models.PositiveSmallIntegerField(default=0)
    desconto_fidelidade = models.DecimalField(max_digits=8, decimal_places=2, default=ZERO)
    pago_em = models.DateTimeField(null=True, blank=True, editable=False)

    status = models.CharField(max_length=24, choices=Status.choices, default=Status.AGUARDANDO_PAGAMENTO)
    forma_pagamento = models.CharField(max_length=10, choices=Pagamento.choices, default=Pagamento.PIX)
    mp_preference_id = models.CharField(max_length=80, blank=True)
    mp_init_point = models.URLField(max_length=300, blank=True)
    mp_payment_id = models.CharField(max_length=40, blank=True)
    mp_status = models.CharField(max_length=30, blank=True)

    observacoes = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado_em"]

    def __str__(self):
        return self.codigo

    def save(self, *args, **kwargs):
        if not self.codigo:
            while True:
                codigo = "MT-" + get_random_string(8, "ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
                if not Pedido.objects.filter(codigo=codigo).exists():
                    self.codigo = codigo
                    break
        if not self.codigo_entrega:
            self.codigo_entrega = get_random_string(4, "0123456789")
        agora = timezone.now()
        alterados = []
        if self.status in self.STATUS_PAGOS and self.pago_em is None:
            self.pago_em = agora
            alterados.append("pago_em")
            if self.modalidade == self.Modalidade.RAPIDA and self.prazo_entrega is None:
                minutos = minutos_previstos(self.distancia_km, ConfiguracaoLoja.obter())
                self.prazo_entrega = agora + timedelta(minutes=minutos)
                alterados.append("prazo_entrega")
        if self.status == self.Status.ENTREGUE and self.entregue_em is None:
            self.entregue_em = agora
            alterados.append("entregue_em")
        campos = kwargs.get("update_fields")
        if campos is not None:
            kwargs["update_fields"] = list(campos) + alterados + (
                ["codigo_entrega"] if self.pk and "codigo_entrega" not in campos else [])
        super().save(*args, **kwargs)
        # credita ou estorna pontos de fidelidade conforme o status (idempotente)
        from fidelidade.services import sincronizar_pedido
        sincronizar_pedido(self)

    def recalcular(self):
        """Recalcula desconto e total a partir de subtotal, taxa e cupom."""
        if self.cupom_id:
            self.desconto = self.cupom.desconto_para(self.subtotal, self.taxa_entrega)
        taxa = self.taxa_entrega or ZERO
        self.total = max(self.subtotal + taxa - self.desconto - self.desconto_fidelidade, ZERO)

    @property
    def atraso_min(self):
        """Minutos de atraso (0 se está no prazo ou se não há prazo)."""
        if not self.prazo_entrega:
            return 0
        referencia = self.entregue_em or timezone.now()
        return max(0, int((referencia - self.prazo_entrega).total_seconds() // 60))

    @property
    def pontos_atraso(self):
        """1 ponto de fidelidade a cada 5 minutos completos de atraso."""
        pontos = self.atraso_min // 5
        limite = ConfiguracaoLoja.obter().max_pontos_atraso
        return min(pontos, limite) if limite else pontos

    @property
    def atrasado(self):
        return bool(self.prazo_entrega) and self.status in ("pago", "em_preparo", "saiu_entrega") \
            and timezone.now() > self.prazo_entrega

    def garantir_codigo(self):
        """Pedidos antigos (de antes do código) ganham o código na primeira vez que ele é preciso."""
        if not self.codigo_entrega:
            self.codigo_entrega = get_random_string(4, "0123456789")
            Pedido.objects.filter(pk=self.pk).update(codigo_entrega=self.codigo_entrega)

    @property
    def chat_ativo(self):
        """O chat com o entregador fica aberto enquanto o pedido está em andamento."""
        return self.status in ("pago", "em_preparo", "saiu_entrega")

    @property
    def link_mapa(self):
        """Link do Google Maps para o endereço (coordenadas só quando são precisas)."""
        from urllib.parse import quote
        if self.destino_lat is not None and self.destino_lon is not None and self.destino_precisao in ("endereco", "gps"):
            consulta = f"{self.destino_lat},{self.destino_lon}"
        else:
            consulta = quote(f"{self.rua}, {self.numero}, {self.bairro_nome}, {self.cep}")
        return f"https://www.google.com/maps/search/?api=1&query={consulta}"

    @property
    def proximo(self):
        return self.PROXIMOS.get(self.status)

    @property
    def pontos_ganhos(self):
        return sum(i.pontos * i.quantidade for i in self.itens.all())

    @property
    def aguarda_pagamento(self):
        return self.status == self.Status.AGUARDANDO_PAGAMENTO

    @property
    def endereco_completo(self):
        partes = [f"{self.rua}, {self.numero}"]
        if self.complemento:
            partes.append(self.complemento)
        partes.append(self.bairro_nome)
        if self.cep:
            partes.append(f"CEP {self.cep}")
        return " - ".join(partes)

    @property
    def etapa(self):
        """Posição na linha do tempo (0 a 3); None quando cancelado."""
        S = self.Status
        if self.status == S.CANCELADO.value:
            return None
        return {
            S.AGUARDANDO_CONFIRMACAO.value: 0,
            S.AGUARDANDO_PAGAMENTO.value: 0,
            S.PAGO.value: 1,
            S.EM_PREPARO.value: 2,
            S.SAIU_ENTREGA.value: 3,
            S.ENTREGUE.value: 4,
        }[self.status]


class ItemPedido(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="itens")
    produto = models.ForeignKey(Produto, null=True, blank=True, on_delete=models.SET_NULL)
    nome = models.CharField(max_length=120)
    preco_unitario = models.DecimalField(max_digits=8, decimal_places=2)
    quantidade = models.PositiveSmallIntegerField()
    pontos = models.PositiveSmallIntegerField("Pontos por unidade", default=1)
    resgate = models.BooleanField("Troca de pontos", default=False)
    pontos_resgate = models.PositiveSmallIntegerField("Pontos gastos por unidade", default=0)

    def __str__(self):
        return f"{self.quantidade}x {self.nome}"

    @property
    def subtotal(self):
        return self.preco_unitario * self.quantidade


class Mensagem(models.Model):
    """Chat entre o cliente e o entregador, ligado a um pedido."""

    CLIENTE = "cliente"
    ENTREGADOR = "entregador"
    AUTORES = [(CLIENTE, "Cliente"), (ENTREGADOR, "Entregador")]

    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="mensagens")
    autor = models.CharField(max_length=10, choices=AUTORES)
    texto = models.CharField(max_length=500)
    lida = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.pedido_id} {self.autor}: {self.texto[:30]}"


class AvaliacaoPedido(models.Model):
    class Nota(models.IntegerChoices):
        UMA = 1, "1 estrela"
        DUAS = 2, "2 estrelas"
        TRES = 3, "3 estrelas"
        QUATRO = 4, "4 estrelas"
        CINCO = 5, "5 estrelas"

    pedido = models.OneToOneField(Pedido, on_delete=models.CASCADE, related_name="avaliacao")
    nota = models.PositiveSmallIntegerField(choices=Nota.choices)
    comentario = models.CharField(max_length=1000)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(nota__gte=1, nota__lte=5),
                name="avaliacao_pedido_nota_1_5",
            ),
        ]

    def __str__(self):
        return f"{self.pedido.codigo}: {self.nota}/5"

    @property
    def estrelas(self):
        return "★" * self.nota + "☆" * (5 - self.nota)


class AvaliacaoProduto(models.Model):
    class Nota(models.IntegerChoices):
        UMA = 1, "1 estrela"
        DUAS = 2, "2 estrelas"
        TRES = 3, "3 estrelas"
        QUATRO = 4, "4 estrelas"
        CINCO = 5, "5 estrelas"

    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="avaliacoes_produtos")
    produto = models.ForeignKey(
        "catalogo.Produto", on_delete=models.CASCADE, related_name="avaliacoes"
    )
    nota = models.PositiveSmallIntegerField(choices=Nota.choices)
    comentario = models.CharField(max_length=1000)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
        constraints = [
            models.UniqueConstraint(fields=["pedido", "produto"], name="avaliacao_produto_pedido_unico"),
            models.CheckConstraint(
                condition=models.Q(nota__gte=1, nota__lte=5),
                name="avaliacao_produto_nota_1_5",
            ),
        ]

    def __str__(self):
        return f"{self.produto} · {self.pedido.codigo}: {self.nota}/5"

    @property
    def estrelas(self):
        return "★" * self.nota + "☆" * (5 - self.nota)

    @property
    def nome_publico(self):
        partes = self.pedido.cliente.nome.split()
        if not partes:
            return "Cliente verificado"
        if len(partes) == 1:
            return partes[0]
        return f"{partes[0]} {partes[-1][0]}."