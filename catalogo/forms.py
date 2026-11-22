import re

from django import forms
from django.core.exceptions import ValidationError

from .models import SolicitacaoLGPD


class SolicitacaoLGPDForm(forms.ModelForm):
    class Meta:
        model = SolicitacaoLGPD
        fields = ("nome", "email", "telefone", "tipo", "codigo_pedido", "descricao")
        labels = {
            "nome": "Seu nome",
            "email": "E-mail",
            "telefone": "WhatsApp",
            "tipo": "Tipo de solicitação",
            "codigo_pedido": "Código do pedido (opcional)",
            "descricao": "Como podemos ajudar?",
        }
        help_texts = {
            "email": "Informe um e-mail ou WhatsApp para receber a resposta.",
            "telefone": "Informe um e-mail ou WhatsApp para receber a resposta.",
            "descricao": "Não inclua senhas, dados completos de cartão ou documentos desnecessários.",
        }
        widgets = {
            "nome": forms.TextInput(attrs={"autocomplete": "name"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "telefone": forms.TelInput(attrs={"autocomplete": "tel", "inputmode": "tel"}),
            "codigo_pedido": forms.TextInput(attrs={"autocomplete": "off"}),
            "descricao": forms.Textarea(attrs={"rows": 4, "maxlength": 2000}),
        }

    def clean_nome(self):
        return self.cleaned_data["nome"].strip()

    def clean_telefone(self):
        telefone = re.sub(r"\D", "", self.cleaned_data.get("telefone", ""))
        if telefone and len(telefone) not in (10, 11, 12, 13):
            raise ValidationError("Informe um WhatsApp com DDD e número válidos.")
        return telefone

    def clean_codigo_pedido(self):
        return self.cleaned_data.get("codigo_pedido", "").strip().upper()

    def clean_descricao(self):
        return self.cleaned_data["descricao"].strip()

    def clean(self):
        dados = super().clean()
        if not dados.get("email") and not dados.get("telefone"):
            raise ValidationError("Informe um e-mail ou WhatsApp para recebermos a resposta.")
        return dados
