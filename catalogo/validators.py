from pathlib import Path
import warnings

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from PIL import Image, UnidentifiedImageError

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 30_000_000
EXTENSOES_IMAGEM = ("jpg", "jpeg", "png", "webp")
FORMATOS_POR_EXTENSAO = {
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
}
validar_extensao_imagem = FileExtensionValidator(allowed_extensions=EXTENSOES_IMAGEM)


def validar_imagem_produto(arquivo):
    if arquivo.size > MAX_UPLOAD_BYTES:
        raise ValidationError("A imagem deve ter no máximo 8 MB.")

    try:
        arquivo.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            imagem = Image.open(arquivo)
            extensao = Path(arquivo.name).suffix.lower().lstrip(".")
            if imagem.format != FORMATOS_POR_EXTENSAO.get(extensao):
                raise ValidationError("Envie uma imagem JPG, PNG ou WEBP.")
            if imagem.width * imagem.height > MAX_IMAGE_PIXELS:
                raise ValidationError("A imagem excede o limite de resolução permitido.")
            imagem.verify()
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as erro:
        raise ValidationError("O arquivo não é uma imagem válida.") from erro
    finally:
        arquivo.seek(0)
