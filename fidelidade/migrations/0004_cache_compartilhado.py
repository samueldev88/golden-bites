from django.core.management import call_command
from django.db import migrations


def criar_cache(apps, schema_editor):
    call_command(
        "createcachetable",
        "django_cache",
        database=schema_editor.connection.alias,
        verbosity=0,
    )


def remover_cache(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        tabelas = schema_editor.connection.introspection.table_names(cursor)
    if "django_cache" in tabelas:
        schema_editor.execute(
            schema_editor.sql_delete_table % {
                "table": schema_editor.quote_name("django_cache"),
            }
        )


class Migration(migrations.Migration):
    dependencies = [
        ("fidelidade", "0003_alter_movimentopontos_tipo_codigovinculo_dispositivo"),
    ]

    operations = [
        migrations.RunPython(criar_cache, remover_cache),
    ]
