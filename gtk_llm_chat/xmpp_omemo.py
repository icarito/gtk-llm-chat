"""
xmpp_omemo.py - Integración OMEMO (XEP-0384) para XmppSession.

Implementa el almacenamiento basado en archivos JSON y la sincronización PubSub
con nbxmpp para OMEMO (tanto legacy eu.siacs.conversations.axolotl como urn:xmpp:omemo:2).
"""
import os
import json
import socket
import asyncio
import threading
import traceback
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
from omemo.types import DeviceList

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

    def main_thread_callback():
        try:
            name = getattr(func, '__name__', repr(func))
            debug_print(f"[omemo-glib] call {name}")
            print(f"[omemo-glib] call {name}", flush=True)
            task = func(*args, **kwargs)
            if task is None:
                loop.call_soon_threadsafe(future.set_result, None)
                return

            def on_done(t):
                try:
                    res = t.finish()
                    debug_print(f"[omemo-glib] done {name}")
                    print(f"[omemo-glib] done {name}", flush=True)
                    loop.call_soon_threadsafe(future.set_result, res)
                except Exception as e:
                    loop.call_soon_threadsafe(future.set_exception, e)

            task.add_done_callback(on_done, weak=False)
        except Exception as e:
            loop.call_soon_threadsafe(future.set_exception, e)

    GLib.idle_add(main_thread_callback)
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
            return f"{TWOMEMO_NS}:bundles:{device_id}"
        return f"{LEGACY_NS}.bundles:{device_id}"

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
        await run_on_main_thread(pubsub.publish, node_name, nb_node, force_node_options=True)

    @staticmethod
    async def _download_bundle(namespace: str, bare_jid: str, device_id: int):
        debug_print(f"OMEMO: descargando bundle para {bare_jid} dispositivo {device_id} ({namespace})")
        pubsub = XmppOMEMOSessionManager._get_pubsub_module()
        node_name = XmppOMEMOSessionManager._get_bundle_node(namespace, device_id)

        try:
            items = await run_on_main_thread(
                pubsub.request_items, node_name, max_items=1, jid=JID.from_string(bare_jid)
            )
        except Exception as e:
            debug_print(f"OMEMO: error al descargar bundle {node_name} de {bare_jid}: {e}")
            raise BundleNotFound(f"Bundle {node_name} de {bare_jid} no encontrado: {e}")

        for item in items or []:
            bundle_tag = "bundle"
            bundle_el = item.getTag(bundle_tag, namespace=namespace)
            if bundle_el is None:
                continue
            et_el = node_to_etree(bundle_el)
            if namespace == TWOMEMO_NS:
                return two_parse_bundle(et_el, bare_jid, device_id)
            else:
                return old_parse_bundle(et_el, bare_jid, device_id)

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
        await run_on_main_thread(pubsub.publish, node_name, nb_node, force_node_options=True)

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
            # Salir de modo sincronización de historial inicial
            await manager.after_history_sync()
            debug_print(f"[omemo-init] history-sync-done jid={self.jid_str}")
            return manager

        try:
            self.manager = self.worker.run_coroutine(_init_coro(), timeout=60)
            debug_print(f"[omemo-init] ready jid={self.jid_str} label={label}")
        except Exception as e:
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

        async def _encrypt_coro():
            recipients = frozenset({to_bare_jid})
            try:
                plaintext_bytes = text.encode('utf-8')
                plaintext = {LEGACY_NS: plaintext_bytes}
                if twomemo_available:
                    plaintext[TWOMEMO_NS] = plaintext_bytes
                encrypted_messages, errors = await self.manager.encrypt(
                    recipients, plaintext)
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
            return (nodes[0] if len(nodes) == 1 else nodes), text

        try:
            return self.worker.run_coroutine(_encrypt_coro(), timeout=30)
        except Exception as e:
            debug_print(f"OMEMO: Error encriptando mensaje: {e}")
            return None, text

    def decrypt_msg(self, from_bare_jid: str, encrypted_node: Node) -> str | None:
        """Desencripta un nodo encriptado entrante."""
        if self.manager is None:
            return None

        # Convertir a ElementTree
        et_el = node_to_etree(encrypted_node)
        ns = encrypted_node.getNamespace()

        async def _decrypt_coro():
            if ns == TWOMEMO_NS:
                omemo_msg = two_parse_message(et_el, from_bare_jid)
            else:
                omemo_msg = await old_parse_message(et_el, from_bare_jid, self.jid_str, self.manager)

            # Desencriptar
            plaintext_bytes, _device_info = await self.manager.decrypt(omemo_msg)

            # Establecer confianza automática solo si es necesario (always-trust policy)
            if _device_info.trust_level_name != 'TRUSTED':
                try:
                    await self.manager.set_trust(
                        _device_info.bare_jid,
                        _device_info.identity_key,
                        TrustLevel.TRUSTED
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
            return self.worker.run_coroutine(_decrypt_coro())
        except Exception as e:
            debug_print(f"OMEMO: Error desencriptando mensaje: {e}")
            return None
