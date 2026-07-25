"""Regresión: XmppOMEMOSessionManager._send_message construía un stanza
`Message(to=bare_jid, typ="chat")` sin haber importado `Message` de
`nbxmpp.protocol`. Nunca funcionó desde que se escribió (introducido en
b348676), y el NameError se disparaba DESPUÉS de que el plaintext ya se
hubiera desencriptado con éxito -- SessionManager.decrypt() llama a este
callback como housekeeping del ratchet (enviar un mensaje vacío de ack)
antes de devolver el plaintext, así que la excepción se propagaba y
descartaba un mensaje ya legible, mostrando
"🔒 Encrypted message could not be decrypted" en su lugar.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nbxmpp.protocol import Message as RealMessage

from gtk_llm_chat import xmpp_omemo


@pytest.mark.asyncio
async def test_send_message_builds_a_real_nbxmpp_message():
    fake_session = MagicMock()
    fake_session._client = MagicMock()

    fake_message = MagicMock()
    fake_message.namespace = xmpp_omemo.LEGACY_NS

    with patch.object(
        xmpp_omemo.XmppOMEMOSessionManager, "get_session_instance", return_value=fake_session
    ), patch.object(
        xmpp_omemo, "old_serialize_message", return_value=MagicMock()
    ), patch.object(
        xmpp_omemo, "etree_to_node", return_value=MagicMock()
    ), patch.object(
        xmpp_omemo, "run_on_main_thread", new=AsyncMock()
    ) as mock_run_main:
        await xmpp_omemo.XmppOMEMOSessionManager._send_message(
            fake_message, "user@example.org"
        )

    # Antes del fix, esta línea nunca se alcanzaba -- Message(...) lanzaba
    # NameError antes de poder construirse.
    assert mock_run_main.await_count == 1
    _send_stanza, stanza = mock_run_main.await_args.args
    assert isinstance(stanza, RealMessage)
    assert stanza.getAttr("to") == "user@example.org"
    assert stanza.getAttr("type") == "chat"


@pytest.mark.asyncio
async def test_send_message_raises_if_no_active_session():
    with patch.object(
        xmpp_omemo.XmppOMEMOSessionManager, "get_session_instance", return_value=None
    ):
        fake_message = MagicMock(namespace=xmpp_omemo.LEGACY_NS)
        with pytest.raises(RuntimeError):
            await xmpp_omemo.XmppOMEMOSessionManager._send_message(
                fake_message, "user@example.org"
            )
