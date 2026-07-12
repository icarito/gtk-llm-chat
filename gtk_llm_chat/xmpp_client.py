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

import os
import uuid

from nbxmpp.client import Client as NbxmppClient
from nbxmpp.namespaces import Namespace
from nbxmpp.protocol import Iq, JID, Message, Presence
from nbxmpp.simplexml import Node
from nbxmpp.structs import StanzaHandler

from .chat_backend import ChatBackend
from .chat_application import _
from .debug_utils import debug_print
from .xmpp_history import XmppHistory

STATE_DISCONNECTED = 'disconnected'
STATE_CONNECTING = 'connecting'
STATE_RECONNECTING = 'reconnecting'
STATE_CONNECTED = 'connected'

RESOURCE = 'gtk-llm-chat'
NANOCLAW_CAPS_NODE = 'https://github.com/nanocoai/nanoclaw'
QUICK_RESPONSE_NS = 'urn:xmpp:tmp:quick-response'


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
        # bare_jid — cambió el status/caps de un contacto agente (spec 005)
        'contact-status-changed': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        # bare_jid — alguien pide suscribirse a nuestra presencia (spec 002 T6)
        'subscription-request': (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    PRESENCE_ONLINE = 'online'
    PRESENCE_OFFLINE = 'offline'

    def __init__(self, jid: str, password: str, resource: str = RESOURCE,
                 auto_reconnect: bool = True):
        GObject.Object.__init__(self)
        self._jid = JID.from_string(jid)
        self._password = password
        self._resource = resource
        self._auto_reconnect = auto_reconnect
        self._client = None
        self._state = STATE_DISCONNECTED
        self._disconnect_requested = False
        self._reconnect_requested = False
        self._reconnect_timeout_id = None
        self._reconnect_attempt = 0
        # bare jid (str) -> dict(name=..., subscription=..., presence=...)
        self.roster_items = {}
        self._roster_loaded = False
        self._online_resources = {}
        self._conversations = {}
        self._pending_mam_queries: dict = {}
        self.history: XmppHistory | None = None

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

    def connect_to_server(self, reset_backoff: bool = True):
        """Inicia la conexión. No bloqueante; el progreso llega por señales."""
        if self._state not in (STATE_DISCONNECTED, STATE_RECONNECTING):
            debug_print(f"XmppSession: connect_to_server ignorado en estado {self._state}")
            return
        self._cancel_reconnect_timer()
        if reset_backoff:
            self._reconnect_attempt = 0
        self._disconnect_requested = False
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
        self._set_state(STATE_CONNECTING)
        client.connect()

    def disconnect_from_server(self):
        self._disconnect_requested = True
        self._cancel_reconnect_timer()
        if self._client is not None and self._state != STATE_DISCONNECTED:
            self._client.disconnect()
        else:
            self._set_state(STATE_DISCONNECTED)

    def reconnect_now(self):
        """Cancela el backoff pendiente y reconecta de inmediato."""
        self._cancel_reconnect_timer()
        self._reconnect_attempt = 0
        if self._client is not None and self._state != STATE_DISCONNECTED:
            self._reconnect_requested = True
            self._client.disconnect(immediate=True)
            return
        self.connect_to_server()

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
        if self._reconnect_requested:
            self._reconnect_requested = False
            GLib.idle_add(lambda: (self.connect_to_server(), GLib.SOURCE_REMOVE)[1])
            return
        if self._should_reconnect(error, text):
            self._schedule_reconnect()

    def _on_connection_failed(self, _client, _signal_name):
        error, text, _extra = self._client.get_error()
        message = f"{error}: {text}" if text else str(error or _("Connection failed"))
        debug_print(f"XmppSession: fallo de conexión: {message}")
        self.emit('session-error', message)
        self._set_state(STATE_DISCONNECTED)
        if self._should_reconnect(error, text):
            self._schedule_reconnect()

    def _should_reconnect(self, error, text) -> bool:
        if self._disconnect_requested or self._reconnect_requested or not self._auto_reconnect:
            return False
        message = f"{error or ''} {text or ''}".lower()
        auth_markers = ('not-authorized', 'not authorized', 'sasl', 'authentication')
        return not any(marker in message for marker in auth_markers)

    def _schedule_reconnect(self):
        if self._reconnect_timeout_id is not None:
            return
        self._reconnect_attempt += 1
        delay = min(60, 2 ** min(self._reconnect_attempt, 5))
        debug_print(f"XmppSession: reconectando en {delay}s")
        self._set_state(STATE_RECONNECTING)

        def do_reconnect():
            self._reconnect_timeout_id = None
            if self._disconnect_requested:
                return GLib.SOURCE_REMOVE
            self.connect_to_server(reset_backoff=False)
            return GLib.SOURCE_REMOVE

        self._reconnect_timeout_id = GLib.timeout_add_seconds(delay, do_reconnect)

    def _cancel_reconnect_timer(self):
        if self._reconnect_timeout_id is not None:
            GLib.source_remove(self._reconnect_timeout_id)
            self._reconnect_timeout_id = None

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
            # Reiniciar el estado de presencia: tras una (re)carga de roster
            # las presencias se reciben de nuevo. Sin esto, un reconnect del
            # mismo objeto sesión dejaría recursos "online" fantasma que
            # impiden detectar el flip offline→online (fix review #2).
            self._online_resources = {}
            self.roster_items = {}
            for item in roster.items:
                bare = str(item.jid.bare)
                self.roster_items[bare] = {
                    'name': item.name,
                    'subscription': item.subscription,
                    # Presencia inicial desconocida = offline hasta recibir <presence>
                    'presence': self.PRESENCE_OFFLINE,
                    'status': '',
                    'is_agent': False,
                    'agent_full_jid': None,
                }
            self._roster_loaded = True
            debug_print(f"XmppSession: roster con {len(self.roster_items)} contactos")
        # Presence inicial: sin esto el servidor no rutea mensajes entrantes
        self._client.send_stanza(Presence())
        # XEP-0280 Message Carbons: sin activarlo, si esta cuenta también
        # está conectada desde otro cliente (p.ej. Gajim) en otro recurso,
        # el servidor puede entregar un mensaje solo a ese otro recurso y
        # esta ventana nunca se entera — aunque el filtro is_carbon_message
        # ya existente en _on_message asume que sí llegan copias.
        # <enable/> va como hijo directo del <iq>, no envuelto en <query>
        # (por eso no se usa el parámetro payload= de Iq, que sí envuelve).
        enable_carbons = Iq(typ='set')
        enable_carbons.addChild('enable', namespace=Namespace.CARBONS)
        self._client.send_stanza(enable_carbons)
        self._reconnect_attempt = 0
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

    def get_contact_status(self, bare_jid: str) -> str:
        item = self.roster_items.get(bare_jid)
        return item.get('status', '') if item else ''

    def is_agent_contact(self, bare_jid: str) -> bool:
        item = self.roster_items.get(bare_jid)
        return bool(item and item.get('is_agent'))

    def get_agent_full_jid(self, bare_jid: str) -> str | None:
        item = self.roster_items.get(bare_jid)
        return item.get('agent_full_jid') if item else None

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
        old_status = self.roster_items[bare].get('status', '')
        old_is_agent = self.roster_items[bare].get('is_agent', False)
        old_agent_full_jid = self.roster_items[bare].get('agent_full_jid')
        status = getattr(properties, 'status', None) or ''
        entity_caps = getattr(properties, 'entity_caps', None)
        caps_node = getattr(entity_caps, 'node', None)
        if caps_node == NANOCLAW_CAPS_NODE:
            self.roster_items[bare]['is_agent'] = True
            self.roster_items[bare]['agent_full_jid'] = str(properties.jid)
        if status != old_status:
            self.roster_items[bare]['status'] = status
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
        if (status != old_status or
                self.roster_items[bare].get('is_agent') != old_is_agent or
                self.roster_items[bare].get('agent_full_jid') != old_agent_full_jid):
            self.emit('contact-status-changed', bare)

    def _ensure_history(self):
        if self.history is None:
            from .platform_utils import ensure_user_dir_exists
            user_dir = ensure_user_dir_exists()
            self.history = XmppHistory(os.path.join(user_dir, "xmpp_history.db"))

    # --- Mensajes ---

    def query_mam(self, bare_jid: str, after: str = None, end: str = None,
                  callback: 'callable' = None):
        """Issue a MAM query for conversation history (XEP-0313).

        Returns the queryid for correlation, or None if not connected.
        Results arrive as ordinary 'message' stanzas routed through
        _on_message's MAM branch, collected in _pending_mam_queries;
        the done-callback fires on query completion with the buffered
        messages and complete flag.

        This nbxmpp version's make_query has no before= parameter,
        only start/end/after (max_ for page size). Scroll-to-load-older
        uses end= (the timestamp of the oldest message currently shown)
        without after= to get the page immediately preceding it.
        """
        if not self.is_connected:
            return None
        self._ensure_history()
        queryid = str(uuid.uuid4())
        self._pending_mam_queries[queryid] = {
            'buffer': [],
            'callback': callback,
            'bare_jid': bare_jid,
        }
        try:
            kwargs = {'jid': self._jid, 'queryid': queryid, 'with_': bare_jid, 'max_': 50}
            if after is not None:
                kwargs['after'] = after
            if end is not None:
                kwargs['end'] = end
            task = self._client.get_module('MAM').make_query(**kwargs)
            task.add_done_callback(lambda t: self._on_mam_query_done(t, queryid))
        except Exception as err:
            debug_print(f"XmppSession: MAM query failed: {err}")
            entry = self._pending_mam_queries.pop(queryid, None)
            if entry and entry['callback']:
                entry['callback']([], False)
            return None
        return queryid

    def _on_mam_query_done(self, task, queryid):
        entry = self._pending_mam_queries.pop(queryid, None)
        if entry is None:
            return
        try:
            result = task.finish()
            complete = result.complete
            debug_print(f"XmppSession: MAM query done for {entry['bare_jid']} "
                        f"complete={complete} first={result.rsm.first} "
                        f"last={result.rsm.last}")
        except Exception as err:
            debug_print(f"XmppSession: MAM query errored: {err}")
            complete = False
        if entry['callback']:
            entry['callback'](entry['buffer'], complete)

    # --- Mensajes ---

    def _on_message(self, _client, _stanza, properties):
        if properties.jid is None:
            return
        if getattr(properties, 'is_carbon_message', False) \
                and properties.carbon.is_sent:
            return
        bare = str(properties.jid.bare)
        conversation = self._conversations.get(bare)

        if getattr(properties, 'is_mam_message', False):
            mam = properties.mam
            pending = self._pending_mam_queries.get(mam.query_id)
            if pending is not None and properties.body:
                direction = 'out' if properties.jid.bare == self._jid.bare else 'in'
                pending['buffer'].append(
                    (properties.body, direction, mam.timestamp, mam.id))
            return

        if properties.has_chatstate and conversation is not None:
            conversation.notify_chatstate(str(properties.chatstate))
        if not properties.body:
            return
        debug_print(f"XmppSession: mensaje de {bare}: {properties.body[:60]!r}")
        quick_responses = self._parse_quick_responses(_stanza)
        if conversation is not None:
            conversation.deliver(properties.body, quick_responses)
        # Emitir siempre para que la app pueda notificar si la ventana de
        # esa conversación no tiene foco (o no existe) — spec 002 T5.
        self.emit('message-received', bare, properties.body)

    def _parse_quick_responses(self, stanza) -> list[dict[str, str]]:
        responses = []
        for child in stanza.getTags('response', namespace=QUICK_RESPONSE_NS):
            value = child.getAttr('value')
            label = child.getAttr('label') or value
            if value and label:
                responses.append({'value': value, 'label': label})
        return responses

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

    def add_contact(self, bare_jid: str):
        """Añade un contacto nuevo: pide ver su presencia. El contacto
        aparecerá en el roster (vía roster-push del servidor) aunque él
        aún no haya aceptado; su presencia quedará offline hasta que lo
        haga."""
        if not self.is_connected:
            return
        self._client.get_module('BasePresence').subscribe(JID.from_string(bare_jid))

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
        self._cancel_reconnect_timer()
        self._conversations.clear()
        self.disconnect_from_server()


class XmppConversation(ChatBackend):
    """ChatBackend para un contacto XMPP. Una instancia por bare JID."""

    def __init__(self, session: XmppSession, bare_jid: str):
        ChatBackend.__init__(self)
        self.session = session
        self.bare_jid = bare_jid
        session._ensure_history()
        # Guardar los handler ids para poder desconectarlos en shutdown:
        # la sesión es compartida y vive más que esta conversación.
        self._session_handlers = [
            session.connect('state-changed', self._on_session_state),
            session.connect('session-error', self._on_session_error),
        ]
        self._history_shown_from: str | None = None
        self._pending_mam_queryid: str | None = None
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

    def deliver(self, body: str, quick_responses=None):
        """Un mensaje del contacto: response + finished, cached."""
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        history = self.session.history
        if history is not None:
            history.record_message(self.bare_jid, body, 'in', ts)
        self.emit('response', body)
        if quick_responses:
            self.emit('quick-responses', quick_responses)
        self.emit('finished', True)

    def notify_chatstate(self, chatstate: str):
        self.emit('typing', chatstate.endswith('COMPOSING'))

    # --- Contrato ChatBackend ---

    def send_message(self, prompt: str):
        if not self.session.is_connected:
            self.emit('error', _("Not connected to the XMPP server"))
            self.emit('finished', False)
            return
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        history = self.session.history
        if history is not None:
            history.record_message(self.bare_jid, prompt, 'out', ts)
        self.session.send_text(self.bare_jid, prompt)
        self.emit('finished', True)

    def send_quick_response(self, value: str, label: str):
        if not self.session.is_connected:
            self.emit('error', _("Not connected to the XMPP server"))
            self.emit('finished', False)
            return
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        history = self.session.history
        if history is not None:
            history.record_message(self.bare_jid, value, 'out', ts)
        self.session.send_text(self.bare_jid, value)
        self.emit('finished', True)

    def cancel(self):
        pass

    def get_conversation_id(self):
        return f"xmpp:{self.session.bare_jid}:{self.bare_jid}"

    def get_display_name(self) -> str:
        return self.session.get_contact_name(self.bare_jid)

    def notify_composing(self, is_composing: bool):
        state = 'composing' if is_composing else 'active'
        self.session.send_chatstate(self.bare_jid, state)

    # --- History (spec 004) ---

    def load_history_from_cache(self):
        history = self.session.history
        if history is None:
            self.emit('history-complete', False)
            return
        messages = history.get_recent(self.bare_jid)
        if not messages:
            self.emit('history-complete', False)
            return
        for msg in messages:
            self.emit('history-message', msg['body'], msg['direction'], msg['timestamp'])
        self._history_shown_from = messages[0]['timestamp']
        self.emit('history-complete', True)

    def load_history_from_mam(self):
        if not self.session.is_connected or self._pending_mam_queryid is not None:
            return
        history = self.session.history
        after_ts = history.get_latest_timestamp(self.bare_jid) if history else None
        self._pending_mam_queryid = self.session.query_mam(
            self.bare_jid, after=after_ts, callback=self._on_mam_page)

    def load_more_history(self):
        history = self.session.history
        if history is None:
            return
        older = history.get_before(self.bare_jid, self._history_shown_from, limit=50)
        if older:
            for msg in older:
                self.emit('history-message', msg['body'], msg['direction'], msg['timestamp'])
            self._history_shown_from = older[0]['timestamp']
            self.emit('history-complete', True)
            return
        if self.session.is_connected:
            self._pending_mam_queryid = self.session.query_mam(
                self.bare_jid, end=self._history_shown_from, callback=self._on_mam_page)

    def _on_mam_page(self, messages, complete):
        self._pending_mam_queryid = None
        for body, direction, timestamp, mam_id in messages:
            history = self.session.history
            if history is not None:
                history.record_message(self.bare_jid, body, direction, timestamp, mam_id)
            self.emit('history-message', body, direction, timestamp)
        if messages:
            self._history_shown_from = messages[0][2]
        self.emit('history-complete', not complete)

    def shutdown(self):
        # La sesión es compartida (la cierra quien la posee), pero sí hay
        # que soltar nuestros handlers y salir de su registro para no
        # seguir recibiendo señales tras cerrar la ventana.
        for handler_id in self._session_handlers:
            self.session.disconnect(handler_id)
        self._session_handlers = []
        self.session.forget_conversation(self.bare_jid)
