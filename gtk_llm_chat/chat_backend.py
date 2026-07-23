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
- 'response-correction' reemplaza el contenido de la última burbuja
  recibida en lugar de crear una nueva (XEP-0308 Last Message Correction).
  Backends que no corrigen simplemente no la emiten.
- 'ready' indica que el backend puede enviar mensajes (modelo cargado /
  sesión conectada); su argumento es el nombre a mostrar.
- 'state-changed' comunica estados de conexión propios del backend
  (p.ej. XMPP: connected/disconnected). Los backends locales pueden
  no emitirla nunca.
- 'typing' indica que la otra parte está escribiendo (p.ej. XEP-0085).
  Backends que no lo soportan (LLMClient) simplemente no la emiten.
- 'quick-responses' adjunta acciones de respuesta rápida al último
  mensaje recibido, junto con el request_id (stanza id) de ese mensaje
  para poder correlacionar una futura 'response-correction'. Backends que
  no lo soportan simplemente no la emiten.
"""
from gi.repository import GObject


class ChatBackend(GObject.Object):
    """Base para backends de conversación. Duck-typed: la ventana solo
    depende de estas señales y métodos."""

    __gsignals__ = {
        'response': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'response-message': (GObject.SignalFlags.RUN_LAST, None, (str, str, str)),
        # (request_id, body, timestamp) — request_id identifica la pregunta
        # original que esta corrección resuelve (XEP-0308 <replace
        # id=request_id>), None si el backend no pudo correlacionarla
        # (degradación: se trata como mensaje nuevo, ver
        # XmppConversation.deliver()). timestamp es ISO-8601 UTC del momento
        # de recepción, o "" si el backend no lo provee (p.ej. LLMClient
        # local): sin esto, la burbuja en vivo quedaba marcada con la hora de
        # RENDERIZADO en pantalla en vez de la hora real del mensaje, y la
        # deduplicación contra el catch-up de MAM (_has_recent_matching_bubble,
        # ventana de 60s) fallaba si pasaba más de un minuto entre ambas —
        # el mismo mensaje terminaba pintado dos veces.
        'response-correction': (GObject.SignalFlags.RUN_LAST, None, (str, str)),
        # request_id de una pregunta resuelta por un carbon (XEP-0280) de la
        # propia respuesta enviada desde otro recurso — señal secundaria,
        # más rápida que 'response-correction' pero sin texto de corrección
        # (no cambia el body de la pregunta original, sólo la atenúa).
        'own-carbon-resolved': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        # Un mensaje MÍO que hay que pintar y que la ventana no dibujó al
        # enviarlo: un adjunto (la burbuja no puede existir hasta que la subida
        # devuelve la URL) o un carbon XEP-0280 de otro dispositivo, p.ej. una
        # imagen enviada desde el móvil.
        'own-message': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'error': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'finished': (GObject.SignalFlags.RUN_LAST, None, (bool,)),
        'ready': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'state-changed': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'typing': (GObject.SignalFlags.RUN_LAST, None, (bool,)),
        # (stanza_id, state, body) para mensajes propios XMPP. state es
        # pending|sent|failed; body permite correlacionar la burbuja creada
        # por la UI antes de que el backend asigne el stanza id.
        'delivery-state': (GObject.SignalFlags.RUN_LAST, None, (str, str, str)),
        # (stanza_id, namespace): transporte confirmó que el mensaje usó OMEMO.
        'encryption-state': (GObject.SignalFlags.RUN_LAST, None, (str, str)),
        # (options, request_id) — request_id es el stanza id propio del
        # mensaje que trajo estas opciones; None si no se pudo capturar.
        'quick-responses': (GObject.SignalFlags.RUN_LAST, None, (object, object)),
        'commands': (GObject.SignalFlags.RUN_LAST, None, (object, object)),
        'history-message': (GObject.SignalFlags.RUN_LAST, None,
                            (str, str, str, bool, str)),
        'history-actions': (GObject.SignalFlags.RUN_LAST, None,
                            (str, str, object, object, object)),
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
