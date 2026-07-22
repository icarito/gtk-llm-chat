"""
xmpp_omemo.py - Integración OMEMO (XEP-0384) para XmppSession.

Implementa el almacenamiento basado en archivos JSON y la sincronización PubSub
con nbxmpp para OMEMO (tanto legacy eu.siacs.conversations.axolotl como urn:xmpp:omemo:2).
"""
import os
import json
import socket
import asyncio
import faulthandler
import sys
import traceback
import threading
from xml.etree import ElementTree as ET

from gi.repository import GLib

from nbxmpp import Node, JID
from nbxmpp.namespaces import Namespace

from .debug_utils import debug_print
from .platform_utils import ensure_user_dir_exists

# python-omemo imports
from omemo import (
    SessionManager,
    AsyncFramework,
    TrustLevel,
    BundleNotFound,
    DeviceListDownloadFailed,
    BundleDownloadFailed,
    NoEligibleDevices,
    JSONType,
    Maybe,
    Just,
    Nothing
)
from omemo.storage import Storage, StorageException
from omemo.backend import Backend
from omemo.types import DeviceInformation, DeviceList

from oldmemo import Oldmemo
from oldmemo.oldmemo import BundleImpl as OldBundleImpl
from oldmemo.etree import (
    serialize_device_list as old_serialize_device_list,
    parse_device_list as old_parse_device_list,
    serialize_bundle as old_serialize_bundle,
    parse_bundle as old_parse_bundle,
    serialize_message as old_serialize_message,
    parse_message as old_parse_message
)

try:
    from twomemo import Twomemo
    from twomemo.twomemo import BundleImpl as TwoBundleImpl
    from twomemo.etree import (
        serialize_device_list as two_serialize_device_list,
        parse_device_list as two_parse_device_list,
        serialize_bundle as two_serialize_bundle,
        parse_bundle as two_parse_bundle,
        serialize_message as two_serialize_message,
        parse_message as two_parse_message
    )
    twomemo_available = True
except ImportError:
    twomemo_available = False

# XML Namespaces
LEGACY_NS = "eu.siacs.conversations.axolotl"
TWOMEMO_NS = "urn:xmpp:omemo:2"


# --- XML Conversion Utilities ---

def etree_to_node(et_element) -> Node:
    """Convierte de xml.etree.ElementTree.Element a nbxmpp.Node."""
    tag = et_element.tag
    ns = None
    if tag.startswith('{'):
        ns, tag = tag[1:].split('}', 1)
        attrs = {'xmlns': ns}
    else:
        attrs = {}
    for k, v in et_element.attrib.items():
        if k.startswith('{'):
            _, k = k[1:].split('}', 1)
        attrs[k] = v
    node = Node(tag, attrs=attrs)
    if ns:
        node.setNamespace(ns)
    if et_element.text:
        node.setData(et_element.text)
    for child in et_element:
        node.addChild(node=etree_to_node(child))
    return node


def node_to_etree(node, parent_ns=None) -> ET.Element:
    """Convierte de nbxmpp.Node a xml.etree.ElementTree.Element."""
    ns = node.getNamespace() or parent_ns
    tag = f"{{{ns}}}{node.getName()}" if ns else node.getName()
    attrib = {}
    for k, v in node.getAttrs().items():
        if k == 'xmlns':
            continue
        attrib[k] = str(v)
    et_element = ET.Element(tag, attrib=attrib)
    data = node.getData()
    if data:
        et_element.text = data
    for child in node.getChildren():
        et_element.append(node_to_etree(child, parent_ns=ns))
    return et_element


def _strip_non_schema_device_attributes(element: ET.Element) -> ET.Element:
    """Acepta clientes que añaden ``label`` a <device> (OMEMO 2)."""
    for child in element.iter():
        tag = child.tag.rsplit('}', 1)[-1] if isinstance(child.tag, str) else ''
        if tag == 'device':
            child.attrib.pop('label', None)
    return element


# --- Storage Provider ---

class JSONStorage(Storage):
    """Almacenamiento persistente en JSON para claves e información OMEMO."""

    def __init__(self, filepath: str):
        super().__init__()
        self.filepath = filepath
        self.data = {}
        self.load_from_file()

    def load_from_file(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
                debug_print(f"OMEMO JSONStorage: cargado {len(self.data)} entradas de {self.filepath}")
            except Exception as e:
                debug_print(f"OMEMO JSONStorage: error al cargar {self.filepath}: {e}")
                self.data = {}
        else:
            self.data = {}

    def save_to_file(self):
        tmp_path = f"{self.filepath}.tmp"
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self.filepath)
            os.chmod(self.filepath, 0o600)
        except Exception as e:
            debug_print(f"OMEMO JSONStorage: error al guardar {self.filepath}: {e}")
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass

    async def _load(self, key: str) -> Maybe[JSONType]:
        print(f"[omemo-storage] load key={key}", flush=True)
        if key in self.data:
            return Just(self.data[key])
        return Nothing()

    async def _store(self, key: str, value: JSONType) -> None:
        print(f"[omemo-storage] store key={key}", flush=True)
        self.data[key] = value
        self.save_to_file()

    async def _delete(self, key: str) -> None:
        if key in self.data:
            del self.data[key]
            self.save_to_file()


# --- Thread-Safe nbxmpp Task bridging ---

def run_on_main_thread(func, *args, **kwargs):
    """Ejecuta una función en el hilo principal de GLib y devuelve un Future de asyncio."""
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    timeout_handle = None

    def complete_result(result):
        if not future.done():
            future.set_result(result)

    def complete_exception(error):
        if not future.done():
            future.set_exception(error)

    def main_thread_callback():
        try:
            name = getattr(func, '__name__', repr(func))
            debug_print(f"[omemo-glib] call {name}")
            print(f"[omemo-glib] call {name}", flush=True)
            task = func(*args, **kwargs)
            if task is None:
                if timeout_handle is not None:
                    timeout_handle.cancel()
                loop.call_soon_threadsafe(complete_result, None)
                return

            def on_done(t):
                try:
                    res = t.finish()
                    debug_print(f"[omemo-glib] done {name}")
                    print(f"[omemo-glib] done {name}", flush=True)
                    if timeout_handle is not None:
                        timeout_handle.cancel()
                    loop.call_soon_threadsafe(complete_result, res)
                except Exception as e:
                    if timeout_handle is not None:
                        timeout_handle.cancel()
                    loop.call_soon_threadsafe(complete_exception, e)

            task.add_done_callback(on_done, weak=False)
        except Exception as e:
            if timeout_handle is not None:
                timeout_handle.cancel()
            loop.call_soon_threadsafe(complete_exception, e)

    GLib.idle_add(main_thread_callback)
    timeout_handle = loop.call_later(
        20,
        complete_exception,
        TimeoutError(f"GLib XMPP operation timed out: {getattr(func, '__name__', repr(func))}"),
    )
    return future


# --- OMEMO Session Manager ---

class XmppOMEMOSessionManager(SessionManager):
    """Manejador de sesión OMEMO que interactúa con nbxmpp PubSub de forma segura."""

    _session_instance = None  # Instancia activa de XmppSession

    @classmethod
    def set_session_instance(cls, session):
        cls._session_instance = session

    @classmethod
    def get_session_instance(cls):
        return cls._session_instance

    @staticmethod
    def _get_pubsub_module():
        session = XmppOMEMOSessionManager.get_session_instance()
        if session is None or session._client is None:
            raise RuntimeError("No hay cliente XMPP activo conectado")
        return session._client.get_module('PubSub')

    @staticmethod
    def _get_device_list_node(namespace: str) -> str:
        if namespace == TWOMEMO_NS:
            return f"{TWOMEMO_NS}:devices"
        return f"{LEGACY_NS}.devicelist"

    @staticmethod
    def _get_bundle_node(namespace: str, device_id: int) -> str:
        if namespace == TWOMEMO_NS:
            return f"{TWOMEMO_NS}:bundles"
        return f"{LEGACY_NS}.bundles:{device_id}"

    @staticmethod
    async def _delete_bundle(namespace: str, device_id: int) -> None:
        pubsub = XmppOMEMOSessionManager._get_pubsub_module()
        await run_on_main_thread(
            pubsub.retract,
            XmppOMEMOSessionManager._get_bundle_node(namespace, device_id),
            str(device_id),
            notify=True,
        )

    async def _evaluate_custom_trust_level(self, device: DeviceInformation) -> TrustLevel:
        # The desktop client currently exposes no interactive fingerprint UI.
        # Preserve the PR's explicit always-trust policy until that UI exists.
        if device.trust_level_name == "undecided":
            return TrustLevel.TRUSTED
        if device.trust_level_name == "trusted":
            return TrustLevel.TRUSTED
        return TrustLevel.DISTRUSTED

    async def _make_trust_decision(self, undecided, identifier):
        for device in undecided:
            await self.set_trust(device.bare_jid, device.identity_key, "trusted")

    @staticmethod
    async def _send_message(message, bare_jid: str) -> None:
        session = XmppOMEMOSessionManager.get_session_instance()
        if session is None or session._client is None:
            raise RuntimeError("No hay cliente XMPP activo conectado")
        if message.namespace == TWOMEMO_NS:
            et_el = two_serialize_message(message)
        else:
            et_el = old_serialize_message(message)
        stanza = Message(to=bare_jid, typ="chat")
        stanza.addChild(node=etree_to_node(et_el))
        await run_on_main_thread(session._client.send_stanza, stanza)

    @staticmethod
    async def _upload_bundle(bundle) -> None:
        debug_print(f"OMEMO: publicando bundle para {bundle.namespace} (dispositivo {bundle.device_id})")
        pubsub = XmppOMEMOSessionManager._get_pubsub_module()
        node_name = XmppOMEMOSessionManager._get_bundle_node(bundle.namespace, bundle.device_id)

        if bundle.namespace == TWOMEMO_NS:
            et_el = two_serialize_bundle(bundle)
        else:
            et_el = old_serialize_bundle(bundle)

        nb_node = etree_to_node(et_el)
        await run_on_main_thread(
            pubsub.publish,
            node_name,
            nb_node,
            id_=str(bundle.device_id),
            options={
                "pubsub#persist_items": "true",
                "pubsub#max_items": "100" if bundle.namespace == TWOMEMO_NS else "1",
                "pubsub#access_model": "open",
            },
            force_node_options=True,
        )

    @staticmethod
    async def _download_bundle(namespace: str, bare_jid: str, device_id: int):
        debug_print(f"OMEMO: descargando bundle para {bare_jid} dispositivo {device_id} ({namespace})")
        pubsub = XmppOMEMOSessionManager._get_pubsub_module()
        node_name = XmppOMEMOSessionManager._get_bundle_node(namespace, device_id)

        try:
            items = await run_on_main_thread(
                pubsub.request_items,
                node_name,
                max_items=100 if namespace == TWOMEMO_NS else 1,
                jid=JID.from_string(bare_jid),
            )
        except Exception as e:
            if namespace != TWOMEMO_NS:
                debug_print(f"OMEMO: error al descargar bundle {node_name} de {bare_jid}: {e}")
                raise BundleNotFound(f"Bundle {node_name} de {bare_jid} no encontrado: {e}")
            # Read compatibility with the early per-device OMEMO 2 draft.
            legacy_node = f"{TWOMEMO_NS}:bundles:{device_id}"
            try:
                items = await run_on_main_thread(
                    pubsub.request_items, legacy_node, max_items=1,
                    jid=JID.from_string(bare_jid),
                )
                node_name = legacy_node
            except Exception as legacy_error:
                debug_print(f"OMEMO: error al descargar bundle {node_name} de {bare_jid}: {legacy_error}")
                raise BundleNotFound(
                    f"Bundle {node_name} de {bare_jid} no encontrado: {legacy_error}"
                )

        for item in items or []:
            if namespace == TWOMEMO_NS and node_name == f"{TWOMEMO_NS}:bundles":
                item_id = item.getAttr("id")
                if item_id is not None and item_id != str(device_id):
                    continue
            bundle_tag = "bundle"
            bundle_el = item.getTag(bundle_tag, namespace=namespace)
            if bundle_el is None:
                continue
            et_el = node_to_etree(bundle_el)
            if namespace == TWOMEMO_NS:
                return two_parse_bundle(et_el, bare_jid, device_id)
            else:
                return old_parse_bundle(et_el, bare_jid, device_id)

        if namespace == TWOMEMO_NS and node_name == f"{TWOMEMO_NS}:bundles":
            legacy_node = f"{TWOMEMO_NS}:bundles:{device_id}"
            try:
                legacy_items = await run_on_main_thread(
                    pubsub.request_items, legacy_node, max_items=1,
                    jid=JID.from_string(bare_jid),
                )
            except Exception:
                legacy_items = []
            for item in legacy_items or []:
                bundle_el = item.getTag("bundle", namespace=namespace)
                if bundle_el is not None:
                    return two_parse_bundle(node_to_etree(bundle_el), bare_jid, device_id)

        raise BundleNotFound(f"Bundle {node_name} de {bare_jid} no encontrado en la respuesta PubSub")

    @staticmethod
    async def _upload_device_list(namespace: str, device_list: DeviceList) -> None:
        debug_print(f"OMEMO: publicando lista de dispositivos para {namespace}: {list(device_list.keys())}")
        pubsub = XmppOMEMOSessionManager._get_pubsub_module()
        node_name = XmppOMEMOSessionManager._get_device_list_node(namespace)

        if namespace == TWOMEMO_NS:
            et_el = two_serialize_device_list(device_list)
        else:
            et_el = old_serialize_device_list(device_list)

        nb_node = etree_to_node(et_el)
        await run_on_main_thread(
            pubsub.publish,
            node_name,
            nb_node,
            id_="current",
            options={
                "pubsub#persist_items": "true",
                "pubsub#max_items": "1",
                "pubsub#access_model": "open",
            },
            force_node_options=True,
        )

    @staticmethod
    async def _download_device_list(namespace: str, bare_jid: str) -> DeviceList:
        debug_print(f"OMEMO: descargando lista de dispositivos para {bare_jid} ({namespace})")
        pubsub = XmppOMEMOSessionManager._get_pubsub_module()
        node_name = XmppOMEMOSessionManager._get_device_list_node(namespace)

        try:
            items = await run_on_main_thread(
                pubsub.request_items, node_name, max_items=1, jid=JID.from_string(bare_jid)
            )
        except Exception as e:
            debug_print(f"OMEMO: error al descargar lista de dispositivos para {bare_jid}: {e}")
            return {}

        for item in items or []:
            tag_name = "devices" if namespace == TWOMEMO_NS else "list"
            list_el = item.getTag(tag_name, namespace=namespace)
            if list_el is None:
                continue
            et_el = node_to_etree(list_el)
            if namespace == TWOMEMO_NS:
                return two_parse_device_list(et_el)
            else:
                et_el = _strip_non_schema_device_attributes(et_el)
                return old_parse_device_list(et_el)

        return {}


# --- Background Asyncio Loop for OMEMO ---

class OMEMOAsyncWorker:
    """Hilo de ejecución en segundo plano con un event loop de asyncio."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run_coroutine(self, coro, timeout=None):
        """Ejecuta una corrutina de forma síncrona esperando su resultado.

        A network-backed OMEMO operation must not be allowed to leave the
        outbound delivery bubble pending forever.
        """
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            raise


class OMEMOEngine:
    """Fachada para interactuar con OMEMO de manera síncrona y segura desde XmppSession."""

    def __init__(self, session, jid_str: str):
        self.session = session
        self.jid_str = jid_str
        self.worker = OMEMOAsyncWorker()
        self.manager = None

        # Ruta del archivo de persistencia
        user_dir = ensure_user_dir_exists()
        omemo_dir = os.path.join(user_dir, 'omemo')
        os.makedirs(omemo_dir, exist_ok=True)
        safe_jid = jid_str.lower().replace('/', '_')
        self.storage_path = os.path.join(omemo_dir, f"{safe_jid}.json")
        self.storage = JSONStorage(self.storage_path)

    def initialize(self, label: str):
        """Inicializa las claves OMEMO en segundo plano."""
        XmppOMEMOSessionManager.set_session_instance(self.session)
        print(f"[omemo-init] initialize-enter source={__file__} jid={self.jid_str}", flush=True)
        debug_print(
            f"[omemo-init] start jid={self.jid_str} "
            f"oldmemo=True twomemo={twomemo_available} storage={self.storage_path}"
        )

        # Configurar backends
        backends = [Oldmemo(self.storage)]
        if twomemo_available:
            backends.append(Twomemo(self.storage))
        else:
            print(
                "[omemo-init] WARNING: twomemo package unavailable; "
                "OMEMO 2 decrypt/encrypt is disabled",
                flush=True,
            )

        async def _init_coro():
            print(f"[omemo-init] create-start jid={self.jid_str}", flush=True)
            debug_print(f"[omemo-init] create-start jid={self.jid_str}")
            print("[omemo-init] manager-create-call", flush=True)
            manager = await XmppOMEMOSessionManager.create(
                backends=backends,
                storage=self.storage,
                own_bare_jid=self.jid_str,
                initial_own_label=label,
                undecided_trust_level_name="undecided"
            )
            print(f"[omemo-init] create-done jid={self.jid_str}", flush=True)
            debug_print(f"[omemo-init] create-done jid={self.jid_str}")
            # Migrate existing installations from the early per-device v2
            # bundle node to the standard shared :bundles node.  Creating a
            # manager from persisted state does not otherwise republish its
            # already-generated bundle, leaving new peers unable to identify
            # this sender.
            if twomemo_available:
                own_device_id = (await self.storage.load_primitive(
                    "/own_device_id", int
                )).from_just()
                twomemo_backend = next(
                    backend for backend in backends
                    if backend.namespace == TWOMEMO_NS
                )
                own_bundle = await twomemo_backend.get_bundle(
                    self.jid_str, own_device_id
                )
                await XmppOMEMOSessionManager._upload_bundle(own_bundle)
                # Also reconcile the online device list.  Existing local
                # state may contain our device even when the PEP node was
                # never created (or was lost), in which case create() alone
                # has nothing to republish.
                await manager.refresh_device_list(TWOMEMO_NS, self.jid_str)
                debug_print(
                    f"[omemo-init] republished standard OMEMO 2 bundle/device "
                    f"device={own_device_id}"
                )
            # Salir de modo sincronización de historial inicial
            await manager.after_history_sync()
            debug_print(f"[omemo-init] history-sync-done jid={self.jid_str}")
            return manager

        try:
            faulthandler.dump_traceback_later(3, repeat=False)
            def dump_omemo_stack():
                for thread_id, frame in sys._current_frames().items():
                    frames = traceback.extract_stack(frame)
                    relevant = [f for f in frames if "omemo" in f.filename or "xmpp" in f.filename]
                    if relevant:
                        print(f"[omemo-stack] thread={thread_id}", flush=True)
                        for item in relevant[-12:]:
                            print(f"[omemo-stack] {item.filename}:{item.lineno} {item.name}", flush=True)
            stack_timer = threading.Timer(3, dump_omemo_stack)
            stack_timer.daemon = True
            stack_timer.start()
            self.manager = self.worker.run_coroutine(_init_coro(), timeout=60)
            stack_timer.cancel()
            faulthandler.cancel_dump_traceback_later()
            debug_print(f"[omemo-init] ready jid={self.jid_str} label={label}")
        except Exception as e:
            stack_timer.cancel()
            faulthandler.cancel_dump_traceback_later()
            self.manager = None
            debug_print(f"[omemo-init] failed jid={self.jid_str} error={e!r}")
            debug_print(traceback.format_exc())

    def encrypt_msg_async(self, to_bare_jid: str, text: str):
        """Encripta para el destinatario usando la API OMEMO 2.1.

        ``SessionManager.encrypt`` recibe destinatarios inmutables y un mapa de
        plaintext por backend; devuelve un mapa de mensajes (uno por backend)
        junto con errores no críticos. Se conserva compatibilidad con los
        llamadores antiguos devolviendo un Node cuando hay un solo backend y
        una lista de Nodes cuando hay varios.
        """
        if self.manager is None:
            return None, text

        print(f"[omemo-encrypt] start target={to_bare_jid} len={len(text)}", flush=True)

        async def _encrypt_coro():
            recipients = frozenset({to_bare_jid})
            try:
                if twomemo_available:
                    # Los clientes OMEMO 2 pueden anunciar también el
                    # namespace legacy sin publicar su bundle. Evitar que la
                    # biblioteca intente descargar ese bundle durante la
                    # resolución inicial de identidad.
                    # Refresh unconditionally.  A cached v2 device can be
                    # retired and replaced (for example during an identity
                    # migration), so merely finding one local entry is not
                    # proof that the online list is current.
                    debug_print(f"OMEMO: refrescando device list OMEMO 2 de {to_bare_jid}")
                    await asyncio.wait_for(
                        self.manager.refresh_device_list(TWOMEMO_NS, to_bare_jid),
                        timeout=8,
                    )
                    ids = (await self.storage.load_list(
                        f"/devices/{to_bare_jid}/list", int
                    )).maybe([])

                    for device_id in ids:
                        key = f"/devices/{to_bare_jid}/{device_id}"
                        namespaces = (await self.storage.load_list(
                            f"{key}/namespaces", str
                        )).maybe([])
                        active = (await self.storage.load_dict(
                            f"{key}/active", bool
                        )).maybe({})
                        if TWOMEMO_NS in namespaces:
                            await self.storage.store(
                                f"{key}/namespaces", [TWOMEMO_NS]
                            )
                            await self.storage.store(
                                f"{key}/active", {TWOMEMO_NS: bool(active.get(TWOMEMO_NS, True))}
                            )
                plaintext_bytes = text.encode('utf-8')
                # Preferir OMEMO 2 para envíos: los clientes modernos (Dino,
                # OpenClaw) pueden publicar solo el bundle urn:xmpp:omemo:2.
                # El backend legacy permanece cargado para descifrar mensajes
                # antiguos, pero no debe bloquear el cifrado saliente.
                if twomemo_available:
                    plaintext = {TWOMEMO_NS: plaintext_bytes}
                else:
                    plaintext = {LEGACY_NS: plaintext_bytes}
                encrypted_messages, errors = await asyncio.wait_for(
                    self.manager.encrypt(
                        recipients,
                        plaintext,
                        backend_priority_order=[TWOMEMO_NS] if twomemo_available else [LEGACY_NS],
                    ), timeout=20
                )
                if errors:
                    debug_print(f"OMEMO: errores no críticos al cifrar para {to_bare_jid}: {errors}")
                if not encrypted_messages:
                    raise NoEligibleDevices(f"no encrypted messages for {to_bare_jid}")
            except NoEligibleDevices as e:
                debug_print(f"OMEMO: no hay dispositivos OMEMO elegibles para {to_bare_jid}: {e}")
                return None, text
            except Exception as e:
                debug_print(f"OMEMO: error durante encriptación OMEMO: {e}")
                return None, text

            nodes = []
            for omemo_message in encrypted_messages.keys():
                namespace = omemo_message.namespace
                if namespace == TWOMEMO_NS:
                    et_el = two_serialize_message(omemo_message)
                elif namespace == LEGACY_NS:
                    et_el = old_serialize_message(omemo_message)
                else:
                    debug_print(f"OMEMO: namespace desconocido {namespace}; se omite")
                    continue
                nodes.append(etree_to_node(et_el))
            if not nodes:
                return None, text
            print(f"[omemo-encrypt] done target={to_bare_jid} nodes={len(nodes)}", flush=True)
            return (nodes[0] if len(nodes) == 1 else nodes), text

        try:
            return self.worker.run_coroutine(_encrypt_coro(), timeout=10)
        except Exception as e:
            debug_print(f"OMEMO: Error encriptando mensaje: {e}")
            print(f"[omemo-encrypt] failed target={to_bare_jid} error={e!r}", flush=True)
            return None, text

    def decrypt_msg(self, from_bare_jid: str, encrypted_node: Node) -> str | None:
        """Desencripta un nodo encriptado entrante."""
        if self.manager is None:
            return None
        print(f"[omemo-decrypt] start from={from_bare_jid}", flush=True)

        # Convertir a ElementTree
        et_el = node_to_etree(encrypted_node)
        ns = encrypted_node.getNamespace()

        async def _decrypt_coro():
            if ns == TWOMEMO_NS:
                omemo_msg = two_parse_message(et_el, from_bare_jid)
            else:
                omemo_msg = await old_parse_message(et_el, from_bare_jid, self.jid_str, self.manager)

            # Desencriptar
            decrypt_result = await self.manager.decrypt(omemo_msg)
            plaintext_bytes, _device_info = decrypt_result[:2]

            # Establecer confianza automática solo si es necesario (always-trust policy)
            if _device_info.trust_level_name.lower() != 'trusted':
                try:
                    await self.manager.set_trust(
                        _device_info.bare_jid,
                        _device_info.identity_key,
                        "trusted"
                    )
                    debug_print(f"OMEMO: confianza automática establecida para {_device_info.bare_jid}")
                except Exception as e:
                    debug_print(f"OMEMO: Error guardando trust para {_device_info.bare_jid}: {e}")

            # Responder al exchange con un mensaje vacío de ser necesario
            header_node = encrypted_node.getTag('header')
            has_prekey = False
            if header_node is not None:
                keys = []
                if ns == TWOMEMO_NS:
                    for keys_elt in header_node.getTags('keys'):
                        keys.extend(keys_elt.getTags('key'))
                else:
                    keys.extend(header_node.getTags('key'))

                for key_node in keys:
                    if key_node.getAttr('prekey') == 'true' or key_node.getAttr('kex') == 'true':
                        has_prekey = True
                        break

            if has_prekey:
                GLib.idle_add(lambda: self.session.send_text(from_bare_jid, ""))

            return plaintext_bytes.decode('utf-8')

        try:
            return self.worker.run_coroutine(_decrypt_coro(), timeout=20)
        except Exception as e:
            debug_print(f"OMEMO: Error desencriptando mensaje: {e}")
            print(f"[omemo-decrypt] failed from={from_bare_jid} error={e!r}", flush=True)
            return None
