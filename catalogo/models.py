from decimal import Decimal

from django.db import models
from django.utils.text import slugify

from .validators import validar_extensao_imagem, validar_imagem_produto


def slug_unico(modelo, texto, pk=None):
    base = slugify(texto) or "item"
    slug, n = base, 2
    while modelo.objects.filter(slug=slug).exclude(pk=pk).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


class ConfiguracaoLoja(models.Model):
    """Registro único com os dados gerais da loja (editável no painel)."""

    nome = models.CharField(max_length=80, default="Golden Bites")
    slogan = models.CharField(max_length=120, default="Um doce momento, onde você estiver.")
    cidade_texto = models.CharField(
        "Localização", max_length=120, default="Recreio dos Bandeirantes - Rio de Janeiro, RJ"
    )
    horario_texto = models.CharField(
        "Texto do horário", max_length=80, default="Aberto até às 18h",
        help_text="Aparece ao lado do nome da loja. Ex.: Aberto até às 18h",
    )
    loja_aberta = models.BooleanField(
        "Loja aberta para pedidos", default=True,
        help_text="Desmarque para pausar a loja (mostra 'Fechado' e bloqueia novos pedidos).",
    )
    whatsapp = models.CharField(
        "WhatsApp", max_length=20, blank=True,
        help_text="Somente números, com DDI e DDD. Ex.: 5521999999999",
    )
    pedido_minimo = models.DecimalField(
        "Pedido mínimo (R$)", max_digits=8, decimal_places=2, default=Decimal("0.00")
    )
    antecedencia_agendada_dias = models.PositiveSmallIntegerField(
        "Antecedência mínima da entrega agendada (dias)", default=1
    )
    latitude = models.FloatField(
        "Latitude da loja", default=-23.0200,
        help_text="No Google Maps, clique com o botão direito no ponto de saída das entregas e copie o 1º número.",
    )
    longitude = models.FloatField("Longitude da loja", default=-43.4650, help_text="O 2º número do Google Maps.")
    raio_rapida_km = models.PositiveSmallIntegerField(
        "Raio da entrega rápida (km)", default=12,
        help_text="Até essa distância em linha reta a entrega rápida (bicicleta) fica disponível.",
    )
    raio_maximo_km = models.PositiveSmallIntegerField(
        "Raio máximo de entrega (km)", default=20,
        help_text="Entre o raio rápido e este valor só entrega agendada. Acima, não entregamos.",
    )
    veiculo = models.CharField(
        "Veículo das entregas", max_length=10, default="moto",
        choices=[("moto", "Moto"), ("bicicleta", "Bicicleta")],
        help_text="Define o tipo de rota calculada (ruas que a moto usa ou ciclovias).",
    )
    velocidade_bike_kmh = models.PositiveSmallIntegerField(
        "Velocidade média do entregador (km/h)", default=25,
        help_text="Usada para estimar o tempo de entrega. Moto: cerca de 25. Bicicleta: cerca de 15.",
    )
    tempo_preparo_min = models.PositiveSmallIntegerField(
        "Tempo de preparo do pedido (min)", default=20,
        help_text="Somado ao tempo de trajeto para formar a previsão de entrega.",
    )
    max_pontos_atraso = models.PositiveSmallIntegerField(
        "Limite de pontos por atraso (0 = sem limite)", default=0,
        help_text="Cliente ganha 1 ponto de fidelidade a cada 5 min de atraso na entrega rápida.",
    )
    fidelidade_ativa = models.BooleanField("Programa de fidelidade ativo", default=True)
    pontos_resgate = models.PositiveSmallIntegerField(
        "Pontos para trocar por 1 item grátis (padrão)", default=8,
        help_text="Cada item pedido vale pontos (veja o campo 'pontos' de cada produto). Cada produto pode ter um custo próprio.",
    )
    sobre = models.TextField(
        "Texto 'Sobre'", blank=True,
        default="Doces artesanais feitos em pequenos lotes, com ingredientes selecionados "
                "e acabamento de confeitaria fina.",
    )

    class Meta:
        verbose_name = "Configuração da loja"
        verbose_name_plural = "Configuração da loja"

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def obter(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class SolicitacaoLGPD(models.Model):
    class Tipo(models.TextChoices):
        ACESSO = "acesso", "Confirmação e acesso aos dados"
        CORRECAO = "correcao", "Correção ou atualização"
        EXCLUSAO = "exclusao", "Exclusão, anonimização ou bloqueio"
        COMPARTILHAMENTO = "compartilhamento", "Informações sobre uso e compartilhamento"
        PORTABILIDADE = "portabilidade", "Portabilidade"
        REVOGACAO = "revogacao", "Revogação de consentimento ou oposição"
        OUTRO = "outro", "Outra solicitação relacionada à LGPD"

    class Status(models.TextChoices):
        NOVA = "nova", "Nova"
        EM_ANALISE = "em_analise", "Em análise"
        CONCLUIDA = "concluida", "Concluída"

    nome = models.CharField(max_length=120)
    email = models.EmailField(blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    tipo = models.CharField(max_length=24, choices=Tipo.choices)
    codigo_pedido = models.CharField(max_length=12, blank=True)
    descricao = models.TextField(max_length=2000)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NOVA)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "solicitação LGPD"
        verbose_name_plural = "solicitações LGPD"

    def __str__(self):
        return f"{self.get_tipo_display()} — {self.nome}"


class Categoria(models.Model):
    nome = models.CharField(max_length=60)
    slug = models.SlugField(max_length=70, unique=True, blank=True)
    ordem = models.PositiveSmallIntegerField(default=0)
    ativa = models.BooleanField(default=True)

    class Meta:
        ordering = ["ordem", "nome"]

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slug_unico(Categoria, self.nome, self.pk)
        super().save(*args, **kwargs)


class Produto(models.Model):
    categoria = models.ForeignKey(
        Categoria, null=True, blank=True, on_delete=models.SET_NULL, related_name="produtos"
    )
    nome = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    descricao = models.TextField("Descrição", blank=True)
    preco = models.DecimalField("Preço (R$)", max_digits=8, decimal_places=2)
    preco_promocional = models.DecimalField(
        "Preço promocional (R$)", max_digits=8, decimal_places=2, null=True, blank=True,
        help_text="Deixe vazio se não houver promoção.",
    )
    foto = models.ImageField(
        upload_to="produtos/", blank=True,
        validators=[validar_extensao_imagem, validar_imagem_produto],
    )
    disponivel = models.BooleanField("Disponível", default=True)
    destaque = models.BooleanField("Em alta (aparece na página inicial)", default=False)
    pontos = models.PositiveSmallIntegerField(
        "Pontos de fidelidade por unidade", default=1,
        help_text="Pontos que cada unidade pedida gera. Ex.: 1 para um item; kits e caixas podem valer mais.",
    )
    pontos_troca = models.PositiveSmallIntegerField(
        "Pontos para trocar por este item", null=True, blank=True,
        help_text="Vazio = usa o padrão da loja (Painel > Loja).",
    )
    permite_troca = models.BooleanField("Pode ser trocado por pontos", default=True)
    ordem = models.PositiveSmallIntegerField(default=0)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-disponivel", "ordem", "nome"]

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slug_unico(Produto, self.nome, self.pk)
        super().save(*args, **kwargs)

    @property
    def galeria(self):
        """URLs das fotos na ordem em que aparecem: capa primeiro, depois as extras (use prefetch_related('fotos'))."""
        urls = [self.foto.url] if self.foto else []
        urls += [f.imagem.url for f in self.fotos.all()]
        return urls

    def custo_troca(self, config):
        """Pontos necessários para trocar 1 unidade deste item por pontos."""
        return self.pontos_troca if self.pontos_troca else config.pontos_resgate

    @property
    def em_promocao(self):
        return self.preco_promocional is not None and self.preco_promocional < self.preco

    @property
    def preco_final(self):
        return self.preco_promocional if self.em_promocao else self.preco

    @property
    def desconto_percentual(self):
        if not self.em_promocao:
            return 0
        return int(round((1 - self.preco_promocional / self.preco) * 100))


class FotoProduto(models.Model):
    """Fotos extras do produto (a capa é o campo 'foto' do produto). Passam sozinhas na loja."""

    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name="fotos")
    imagem = models.ImageField(
        upload_to="produtos/galeria/",
        validators=[validar_extensao_imagem, validar_imagem_produto],
    )
    ordem = models.PositiveSmallIntegerField(default=0)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ordem", "id"]
        verbose_name = "foto do produto"
        verbose_name_plural = "fotos do produto"

    def __str__(self):
        return f"Foto {self.pk} de {self.produto_id}"