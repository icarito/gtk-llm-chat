"""command_result_fields (xmpp-approval-unified-contract, Fase 2): lee los
pares var->value de un <x type="result"> adjunto a un comando ad-hoc
XEP-0050, para que _query_approval_bypass_status no dependa de parsear
prosa en español por regex.

En el momento en que se escribió el fix (2026-07-25) este módulo no era
importable en el entorno de desarrollo (encadenaba a chat_application.py ->
llm, no instalado), así que la verificación se hizo aislada contra nbxmpp
real fuera de pytest. Con python-llm instalado, este es ese mismo test
formalizado en la suite.
"""
from unittest.mock import MagicMock

from nbxmpp.modules.dataforms import SimpleDataForm, create_field

from gtk_llm_chat.xmpp_commands import command_result_fields


def _fake_command(data):
    command = MagicMock()
    command.data = data
    return command


def test_command_result_fields_reads_var_value_pairs():
    form = SimpleDataForm(
        type_="result",
        fields=[
            create_field("hidden", var="active", value="true"),
            create_field("hidden", var="remaining-seconds", value="480"),
        ],
    )
    result = command_result_fields(_fake_command(form))
    assert result == {"active": "true", "remaining-seconds": "480"}


def test_command_result_fields_no_data_returns_empty_dict():
    assert command_result_fields(_fake_command(None)) == {}


def test_command_result_fields_malformed_data_returns_empty_dict_without_raising():
    # extend_form espera un nodo de form real; un objeto arbitrario no debe
    # tirar la excepción hacia el llamador -- ver el except en
    # command_result_fields.
    assert command_result_fields(_fake_command(object())) == {}
