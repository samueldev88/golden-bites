from unittest.mock import patch

from django.test import TestCase

from catalogo.models import ConfiguracaoLoja

from .cep import _avaliar


class CepsDoCheckoutTests(TestCase):
    def test_cliente_nao_escolhe_bairro_ou_numero_usados_no_preco(self):
        resposta_cep = {
            "rua": "",
            "bairro": "",
            "cidade": "Rio de Janeiro",
            "uf": "RJ",
            "lat": None,
            "lon": None,
        }
        with (
            patch("entregas.cep.consultar_cep", return_value=resposta_cep),
            patch("entregas.cep._distancia_do_bairro_cadastrado", return_value=None) as distancia_bairro,
            patch("entregas.cep.geocodificar", return_value=None) as geocodificar,
        ):
            resultado = _avaliar(
                "22790000",
                "Bairro escolhido pelo cliente",
                ConfiguracaoLoja.obter(),
                "9999",
            )

        self.assertEqual(resultado["zona"], "desconhecida")
        distancia_bairro.assert_called_once_with("")
        self.assertEqual(geocodificar.call_args.args[1:3], ("", ""))
