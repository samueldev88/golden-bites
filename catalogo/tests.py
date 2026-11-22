from io import BytesIO

from PIL import Image
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import Produto, SolicitacaoLGPD
from .validators import MAX_UPLOAD_BYTES, validar_imagem_produto


class UploadImagemTests(TestCase):
    def test_product_image_validator_accepts_a_real_web_image(self):
        conteudo = BytesIO()
        Image.new("RGB", (20, 20), color="white").save(conteudo, format="PNG")
        produto = Produto(
            nome="Teste",
            preco="5.00",
            foto=SimpleUploadedFile("produto.png", conteudo.getvalue(), content_type="image/png"),
        )

        produto.full_clean()

    def test_product_image_validator_rejects_non_images(self):
        arquivo = SimpleUploadedFile("produto.png", b"not an image", content_type="image/png")

        with self.assertRaises(ValidationError):
            validar_imagem_produto(arquivo)

    def test_product_image_validator_rejects_an_extension_format_mismatch(self):
        conteudo = BytesIO()
        Image.new("RGB", (20, 20), color="white").save(conteudo, format="PNG")
        arquivo = SimpleUploadedFile("produto.jpg", conteudo.getvalue(), content_type="image/jpeg")

        with self.assertRaises(ValidationError):
            validar_imagem_produto(arquivo)

    def test_product_image_validator_rejects_oversized_files(self):
        arquivo = SimpleUploadedFile(
            "produto.png",
            b"x" * (MAX_UPLOAD_BYTES + 1),
            content_type="image/png",
        )

        with self.assertRaises(ValidationError):
            validar_imagem_produto(arquivo)


class PoliticasTests(TestCase):
    def test_politicas_page_contains_documents_and_request_form(self):
        response = self.client.get(reverse("catalogo:politicas"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Política de Privacidade")
        self.assertContains(response, "Termos de Serviço")
        self.assertContains(response, "Aviso de Cookies")
        self.assertContains(response, "Política de Cancelamento e Reembolso")
        self.assertContains(response, "Formulário de Solicitações LGPD")
        self.assertContains(response, "Samuel Cordeiro De Araujo")
        self.assertContains(response, 'id="solicitacao-lgpd"')
        self.assertContains(response, 'id="conformidade-lgpd"')

    def test_home_places_faq_above_footer_storage_notice(self):
        response = self.client.get(reverse("catalogo:home"))
        conteudo = response.content.decode()

        pos_faq = conteudo.index("Perguntas frequentes")
        pos_marca = conteudo.index("<strong>", pos_faq)
        pos_aviso = conteudo.index("Usamos armazenamento essencial", pos_marca)

        self.assertLess(pos_faq, pos_marca)
        self.assertLess(pos_marca, pos_aviso)

    def test_lgpd_request_is_saved_for_manual_follow_up(self):
        response = self.client.post(
            reverse("catalogo:politicas"),
            {
                "nome": "Ana Silva",
                "email": "ana@example.com",
                "telefone": "",
                "tipo": SolicitacaoLGPD.Tipo.ACESSO,
                "codigo_pedido": "",
                "descricao": "Quero acessar meus dados.",
            },
        )

        self.assertEqual(response.status_code, 302)
        solicitacao = SolicitacaoLGPD.objects.get()
        self.assertEqual(solicitacao.nome, "Ana Silva")
        self.assertEqual(solicitacao.status, SolicitacaoLGPD.Status.NOVA)

    def test_lgpd_request_requires_a_reply_contact(self):
        response = self.client.post(
            reverse("catalogo:politicas"),
            {
                "nome": "Ana Silva",
                "email": "",
                "telefone": "",
                "tipo": SolicitacaoLGPD.Tipo.ACESSO,
                "codigo_pedido": "",
                "descricao": "Quero acessar meus dados.",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(SolicitacaoLGPD.objects.count(), 0)
