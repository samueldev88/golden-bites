from django.db import models


class FaixaTaxa(models.Model):
    """Faixa de distância e a taxa de entrega correspondente (editável no painel)."""

    km_min = models.DecimalField("De (km)", max_digits=5, decimal_places=1)
    km_max = models.DecimalField("Até (km)", max_digits=5, decimal_places=1)
    taxa = models.DecimalField("Taxa (R$)", max_digits=8, decimal_places=2)
    ativa = models.BooleanField(default=True)

    class Meta:
        ordering = ["km_min"]
        verbose_name = "faixa de taxa"
        verbose_name_plural = "faixas de taxa"

    def __str__(self):
        return f"{self.km_min} a {self.km_max} km: R$ {self.taxa}"


class Bairro(models.Model):
    """Local atendido. Na entrega rápida a taxa vem da distância; na agendada,
    sem distância cadastrada, a taxa fica 'a consultar'."""

    RAPIDA = "rapida"
    AGENDADA = "agendada"
    MODALIDADES = [
        (RAPIDA, "Entrega rápida (Recreio, de bicicleta)"),
        (AGENDADA, "Entrega agendada (outros bairros)"),
    ]

    nome = models.CharField(max_length=100)
    modalidade = models.CharField(max_length=10, choices=MODALIDADES, default=RAPIDA)
    distancia_km = models.DecimalField(
        "Distância da loja (km)", max_digits=5, decimal_places=1, null=True, blank=True,
        help_text="Vazio = taxa a consultar.",
    )
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["modalidade", "distancia_km", "nome"]

    def __str__(self):
        return self.nome
