"""
xmpp_client.py - backend XMPP para conversar con agentes/contactos (spec 001).

Dos piezas:
- XmppSession: una conexión XMPP por cuenta (nbxmpp Client sobre el main
  loop de GLib), compartida por todas las conversaciones. Maneja estado,
  roster y enrutamiento de mensajes entrantes.
- XmppConversation: implementa el contrato ChatBackend para un contacto
  (bare JID). Es lo que consume LLMChatWindow.

Hallazgos del spike (specs/001-xmpp-backend/design.md) aplicados aquí:
- Una contraseña errada NO dispara 'connection-failed': hay que revisar
  client.get_error() al recibir 'disconnected'.
- Hay que enviar Presence inicial o el servidor no rutea mensajes.
- request_roster() devuelve un Task; el resultado llega por callback.
"""
from gi.repository import GLib, GObject

from nbxmpp.client import Client as NbxmppClient
from nbxmpp.namespaces import Namespace
from nbxmpp.protocol import JID, Message, Presence
from nbxmpp.simplexml import Node
from nbxmpp.structs import StanzaHandler

from .chat_backend import ChatBackend
from .chat_application import _
from .debug_utils import debug_print

STATE_DISCONNECTED = 'disconnected'
STATE_CONNECTING = 'connecting'
STATE_CONNECTED = 'connected'

RESOURCE = 'gtk-llm-chat'


class XmppSession(GObject.Object):
    """Sesión XMPP de una cuenta, compartida por sus conversaciones.

    Nota: GObject.Object ya define connect()/disconnect() para señales,
    por eso los métodos de red se llaman connect_to_server() y
    disconnect_from_server().
    """

    __gsignals__ = {
        'state-changed': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'session-error': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'roster-updated': (GObject.SignalFlags.RUN_LAST, None, ()),
        # bare_jid, body — para mensajes sin conversación abierta (T6)
        'message-received': (GObject.SignalFlags.RUN_LAST, None, (str, str)),
        # bare_jid, state ('online'/'offline') — presencia de un contacto (spec 002)
        'presence-changed': (GObject.SignalFlags.RUN_LAST, None, (str, str)),
        # bare_jid — alguien pide suscribirse a nuestra presencia (spec 002 T6)
        'subscription-request': (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    PRESENCE_ONLINE = 'online'
    PRESENCE_OFFLINE = 'offline'

    def __init__(self, jid: str, password: str, resource: str = RESOURCE):
        GObject.Object.__init__(self)
        self._jid = JID.from_string(jid)
        self._password = password
        self._resource = resource
        self._client = None
        self._state = STATE_DISCONNECTED
        self._disconnect_requested = False
        # bare jid (str) -> dict(name=..., subscription=..., presence=...)
        self.roster_items = {}
        self._roster_loaded = False
        # bare jid (str) -> set de recursos online; un contacto está
        # 'online' si tiene al menos un recurso disponible (spec 002 spike)
        self._online_resources = {}
        # bare jid (str) -> XmppConversation
        self._conversations = {}

    # --- Estado ---

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state == STATE_CONNECTED

    @property
    def bare_jid(self) -> str:
        return str(self._jid.bare)

    def _set_state(self, state: str):
        if state == self._state:
            return
        debug_print(f"XmppSession[{self.bare_jid}]: estado {self._state} -> {state}")
        self._state = state
        self.emit('state-changed', state)

    # --- Ciclo de vida de la conexión ---

    def connect_to_server(self):
        """Inicia la conexión. No bloqueante; el progreso llega por señales."""
        if self._state != STATE_DISCONNECTED:
            debug_print(f"XmppSession: connect_to_server ignorado en estado {self._state}")
            return
        client = NbxmppClient(log_context=f'xmpp-{self.bare_jid}')
        client.set_username(self._jid.localpart)
        client.set_domain(self._jid.domain)
        client.set_resource(self._resource)
        client.set_password(self._password)
        client.subscribe('connected', self._on_connected)
        client.subscribe('disconnected', self._on_disconnected)
        client.subscribe('connection-failed', self._on_connection_failed)
        client.register_handler(
            StanzaHandler(name='message', callback=self._on_message))
        client.register_handler(
            StanzaHandler(name='presence', callback=self._on_presence))
        self._client = client
        self._disconnect_requested = False
        self._set_state(STATE_CONNECTING)
        client.connect()

    def disconnect_from_server(self):
        if self._client is not None and self._state != STATE_DISCONNECTED:
            self._disconnect_requested = True
            self._client.disconnect()

    def _on_connected(self, _client, _signal_name):
        # Orden RFC 6121: roster primero, luego presence inicial, y solo
        # entonces anunciar 'connected'. Si se envía un mensaje antes del
        # presence, el servidor nos considera offline y lo encola.
        task = self._client.get_module('Roster').request_roster()
        task.add_done_callback(self._on_roster)

    def _on_disconnected(self, _client, _signal_name):
        # Un fallo de autenticación llega por aquí, no por connection-failed
        error, text, _extra = self._client.get_error()
        if self._disconnect_requested:
            # Cierre voluntario: el stream-end resultante no es un error
            error = None
        if error is not None:
            message = f"{error}: {text}" if text else str(error)
            debug_print(f"XmppSession: desconectado con error: {message}")
            self.emit('session-error', message)
        self._set_state(STATE_DISCONNECTED)

    def _on_connection_failed(self, _client, _signal_name):
        error, text, _extra = self._client.get_error()
        message = f"{error}: {text}" if text else str(error or _("Connection failed"))
        debug_print(f"XmppSession: fallo de conexión: {message}")
        self.emit('session-error', message)
        self._set_state(STATE_DISCONNECTED)

    # --- Roster ---

    def _on_roster(self, task):
        try:
            roster = task.finish()
        except Exception as err:
            # Un roster fallido no impide chatear; reportar y seguir
            debug_print(f"XmppSession: error al pedir roster: {err}")
            self.emit('session-error', str(err))
            roster = None
        if roster is not None:
            self.roster_items = {}
            for item in roster.items:
                bare = str(item.jid.bare)
                self.roster_items[bare] = {
                    'name': item.name,
                    'subscription': item.subscription,
                    # Presencia inicial desconocida = offline hasta recibir <presence>
                    'presence': self.PRESENCE_OFFLINE,
                }
            self._roster_loaded = True
            debug_print(f"XmppSession: roster con {len(self.roster_items)} contactos")
        # Presence inicial: sin esto el servidor no rutea mensajes entrantes
        self._client.send_stanza(Presence())
        self._set_state(STATE_CONNECTED)
        if roster is not None:
            self.emit('roster-updated')

    def get_contact_name(self, bare_jid: str) -> str:
        item = self.roster_items.get(bare_jid)
        if item and item.get('name'):
            return item['name']
        return bare_jid

    def get_presence(self, bare_jid: str) -> str:
        item = self.roster_items.get(bare_jid)
        return item.get('presence', self.PRESENCE_OFFLINE) if item else self.PRESENCE_OFFLINE

    # --- Presencia (spec 002) ---

    def _on_presence(self, _client, _stanza, properties):
        # El handler base de nbxmpp 7.2.0 puede haber crasheado antes en
        # presencias sin 'from' (bug conocido, va a stderr sin tumbar el
        # stream). Aquí guardamos igual contra jid None.
        if properties.jid is None or properties.type is None:
            return
        ptype = properties.type
        bare = str(properties.jid.bare)
        # Solicitud de suscripción entrante (spec 002 T6): alguien quiere
        # ver nuestra presencia. La app decide aceptar/rechazar.
        if ptype.value == 'subscribe':
            debug_print(f"XmppSession: solicitud de suscripción de {bare}")
            self.emit('subscription-request', bare)
            return
        # Solo available/unavailable importan para presencia.
        if ptype.value not in (None, 'unavailable'):
            return
        resource = properties.jid.resource
        if bare not in self.roster_items:
            # Presencia de alguien fuera del roster (p.ej. nosotros mismos);
            # no la mostramos en la lista de contactos.
            return
        resources = self._online_resources.setdefault(bare, set())
        was_online = bool(resources)
        if ptype.value == 'unavailable':
            resources.discard(resource)
        else:  # available
            resources.add(resource)
        is_online = bool(resources)
        if is_online != was_online:
            state = self.PRESENCE_ONLINE if is_online else self.PRESENCE_OFFLINE
            self.roster_items[bare]['presence'] = state
            debug_print(f"XmppSession: presencia {bare} -> {state}")
            self.emit('presence-changed', bare, state)

    # --- Mensajes ---

    def _on_message(self, _client, _stanza, properties):
        if properties.jid is None:
            return
        if getattr(properties, 'is_carbon_message', False) \
                and properties.carbon.is_sent:
            return
        bare = str(properties.jid.bare)
        conversation = self._conversations.get(bare)
        if properties.has_chatstate and conversation is not None:
            conversation.notify_chatstate(str(properties.chatstate))
        if not properties.body:
            return
        debug_print(f"XmppSession: mensaje de {bare}: {properties.body[:60]!r}")
        if conversation is not None:
            conversation.deliver(properties.body)
        # Emitir siempre para que la app pueda notificar si la ventana de
        # esa conversación no tiene foco (o no existe) — spec 002 T5.
        self.emit('message-received', bare, properties.body)

    def send_text(self, to_bare_jid: str, text: str):
        # XEP-0085: marcar 'active' junto con cada mensaje
        chatstate = Node('active', attrs={'xmlns': Namespace.CHATSTATES})
        self._client.send_stanza(
            Message(to=to_bare_jid, body=text, typ='chat', payload=[chatstate]))

    def send_chatstate(self, to_bare_jid: str, chatstate: str):
        """Envía solo un chat state (XEP-0085), sin cuerpo de mensaje."""
        if not self.is_connected:
            return
        payload = Node(chatstate, attrs={'xmlns': Namespace.CHATSTATES})
        self._client.send_stanza(Message(to=to_bare_jid, typ='chat', payload=[payload]))

    # --- Suscripciones (spec 002 T6) ---

    def accept_subscription(self, bare_jid: str):
        """Acepta una solicitud de suscripción y pide reciprocidad, para
        que ambos vean la presencia del otro."""
        if not self.is_connected:
            return
        jid = JID.from_string(bare_jid)
        presence = self._client.get_module('BasePresence')
        presence.subscribed(jid)   # el otro podrá ver nuestra presencia
        presence.subscribe(jid)    # y pedimos ver la suya

    def deny_subscription(self, bare_jid: str):
        """Rechaza una solicitud de suscripción."""
        if not self.is_connected:
            return
        self._client.get_module('BasePresence').unsubscribed(JID.from_string(bare_jid))

    # --- Conversaciones ---

    def get_conversation(self, bare_jid: str) -> 'XmppConversation':
        """Devuelve (creando si hace falta) el backend para un contacto."""
        conversation = self._conversations.get(bare_jid)
        if conversation is None:
            conversation = XmppConversation(self, bare_jid)
            self._conversations[bare_jid] = conversation
        return conversation

    def forget_conversation(self, bare_jid: str):
        """Elimina una conversación del registro (al cerrar su ventana)."""
        self._conversations.pop(bare_jid, None)

    def shutdown(self):
        self._conversations.clear()
        self.disconnect_from_server()


class XmppConversation(ChatBackend):
    """ChatBackend para un contacto XMPP. Una instancia por bare JID."""

    def __init__(self, session: XmppSession, bare_jid: str):
        ChatBackend.__init__(self)
        self.session = session
        self.bare_jid = bare_jid
        # Guardar los handler ids para poder desconectarlos en shutdown:
        # la sesión es compartida y vive más que esta conversación.
        self._session_handlers = [
            session.connect('state-changed', self._on_session_state),
            session.connect('session-error', self._on_session_error),
        ]
        if session.is_connected:
            GLib.idle_add(self._emit_ready)

    def _emit_ready(self):
        self.emit('ready', self.get_display_name())
        return GLib.SOURCE_REMOVE

    def _on_session_state(self, _session, state):
        self.emit('state-changed', state)
        if state == STATE_CONNECTED:
            self.emit('ready', self.get_display_name())

    def _on_session_error(self, _session, message):
        self.emit('error', message)

    # --- Entrantes (llamados por la sesión) ---

    def deliver(self, body: str):
        """Un mensaje del contacto: response + finished (sin streaming)."""
        self.emit('response', body)
        self.emit('finished', True)

    def notify_chatstate(self, chatstate: str):
        self.emit('typing', chatstate.endswith('COMPOSING'))

    # --- Contrato ChatBackend ---

    def send_message(self, prompt: str):
        if not self.session.is_connected:
            self.emit('error', _("Not connected to the XMPP server"))
            self.emit('finished', False)
            return
        self.session.send_text(self.bare_jid, prompt)
        # El envío no genera respuesta propia: liberar la UI de inmediato
        self.emit('finished', True)

    def cancel(self):
        pass

    def get_conversation_id(self):
        # Sin historial local en el MVP (spec 001): no hay CID persistente
        return None

    def get_display_name(self) -> str:
        return self.session.get_contact_name(self.bare_jid)

    def notify_composing(self, is_composing: bool):
        state = 'composing' if is_composing else 'active'
        self.session.send_chatstate(self.bare_jid, state)

    def shutdown(self):
        # La sesión es compartida (la cierra quien la posee), pero sí hay
        # que soltar nuestros handlers y salir de su registro para no
        # seguir recibiendo señales tras cerrar la ventana.
        for handler_id in self._session_handlers:
            self.session.disconnect(handler_id)
        self._session_handlers = []
        self.session.forget_conversation(self.bare_jid)
