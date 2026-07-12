"""
chat_backend.py - contrato común para los backends de conversación.

Un ChatBackend alimenta una LLMChatWindow: recibe texto del usuario y
emite señales GObject con la respuesta. LLMClient (modelos vía python-llm)
es la implementación original; XmppClient (spec 001) implementa el mismo
contrato para contactos XMPP.

Reglas del contrato (ver specs/001-xmpp-backend/design.md):
- Nunca bloquear el main loop: el trabajo largo va en hilos o fuentes
  async de GLib y vuelve con GLib.idle_add antes de emitir señales.
- 'response' puede emitirse muchas veces (streaming) o una sola vez
  (mensaje completo); siempre va seguida de 'finished'.
- 'ready' indica que el backend puede enviar mensajes (modelo cargado /
  sesión conectada); su argumento es el nombre a mostrar.
- 'state-changed' comunica estados de conexión propios del backend
  (p.ej. XMPP: connected/disconnected). Los backends locales pueden
  no emitirla nunca.
- 'typing' indica que la otra parte está escribiendo (p.ej. XEP-0085).
  Backends que no lo soportan (LLMClient) simplemente no la emiten.
- 'quick-responses' adjunta acciones de respuesta rápida al último
  mensaje recibido. Backends que no lo soportan simplemente no la emiten.
"""
from gi.repository import GObject


class ChatBackend(GObject.Object):
    """Base para backends de conversación. Duck-typed: la ventana solo
    depende de estas señales y métodos."""

    __gsignals__ = {
        'response': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'error': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'finished': (GObject.SignalFlags.RUN_LAST, None, (bool,)),
        'ready': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'state-changed': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'typing': (GObject.SignalFlags.RUN_LAST, None, (bool,)),
        'quick-responses': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'history-message': (GObject.SignalFlags.RUN_LAST, None,
                            (str, str, str)),
        'history-complete': (GObject.SignalFlags.RUN_LAST, None, (bool,)),
    }

    def send_message(self, prompt: str):
        """Envía el texto del usuario. No bloqueante."""
        raise NotImplementedError

    def cancel(self):
        """Cancela la generación/el envío en curso, si lo hay."""
        raise NotImplementedError

    def notify_composing(self, is_composing: bool):
        """Informa al backend que el usuario está escribiendo (o dejó de
        hacerlo), para que lo retransmita si el protocolo lo soporta
        (p.ej. XEP-0085). No-op por defecto."""
        pass

    def get_conversation_id(self):
        """Identificador persistente de la conversación, o None."""
        raise NotImplementedError

    def get_display_name(self) -> str:
        """Nombre para el subtítulo de la ventana (modelo o contacto)."""
        raise NotImplementedError

    def shutdown(self):
        """Libera recursos (desconexión, hilos). Por defecto: cancel()."""
        self.cancel()

    def load_more_history(self):
        """Request one more page of older history, if the backend has any
        concept of history. No-op by default."""
        pass
