from django.db import models


class MovimentoPontos(models.Model):
    """Extrato de pontos. O saldo do cliente é a soma dos movimentos."""

    GANHO = "ganho"
    RESGATE = "resgate"
    ESTORNO_GANHO = "estorno_ganho"
    ESTORNO_RESGATE = "estorno_resgate"
    AJUSTE = "ajuste"
    BONUS_ATRASO = "bonus_atraso"
    TIPOS = [
        (GANHO, "Pontos ganhos"),
        (RESGATE, "Troca por item"),
        (ESTORNO_GANHO, "Pontos estornados (pedido cancelado)"),
        (ESTORNO_RESGATE, "Pontos devolvidos (pedido cancelado)"),
        (AJUSTE, "Ajuste manual"),
        (BONUS_ATRASO, "Pontos por atraso na entrega"),
    ]

    cliente = models.ForeignKey("pedidos.Cliente", on_delete=models.CASCADE, related_name="movimentos_pontos")
    pedido = models.ForeignKey(
        "pedidos.Pedido", null=True, blank=True, on_delete=models.SET_NULL, related_name="movimentos_pontos"
    )
    tipo = models.CharField(max_length=16, choices=TIPOS)
    pontos = models.IntegerField(help_text="Positivo soma, negativo desconta.")
    observacao = models.CharField(max_length=160, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "-id"]
        verbose_name = "movimento de pontos"
        verbose_name_plural = "movimentos de pontos"

    def __str__(self):
        return f"{self.cliente_id}: {self.pontos:+d} ({self.get_tipo_display()})"


class Dispositivo(models.Model):
    """Aparelho de confiança de um cliente. Só ele vê o saldo e troca pontos (sem login nem senha)."""

    cliente = models.ForeignKey("pedidos.Cliente", on_delete=models.CASCADE, related_name="dispositivos")
    token_hash = models.CharField(max_length=64, unique=True)  # o token em si só existe no cookie do cliente
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "aparelho de confiança"
        verbose_name_plural = "aparelhos de confiança"

    def __str__(self):
        return f"Aparelho {self.pk} de {self.cliente_id}"


class CodigoVinculo(models.Model):
    """Código temporário de vínculo, gerado pelo aparelho confiável ou pela loja."""

    cliente = models.ForeignKey("pedidos.Cliente", on_delete=models.CASCADE, related_name="codigos_vinculo")
    codigo_hash = models.CharField(max_length=64)
    expira_em = models.DateTimeField()
    usado = models.BooleanField(default=False)
    tentativas = models.PositiveSmallIntegerField(default=0)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "código de vínculo"
        verbose_name_plural = "códigos de vínculo"


class LimiteTentativas(models.Model):
    """Contador de tentativas compartilhado e atualizado atomicamente entre processos."""

    chave = models.CharField(max_length=64, unique=True)
    tentativas = models.PositiveIntegerField(default=1)
    expira_em = models.DateTimeField(db_index=True)