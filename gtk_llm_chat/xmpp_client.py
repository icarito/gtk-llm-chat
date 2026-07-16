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
import re
import uuid

from nbxmpp.client import Client as NbxmppClient
from nbxmpp.namespaces import Namespace
from nbxmpp.protocol import Iq, JID, Message, Presence
from nbxmpp.simplexml import Node
from nbxmpp.structs import DiscoIdentity, StanzaHandler

from .chat_backend import ChatBackend
from .chat_application import _
from .debug_utils import debug_print
from .xmpp_history import XmppHistory

STATE_DISCONNECTED = 'disconnected'
STATE_CONNECTING = 'connecting'
STATE_RECONNECTING = 'reconnecting'
STATE_CONNECTED = 'connected'

RESOURCE = 'gtk-llm-chat-desktop'
AGENT_CAPS_NODE = 'https://github.com/openclaw/openclaw'
QUICK_RESPONSE_NS = 'urn:xmpp:quick-response:0'

# Telemetría del agente (contexto, tokens, coste, modelo). Va por PEP y no en el
# <status> de la presencia: el status es texto para humanos —cualquier cliente lo
# pinta tal cual junto al contacto— y estos números cambian a cada token.
TELEMETRY_NODE = 'urn:openclaw:telemetry:0'
LEGACY_TELEMETRY_NODE = 'urn:nanoclaw:telemetry:0'


def parse_telemetry(item):
    """Extrae la telemetría del <telemetry/> publicado en el nodo PEP.

    Devuelve un dict con las claves presentes (nunca inventa ceros: 'sin dato' y
    'cero' son cosas distintas para una barra de progreso), o None si el ítem no
    trae nada aprovechable.
    """
    payload = item.getTag('telemetry', namespace=TELEMETRY_NODE)
    if payload is None:
        payload = item.getTag('telemetry', namespace=LEGACY_TELEMETRY_NODE)
    if payload is None:
        return None

    def _int(node, attr):
        try:
            return int(node.getAttr(attr))
        except (TypeError, ValueError):
            return None

    out = {}
    activity = payload.getAttr('activity')
    availability = payload.getAttr('availability')
    if activity:
        out['activity'] = activity
    if availability:
        out['availability'] = availability
    context = payload.getTag('context')
    if context is not None:
        used, total = _int(context, 'used'), _int(context, 'max')
        if used is not None and total:
            out['context_used'] = used
            out['context_max'] = total

    tokens = payload.getTag('tokens')
    if tokens is not None:
        for key in ('total', 'input', 'output', 'requests'):
            value = _int(tokens, key)
            if value is not None:
                out[f'tokens_{key}'] = value

    cost = payload.getTag('cost')
    if cost is not None:
        try:
            out['cost'] = float(cost.getAttr('usd'))
        except (TypeError, ValueError):
            pass

    for tag, key in (('session-cost', 'session_cost'), ('day-cost', 'day_cost')):
        node = payload.getTag(tag)
        if node is not None:
            try:
                out[key] = float(node.getAttr('usd'))
            except (TypeError, ValueError):
                pass

    session = payload.getTag('session')
    if session is not None and session.getAttr('status'):
        out['session_status'] = session.getAttr('status')

    for tag in ('model', 'tool'):
        node = payload.getTag(tag)
        if node is not None and node.getData():
            out[tag] = node.getData()

    return out or None
LEGACY_QUICK_RESPONSE_NS = 'urn:xmpp:tmp:quick-response'
MESSAGE_CORRECT_NS = 'urn:xmpp:message-correct:0'
DISCO_ITEMS_NS = 'http://jabber.org/protocol/disco#items'
COMMANDS_NS = 'http://jabber.org/protocol/commands'


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
        # bare_jid — llegó telemetría nueva del agente por PEP
        'agent-telemetry-changed': (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    PRESENCE_ONLINE = 'online'
    PRESENCE_BUSY = 'busy'
    PRESENCE_AWAY = 'away'
    PRESENCE_OFFLINE = 'offline'

    def __init__(self, jid: str, password: str, resource: str = RESOURCE,
                 auto_reconnect: bool = True):
        GObject.Object.__init__(self)
        self._jid = JID.from_string(jid)
        self._password = password
        self._resource = f"{resource}-{uuid.uuid4().hex[:8]}"
        self._auto_reconnect = auto_reconnect
        self._client = None
        self._state = STATE_DISCONNECTED
        self._disconnect_requested = False
        self._reconnect_requested = False
        self._reconnect_timeout_id = None
        self._reconnect_attempt = 0
        # bare jid (str) -> dict(name=..., subscription=..., presence=...)
        self.roster_items = {}
        # bare jid (str) -> dict con lo último publicado en su nodo PEP de
        # telemetría. Sobrevive a una recarga de roster: sigue siendo válido.
        self.agent_telemetry = {}
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

        # Telemetría del agente: llega por PEP (XEP-0163), no en el <status>.
        # El servidor sólo nos la entrega si nuestras caps piden el nodo con
        # "+notify" — de ahí que se declare aquí y no baste con responder al
        # disco. Un contacto que no publique el nodo simplemente no emite nada.
        client.get_module('EntityCaps').set_caps(
            [DiscoIdentity(category='client', type='pc', name='gtk-llm-chat')],
            [
                Namespace.DISCO_INFO,
                f'{TELEMETRY_NODE}+notify',
                f'{LEGACY_TELEMETRY_NODE}+notify',
            ],
            'https://github.com/icarito/gtk-llm-chat')
        client.register_handler(
            StanzaHandler(name='message', callback=self._on_pep_event,
                          ns=Namespace.PUBSUB_EVENT, priority=15))

        self._client = client
        self._set_state(STATE_CONNECTING)
        client.connect()

    def _on_pep_event(self, _client, stanza, properties):
        """Un evento PEP del agente: telemetría (contexto, tokens, modelo).

        nbxmpp sólo rellena `data` para los namespaces que conoce (avatar, tune,
        …); el nuestro es propio, así que el payload viene crudo en `item` y lo
        parseamos nosotros."""
        if not properties.is_pubsub_event:
            return
        event = properties.pubsub_event
        if event.node not in (TELEMETRY_NODE, LEGACY_TELEMETRY_NODE) or event.item is None:
            return
        telemetry = parse_telemetry(event.item)
        if telemetry is None:
            return
        bare_jid = str(stanza.getFrom().bare)
        self.agent_telemetry[bare_jid] = telemetry
        self.emit('agent-telemetry-changed', bare_jid)

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

    def get_agent_telemetry(self, bare_jid: str) -> dict:
        """Lo último que el agente publicó por PEP, o {} si nunca publicó."""
        return self.agent_telemetry.get(bare_jid, {})

    def fetch_agent_telemetry(self, bare_jid: str):
        """Pide el valor actual del nodo de telemetría del agente.

        Los eventos PEP sólo llegan cuando el agente *publica* algo nuevo, así
        que un agente que lleva rato quieto no emitiría nada y la barra de
        contexto se quedaría vacía para siempre. Al abrir la conversación
        preguntamos por el último valor publicado."""
        if not self.is_connected:
            return
        nodes = [TELEMETRY_NODE, LEGACY_TELEMETRY_NODE]

        def _request(index=0):
            if index >= len(nodes):
                return
            task = self._client.get_module('PubSub').request_items(
                nodes[index], max_items=1, jid=JID.from_string(bare_jid))
            task.add_done_callback(lambda t, i=index: _done(t, i), weak=False)

        def _done(t, index):
            try:
                items = t.finish()
            except Exception as err:
                # Lo normal si el contacto no es un agente NanoClaw: no tiene
                # el nodo. No es un error que merezca molestar al usuario.
                debug_print(f"XmppSession: sin telemetría de {bare_jid}: {err}")
                _request(index + 1)
                return
            for item in items or []:
                telemetry = parse_telemetry(item)
                if telemetry:
                    self.agent_telemetry[bare_jid] = telemetry
                    self.emit('agent-telemetry-changed', bare_jid)
                    return
            _request(index + 1)

        # weak=False es obligatorio: add_done_callback guarda por defecto una
        # referencia DÉBIL, así que una función local como ésta muere en cuanto
        # fetch_agent_telemetry retorna y el callback no se llama nunca — el IQ
        # va, el servidor responde, y no pasa nada.
        _request()

    def get_contact_name(self, bare_jid: str) -> str:
        item = self.roster_items.get(bare_jid)
        if item and item.get('name'):
            return item['name']
        return self.friendly_jid_name(bare_jid)

    def set_contact_name(self, bare_jid: str, name: str, on_done=None):
        """Renombra un contacto en el roster (XEP: IQ roster set).

        El nombre se guarda en el servidor, así que lo ven todos los clientes de
        la cuenta, no sólo este. Un nombre vacío borra el name y el contacto
        vuelve a mostrarse por su JID (o por el fallback de friendly_jid_name).
        """
        if not self.is_connected:
            return
        clean = (name or "").strip() or None
        task = self._client.get_module('Roster').set_item(
            JID.from_string(bare_jid), clean)

        def _done(t):
            try:
                t.finish()
            except Exception as err:
                debug_print(f"XmppSession: renombrar contacto falló: {err}")
                if on_done:
                    on_done(False, str(err))
                return
            # El servidor confirma con un roster push, pero no esperamos a él
            # para que la UI refleje el cambio al instante.
            item = self.roster_items.setdefault(bare_jid, {})
            item['name'] = clean or ''
            self.emit('roster-updated')
            if on_done:
                on_done(True, None)

        task.add_done_callback(_done)

    @staticmethod
    def friendly_jid_name(bare_jid: str) -> str:
        """Nombre presentable para un contacto sin `name` en el roster.

        El JID entero es ruido en un título ("clawdio@hablar.fuentelibre.org"):
        el localpart ya identifica al contacto, así que se usa ese, capitalizado.
        Se respeta cualquier mayúscula que el usuario haya puesto (McFly, no
        Mcfly) y las palabras separadas por . _ - se capitalizan por separado.
        """
        local = str(bare_jid or "").split('@')[0]
        if not local:
            return str(bare_jid or "")
        parts = re.split(r'[._-]+', local)
        return " ".join(p[:1].upper() + p[1:] for p in parts if p) or local

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
        show = getattr(properties, 'show', None)
        show_value = getattr(show, 'value', show) or ''
        entity_caps = getattr(properties, 'entity_caps', None)
        caps_node = getattr(entity_caps, 'node', None)
        if caps_node == AGENT_CAPS_NODE:
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
        state = self._presence_state(is_online, show_value, status)
        old_presence = self.roster_items[bare].get('presence')
        if state != old_presence:
            self.roster_items[bare]['presence'] = state
            debug_print(f"XmppSession: presencia {bare} -> {state}")
            self.emit('presence-changed', bare, state)
        if (status != old_status or
                self.roster_items[bare].get('is_agent') != old_is_agent or
                self.roster_items[bare].get('agent_full_jid') != old_agent_full_jid):
            self.emit('contact-status-changed', bare)

    @classmethod
    def _presence_state(cls, is_online: bool, show: str = '', status: str = '') -> str:
        if not is_online:
            return cls.PRESENCE_OFFLINE
        lower_show = str(show or '').lower()
        lower_status = str(status or '').lower()
        if lower_show in ('dnd', 'busy') or '"availability":"busy"' in lower_status:
            return cls.PRESENCE_BUSY
        if lower_show in ('away', 'xa') or '"availability":"away"' in lower_status or '"activity":"paused"' in lower_status:
            return cls.PRESENCE_AWAY
        return cls.PRESENCE_ONLINE

    def _ensure_history(self):
        if self.history is None:
            from .platform_utils import ensure_user_dir_exists
            user_dir = ensure_user_dir_exists()
            self.history = XmppHistory(os.path.join(user_dir, "xmpp_history.db"))

    # --- Mensajes ---

    @staticmethod
    def _parse_iso(value):
        """Convierte un timestamp ISO-8601 (o epoch, por compatibilidad con
        cachés viejas) a datetime aware en UTC. None si no hay valor o no
        se puede parsear."""
        if value is None:
            return None
        from datetime import datetime, timezone
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, timezone.utc)
        try:
            dt = datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def query_mam(self, bare_jid: str, start: str = None, end: str = None,
                  after: str = None, callback: 'callable' = None):
        """Issue a MAM query for conversation history (XEP-0313).

        Returns the queryid for correlation, or None if not connected.
        Results arrive as ordinary 'message' stanzas routed through
        _on_message's MAM branch, collected in _pending_mam_queries;
        the done-callback fires on query completion with the buffered
        messages, the complete flag and the RSM `last` UID (for paging).

        start/end are the XEP-0313 query-form time filters, given here as
        ISO-8601 strings and converted to aware datetimes for nbxmpp's
        make_query (which expects datetime, not str). `after` is the RSM
        page anchor — an archive UID (NOT a timestamp), used to fetch the
        NEXT page of an incomplete result set.

        Catch-up on open uses start= (fetch everything newer than the last
        cached message) and pages forward with after= until complete.
        Scroll-to-load-older uses end= (the timestamp of the oldest message
        currently shown) to get the preceding page.
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
            start_dt = self._parse_iso(start)
            end_dt = self._parse_iso(end)
            if start_dt is not None:
                kwargs['start'] = start_dt
            if end_dt is not None:
                kwargs['end'] = end_dt
            if after is not None:
                kwargs['after'] = after
            task = self._client.get_module('MAM').make_query(**kwargs)
            # weak=False es imprescindible: add_done_callback guarda el
            # callback como weakref por defecto (weak=True). Una lambda
            # local se recolecta en cuanto query_mam retorna, y al terminar
            # el task nbxmpp la desreferencia a None y la salta en silencio
            # — el callback nunca corre y la query queda colgada. (Mismo
            # patrón que el fix de GC de commit a8f88cd.)
            task.add_done_callback(
                lambda t: self._on_mam_query_done(t, queryid), weak=False)
        except Exception as err:
            debug_print(f"XmppSession: MAM query failed: {err}")
            entry = self._pending_mam_queries.pop(queryid, None)
            if entry and entry['callback']:
                entry['callback']([], False, None)
            return None
        return queryid

    def _on_mam_query_done(self, task, queryid):
        entry = self._pending_mam_queries.pop(queryid, None)
        if entry is None:
            return
        rsm_last = None
        try:
            result = task.finish()
            complete = result.complete
            rsm_last = result.rsm.last
            debug_print(f"XmppSession: MAM query done for {entry['bare_jid']} "
                        f"complete={complete} first={result.rsm.first} "
                        f"last={rsm_last}")
        except Exception as err:
            debug_print(f"XmppSession: MAM query errored: {err}")
            complete = False
        if entry['callback']:
            entry['callback'](entry['buffer'], complete, rsm_last)

    # --- Mensajes ---

    def _on_message(self, _client, _stanza, properties):
        if properties.jid is None:
            return
        bare = str(properties.jid.bare)
        conversation = self._conversations.get(bare)
        if getattr(properties, 'is_carbon_message', False) \
                and properties.carbon.is_sent:
            # Copia de una respuesta que YO envié desde otro recurso
            # (Cheogram, Gajim, el propio Android) — no es un mensaje nuevo
            # que mostrar, pero si coincide con una quick_response
            # pendiente sirve como señal de sync más rápida que esperar la
            # corrección XEP-0308 del servidor (ver notify_own_carbon).
            if conversation is not None and properties.body:
                conversation.notify_own_carbon(properties.body)
            return

        if getattr(properties, 'is_mam_message', False):
            mam = properties.mam
            pending = self._pending_mam_queries.get(mam.query_id)
            if pending is not None and properties.body:
                direction = (
                    'out' if properties.from_ is not None
                    and properties.from_.bare == self._jid.bare else 'in')
                # nbxmpp entrega mam.timestamp como epoch (float); lo
                # normalizamos a ISO UTC para que en la caché conviva y
                # ordene junto a los mensajes en vivo (que ya se guardan
                # como isoformat()). Sin esto, get_latest_timestamp mezcla
                # floats y strings y el orden es indefinido.
                from datetime import datetime, timezone
                ts = datetime.fromtimestamp(
                    mam.timestamp, timezone.utc).isoformat()
                quick_responses = self._parse_quick_responses(_stanza)
                commands = self._parse_inline_commands(_stanza)
                # Igual que en el camino en vivo: el stanza id propio del
                # mensaje archivado (no el del envoltorio <result>) es el
                # request_id que una corrección futura usará en su
                # <replace id=...> — sin esto, preguntas descubiertas sólo
                # vía MAM (p.ej. tras reconectar) no podrían correlacionarse.
                stanza_id = _stanza.getAttr('id')
                pending['buffer'].append(
                    (properties.body, direction, ts, mam.id, quick_responses,
                     commands, stanza_id))
            return

        if properties.has_chatstate and conversation is not None:
            conversation.notify_chatstate(str(properties.chatstate))
        if not properties.body:
            return
        debug_print(f"XmppSession: mensaje de {bare}: {properties.body[:60]!r}")
        quick_responses = self._parse_quick_responses(_stanza)
        commands = self._parse_inline_commands(_stanza)
        stanza_id = _stanza.getAttr('id')
        replace_id = self._parse_replace_id(_stanza)
        correction = (replace_id, stanza_id) if replace_id else None
        if conversation is not None:
            conversation.deliver(
                properties.body, quick_responses, commands,
                correction=correction, request_id=stanza_id)
        # Emitir siempre para que la app pueda notificar si la ventana de
        # esa conversación no tiene foco (o no existe) — spec 002 T5.
        self.emit('message-received', bare, properties.body)

    def _parse_quick_responses(self, stanza) -> list[dict[str, str]]:
        responses = []
        for namespace in (QUICK_RESPONSE_NS, LEGACY_QUICK_RESPONSE_NS):
            for child in stanza.getTags('response', namespace=namespace):
                value = child.getAttr('value')
                label = child.getAttr('label') or value
                expires_at_ms = child.getAttr('expires-at-ms')
                # Hint no estándar de color de botón (primary|secondary|
                # success|danger) que emite el plugin XMPP de OpenClaw. Lo
                # renderiza add_quick_responses; los demás clientes lo ignoran.
                style = child.getAttr('style')
                if value and label:
                    response = {'value': value, 'label': label}
                    if expires_at_ms:
                        response['expires_at_ms'] = expires_at_ms
                    if style:
                        response['style'] = style
                    responses.append(response)
            if responses:
                continue
            for reference in stanza.getTags('reference', namespace=namespace):
                if reference.getAttr('type') != 'action':
                    continue
                for body in reference.getTags('body'):
                    value = body.getData()
                    if value:
                        responses.append({'value': value, 'label': value})
        return responses

    def _parse_inline_commands(self, stanza) -> list[dict[str, str]]:
        commands = []
        queries = list(stanza.getTags('query', namespace=DISCO_ITEMS_NS))
        if not queries:
            # nbxmpp has changed namespace matching details across releases.
            # Fall back to explicit child inspection so inline XEP-0050
            # announcements do not degrade to plain fallback text.
            for child in stanza.getTags('query'):
                namespace = getattr(child, 'getNamespace', lambda: None)()
                if namespace == DISCO_ITEMS_NS:
                    queries.append(child)
        for query in queries:
            node = query.getAttr('node')
            if node != COMMANDS_NS:
                continue
            for item in query.getTags('item'):
                jid = item.getAttr('jid')
                cmd_node = item.getAttr('node')
                name = item.getAttr('name')
                style = item.getAttr('style')
                if jid and cmd_node and name:
                    command = {'jid': jid, 'node': cmd_node, 'name': name}
                    if style:
                        command['style'] = style
                    commands.append(command)
        return commands

    @staticmethod
    def _parse_replace_id(stanza) -> str | None:
        for replace in stanza.getTags('replace', namespace=MESSAGE_CORRECT_NS):
            return replace.getAttr('id')
        return None

    def send_text(self, to_bare_jid: str, text: str):
        # XEP-0085: marcar 'active' junto con cada mensaje
        chatstate = Node('active', attrs={'xmlns': Namespace.CHATSTATES})
        msg = Message(to=to_bare_jid, body=text, typ='chat', payload=[chatstate])
        debug_print(f"XmppSession: enviando mensaje a {to_bare_jid}: {text[:60]!r}")
        self._client.send_stanza(msg)

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
        # request_id (stanza id propio) -> {values de sus quick_responses}
        # para preguntas recientes aún sin resolver. Permite que (a) una
        # corrección XEP-0308 entrante se reconozca sin importar si es la
        # más reciente, y (b) un carbon de la propia respuesta enviada
        # desde OTRO recurso se correlacione con la pregunta que resuelve
        # por texto, como señal de sync más rápida que esperar la
        # corrección del servidor.
        self._pending_request_ids: dict[str, set[str]] = {}
        session._ensure_history()
        # Guardar los handler ids para poder desconectarlos en shutdown:
        # la sesión es compartida y vive más que esta conversación.
        self._session_handlers = [
            session.connect('state-changed', self._on_session_state),
            session.connect('session-error', self._on_session_error),
        ]
        self._history_shown_from: str | None = None
        self._pending_mam_queryid: str | None = None
        self._mam_catchup_start: str | None = None
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

    def deliver(self, body: str, quick_responses=None, commands=None,
                correction=None, request_id=None):
        """Un mensaje del contacto: response + finished, cached.

        Si correction es una tupla (replace_id, stanza_id) se busca
        replace_id entre CUALQUIER pregunta pendiente reciente (no sólo la
        última — con varias preguntas abiertas a la vez, una corrección
        para cualquiera de ellas debe reconocerse, no sólo la más nueva;
        antes esto sólo comparaba contra self.last_incoming_id, un único
        valor). Si no coincide con ninguna, se trata como mensaje normal
        (degradación elegante)."""
        if correction is not None:
            replace_id, _stanza_id = correction
            if replace_id and replace_id in self._pending_request_ids:
                self._deliver_correction(replace_id, body)
                return
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        history = self.session.history
        # El propio stanza_id de este mensaje es el request_id que una
        # futura corrección usará en su <replace id=...> para apuntar aquí
        # — sólo tiene sentido guardarlo si trae algo que luego pueda
        # resolverse (quick_responses/commands).
        if request_id is None and correction:
            request_id = correction[1]
        has_pending = bool(quick_responses) or bool(commands)
        if history is not None:
            history.record_message(
                self.bare_jid, body, 'in', ts,
                quick_responses=quick_responses, commands=commands,
                request_id=request_id if has_pending else None)
        if has_pending and request_id:
            self._track_pending_request(request_id, quick_responses)
        self.emit('response', body)
        # Preferir command-items (XEP-0050, responde por IQ off-band) sobre
        # quick-responses (texto en el body) cuando el mensaje trae ambos.
        # El plugin XMPP de OpenClaw manda ambos en el mismo <message> por
        # compatibilidad; como NanoClaw, aquí preferimos el camino IQ para no
        # dejar el `value` crudo visible en el chat. Los clientes sólo-texto
        # (o mensajes sin command-items) siguen usando quick-responses.
        if commands:
            self.emit('commands', commands, request_id)
        elif quick_responses:
            self.emit('quick-responses', quick_responses, request_id)
        self.emit('finished', True)

    def _track_pending_request(self, request_id: str, quick_responses=None,
                               max_tracked: int = 50):
        """Recuerda ids de preguntas recientes con quick_responses/commands
        pendientes, para que deliver() pueda reconocer una corrección que
        llegue para cualquiera de ellas (no sólo la última), y para que un
        carbon de la propia respuesta pueda correlacionarse por texto (ver
        notify_own_carbon). Cota simple de tamaño en vez de expirar por
        tiempo — alcanza para el uso real (pocas preguntas concurrentes por
        conversación)."""
        values = {
            r.get('value', '') for r in (quick_responses or []) if r.get('value')
        }
        self._pending_request_ids[request_id] = values
        if len(self._pending_request_ids) > max_tracked:
            # Orden de inserción no se trackea con un dict-de-inserción
            # simple aquí; en la práctica esto sólo dispara con un backlog
            # anómalo, así que un vaciado simple es aceptable en vez de
            # mantener estructura ordenada.
            self._pending_request_ids.clear()
            self._pending_request_ids[request_id] = values

    def _deliver_correction(self, request_id: str, body: str):
        history = self.session.history
        if history is not None:
            history.update_by_request_id(self.bare_jid, request_id, body)
        self._pending_request_ids.pop(request_id, None)
        self.emit('response-correction', request_id, body)
        self.emit('finished', True)

    def notify_own_carbon(self, body: str):
        """Carbon (XEP-0280) de una respuesta que YO envié desde otro
        recurso/dispositivo. Señal secundaria y más rápida que la
        corrección XEP-0308 del servidor (que llega después, cuando el
        agente procesa la respuesta): si el texto coincide con el value de
        alguna quick_response pendiente, atenuamos su card ya mismo. No
        toca el body de la pregunta original — sólo limpia las acciones,
        la corrección real (si llega) sigue su propio camino en deliver()."""
        for request_id, values in list(self._pending_request_ids.items()):
            if body not in values:
                continue
            history = self.session.history
            if history is not None:
                history.mark_resolved_by_request_id(self.bare_jid, request_id)
            self._pending_request_ids.pop(request_id, None)
            self.emit('own-carbon-resolved', request_id)
            return

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

    # send_command (legacy: solo action='execute', leía un <note> e ignoraba
    # los formularios XEP-0004) fue retirado. Los comandos ad-hoc, tanto los
    # del menú del agente como los inline anunciados en un mensaje, se
    # ejecutan ahora por XmppCommandClient / _execute_agent_command en
    # chat_window.py, que sí renderiza formularios.

    def cancel(self):
        pass

    def get_conversation_id(self):
        return f"xmpp:{self.session.bare_jid}:{self.bare_jid}"

    def get_display_name(self) -> str:
        return self.session.get_contact_name(self.bare_jid)

    def notify_composing(self, is_composing: bool):
        state = 'composing' if is_composing else 'active'
        self.session.send_chatstate(self.bare_jid, state)

    def quick_response_was_answered(self, timestamp: str, values) -> bool:
        history = self.session.history
        if history is None:
            return False
        return history.has_outgoing_after(self.bare_jid, timestamp, values)

    # --- History (spec 004) ---

    def load_history_from_cache(self):
        self._emit_history_from_cache(verified_only=False)

    def _emit_history_from_cache(self, verified_only: bool):
        history = self.session.history
        if history is None:
            self.emit('history-complete', False)
            return
        messages = history.get_recent(self.bare_jid, verified_only=verified_only)
        if not messages:
            self.emit('history-complete', False)
            return
        for msg in messages:
            self.emit('history-message', msg['body'], msg['direction'], msg['timestamp'])
            if msg.get('quick_responses') or msg.get('commands'):
                self.emit(
                    'history-actions', msg['body'], msg['timestamp'],
                    msg.get('quick_responses', []), msg.get('commands', []),
                    msg.get('request_id'))
                if msg.get('request_id'):
                    self._track_pending_request(
                        msg['request_id'], msg.get('quick_responses'))
        self._history_shown_from = messages[0]['timestamp']
        self.emit('history-complete', True)

    def load_history_from_mam(self) -> bool:
        """Consulta MAM los mensajes más nuevos que el último cacheado y
        pagina hacia adelante hasta agotar el archivo.

        Devuelve True si se lanzó una consulta (y por tanto llegará un
        'history-complete'), False si se ignoró (ya hay una en curso, no
        hay conexión, o make_query falló). El llamador usa esto para no
        desbalancear su contador de lotes en la reconexión.

        Clave: con más mensajes que el tamaño de página (50), MAM devuelve
        los 50 MÁS VIEJOS del rango con complete=False; sin paginar, los
        mensajes recientes nunca se cargarían (se veían en Gajim pero no
        aquí). Por eso _on_mam_catchup_page reitera con after=<rsm.last>.
        """
        if not self.session.is_connected or self._pending_mam_queryid is not None:
            return False
        history = self.session.history
        latest_mam_id = history.get_latest_mam_id(self.bare_jid) if history else None
        if latest_mam_id:
            # Cursor-first: ya tenemos un punto verificado del archivo, así
            # que pedimos sólo lo posterior (RSM after=) en vez de repetir
            # una ventana de tiempo fija cada vez que se abre la
            # conversación — evita re-consultar días de archivo ya cubierto.
            self._mam_catchup_start = None
            self._pending_mam_queryid = self.session.query_mam(
                self.bare_jid, after=latest_mam_id,
                callback=self._on_mam_catchup_page)
            return self._pending_mam_queryid is not None
        # Sin mam_id cacheado (conversación nueva, o historial previo sin
        # verificar contra el archivo): fallback al overlap por tiempo.
        latest = history.get_latest_timestamp(self.bare_jid) if history else None
        start_ts = self._overlap_timestamp(latest)
        self._mam_catchup_start = start_ts
        self._pending_mam_queryid = self.session.query_mam(
            self.bare_jid, start=start_ts, callback=self._on_mam_catchup_page)
        return self._pending_mam_queryid is not None

    @staticmethod
    def _overlap_timestamp(iso_value, hours=24 * 7):
        dt = XmppSession._parse_iso(iso_value)
        if dt is None:
            return None
        from datetime import timedelta
        return (dt - timedelta(hours=hours)).isoformat()

    def load_more_history(self):
        history = self.session.history
        if history is None:
            return
        older = history.get_before(self.bare_jid, self._history_shown_from, limit=50)
        if older:
            for msg in older:
                self.emit('history-message', msg['body'], msg['direction'], msg['timestamp'])
                if msg.get('quick_responses') or msg.get('commands'):
                    self.emit(
                        'history-actions', msg['body'], msg['timestamp'],
                        msg.get('quick_responses', []), msg.get('commands', []),
                        msg.get('request_id'))
                    if msg.get('request_id'):
                        self._track_pending_request(
                            msg['request_id'], msg.get('quick_responses'))
            self._history_shown_from = older[0]['timestamp']
            self.emit('history-complete', True)
            return
        if self.session.is_connected:
            self._pending_mam_queryid = self.session.query_mam(
                self.bare_jid, end=self._history_shown_from, callback=self._on_mam_page)

    def _record_and_emit(self, messages):
        """Persiste en caché y emite a la UI cada mensaje de una página MAM."""
        history = self.session.history
        for item in messages:
            body, direction, timestamp, mam_id = item[:4]
            quick_responses = item[4] if len(item) > 4 else []
            commands = item[5] if len(item) > 5 else []
            # El id de stanza propio de este mensaje (si trae quick_responses/
            # commands) es su request_id — igual que en deliver() para
            # mensajes en vivo, así una corrección que llegue después (vía
            # MAM o en vivo) puede encontrarlo sin depender de ser el último.
            request_id = item[6] if len(item) > 6 else None
            has_pending = bool(quick_responses) or bool(commands)
            if (history is not None and
                    history.attach_mam_to_recent_message(
                        self.bare_jid, body, direction, timestamp, mam_id,
                        quick_responses=quick_responses, commands=commands,
                        request_id=request_id if has_pending else None)):
                continue
            inserted = True
            if history is not None:
                inserted = history.record_message(
                    self.bare_jid, body, direction, timestamp, mam_id,
                    quick_responses=quick_responses, commands=commands,
                    request_id=request_id if has_pending else None)
            if has_pending and request_id and direction == 'in':
                self._track_pending_request(request_id, quick_responses)
            if inserted:
                self.emit('history-message', body, direction, timestamp)
                if quick_responses or commands:
                    self.emit(
                        'history-actions', body, timestamp, quick_responses,
                        commands, request_id)
            elif quick_responses or commands:
                self.emit(
                    'history-actions', body, timestamp, quick_responses,
                    commands, request_id)

    def _on_mam_catchup_page(self, messages, complete, rsm_last):
        """Página del catch-up hacia adelante (start=). Emite lo recibido y,
        si el archivo no está completo, pide la siguiente página con
        after=<rsm.last>. Solo al terminar (o sin más páginas) emite
        history-complete, para que la UI trate todo como un lote de
        backfill."""
        self._pending_mam_queryid = None
        self._record_and_emit(messages)
        # Paginar hacia adelante mientras haya más y sepamos desde dónde.
        if not complete and rsm_last and self.session.is_connected:
            self._pending_mam_queryid = self.session.query_mam(
                self.bare_jid, start=self._mam_catchup_start,
                after=rsm_last, callback=self._on_mam_catchup_page)
            if self._pending_mam_queryid is not None:
                return
        self.emit('history-complete', False)

    def _on_mam_page(self, messages, complete, rsm_last=None):
        self._pending_mam_queryid = None
        self._record_and_emit(messages)
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
