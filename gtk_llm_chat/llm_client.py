import gi
import json
import os
import re
import signal
import sys
import unittest
from typing import Optional
from unittest.mock import patch, MagicMock
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import GObject, GLib
import llm
import threading
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from db_operations import ChatHistory

from chat_application import _
from .utils import debug_print, get_default_model, get_api_key_for_model, list_available_models, get_model_config

DEFAULT_CONVERSATION_NAME = lambda: _("New Conversation")
DEBUG = os.environ.get('DEBUG') or False


def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

class LLMClient(GObject.Object):
    __gsignals__ = {
        'response': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'error': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'finished': (GObject.SignalFlags.RUN_LAST, None, (bool,)),
        'model-loaded': (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    def __init__(self, config=None, chat_history=None, fragments_path: Optional[str] = None):
        GObject.Object.__init__(self)
        self.config = config or {}
        self.model = None
        self.conversation = None
        self._is_generating_flag = False
        self._stream_thread = None
        self._init_error = None
        self.chat_history = chat_history or ChatHistory(fragments_path=fragments_path)

    def _ensure_model_loaded(self):
        """Ensures the model is loaded, loading it if necessary."""
        if self.model is None and self._init_error is None:
            debug_print("LLMClient: Ensuring model is loaded (was deferred).")
            self._load_model_internal() # Load default or configured model

    def send_message(self, prompt: str):
        self._ensure_model_loaded() # Ensure model is loaded before sending
        if self._is_generating_flag:
            GLib.idle_add(self.emit, 'error', "Ya se está generando una respuesta.")
            return

        if self._init_error or not self.model:
            GLib.idle_add(self.emit, 'error',
                          f"Error al inicializar el modelo: {self._init_error or 'Modelo no disponible'}")
            return

        self._is_generating_flag = True

        self._stream_thread = threading.Thread(target=self._process_stream, args=(prompt,), daemon=True)
        self._stream_thread.start()

    def set_model(self, model_id):
        debug_print(f"LLMClient.set_model: Solicitud para cambiar al modelo: {model_id}")
        if self.model and self.model.id == model_id:
            debug_print(f"LLMClient.set_model: El modelo {model_id} ya está activo. No se requiere cambio.")
            # Aunque el modelo sea el mismo, si no hay CID, es una nueva conversación.
            # Si hay CID, load_history se encargará de cargar los mensajes correctos.
            if not self.config.get('cid'):
                debug_print("LLMClient.set_model: No hay CID, asegurando nueva conversación para el modelo actual.")
                self.conversation = self.model.conversation() # Nueva conversación para el mismo modelo
                self.load_history() # Esto limpiará las respuestas si no hay CID
            else:
                # Si hay un CID, y el modelo es el mismo, _load_model_internal ya se habrá encargado
                # o set_conversation lo hará. load_history se llamará después de que el modelo esté confirmado.
                debug_print(f"LLMClient.set_model: Modelo {model_id} ya activo y CID {self.config.get('cid')} presente. Se espera que set_conversation o la carga inicial manejen el historial.")
            self.emit('model-loaded', model_id) # Emitir incluso si es el mismo, para que la UI reaccione si es necesario
            return

        previous_model_id = self.model.id if self.model else "ninguno"
        loaded_model_id = self._load_model_internal(model_id_override=model_id)

        if loaded_model_id:
            debug_print(f"LLMClient.set_model: Modelo cambiado de '{previous_model_id}' a '{loaded_model_id}'.")
            self.config['model'] = loaded_model_id # Asegurar que config esté actualizado
            
            # Si hay un CID, actualizar el modelo en la base de datos para esta conversación
            current_cid = self.config.get('cid')
            if current_cid:
                try:
                    self.chat_history.update_conversation_model(current_cid, loaded_model_id)
                    debug_print(f"LLMClient.set_model: Modelo actualizado a '{loaded_model_id}' en BD para CID {current_cid}.")
                except Exception as e:
                    debug_print(f"LLMClient.set_model: Error al actualizar modelo en BD para CID {current_cid}: {e}")
            
            self.load_history() # Cargar historial (o limpiar si no hay CID)
            self.emit('model-loaded', loaded_model_id)
        else:
            debug_print(f"LLMClient.set_model: No se pudo cargar el nuevo modelo {model_id}. Se revirtió o falló la carga.")
            # La señal de error ya debería haber sido emitida por _load_model_internal
            # Si self.model es None, la UI debería reflejar un estado de error.
            # Si se revirtió al modelo anterior, emitir model-loaded para ese modelo.
            if self.model:
                self.emit('model-loaded', self.model.id)
            else:
                # No hay modelo cargado, podría ser útil una señal específica o la UI debe manejar 'error'
                pass 

    def _load_model_internal(self, model_id_override=None):
        """Carga el modelo. Prioriza el override, luego el modelo de la conversación actual (CID),
           luego el modelo de configuración, y finalmente el predeterminado."""
        target_model_id = None
        source_of_model_id = "desconocido"

        if model_id_override:
            target_model_id = model_id_override
            source_of_model_id = "override"
        elif self.config.get('cid'):
            try:
                conversation_details = self.chat_history.get_conversation(self.config.get('cid'))
                if conversation_details and conversation_details.get('model_id'):
                    target_model_id = conversation_details['model_id']
                    source_of_model_id = f"CID {self.config.get('cid')}"
                else:
                    debug_print(f"CID {self.config.get('cid')} presente, pero no se encontró model_id en la BD o la conversación no existe.")
            except Exception as e:
                debug_print(f"Error al obtener model_id de la BD para CID {self.config.get('cid')}: {e}")
        
        if not target_model_id and self.config.get('model'):
            target_model_id = self.config.get('model')
            source_of_model_id = "configuración"
        
        if not target_model_id:
            target_model_id = get_default_model()
            source_of_model_id = "predeterminado"

        debug_print(f"_load_model_internal: Intentando cargar el modelo '{target_model_id}' (fuente: {source_of_model_id}). Modelo actual: {self.model.id if self.model else 'Ninguno'}")

        if self.model and self.model.id == target_model_id:
            debug_print(f"_load_model_internal: El modelo '{target_model_id}' ya está cargado.")
            # Asegurar que self.conversation esté configurado para este modelo si no lo está
            if not self.conversation or self.conversation.model.id != target_model_id:
                debug_print(f"_load_model_internal: Creando nuevo objeto llm.Conversation para el modelo {target_model_id} ya cargado.")
                self.conversation = self.model.conversation()
            return target_model_id # Devuelve el ID del modelo cargado/confirmado

        try:
            model_instance = llm.get_model(target_model_id)
            if not model_instance:
                raise ValueError(f"No se pudo obtener la instancia del modelo para {target_model_id}")
            self.model = model_instance
            self.conversation = self.model.conversation() # Crear nueva conversación para el modelo
            self.config['model'] = self.model.id # Actualizar config con el modelo realmente cargado
            debug_print(f"_load_model_internal: Modelo '{self.model.id}' cargado y nueva conversación creada.")
            return self.model.id
        except Exception as e:
            debug_print(f"Error crítico al cargar el modelo '{target_model_id}': {e}", exc_info=True)
            # Intentar cargar el modelo predeterminado como último recurso si el fallido no era el predeterminado
            default_model_id = get_default_model()
            if target_model_id != default_model_id:
                debug_print(f"_load_model_internal: Intentando recurrir al modelo predeterminado '{default_model_id}'.")
                try:
                    self.model = llm.get_model(default_model_id)
                    self.conversation = self.model.conversation()
                    self.config['model'] = self.model.id
                    debug_print(f"_load_model_internal: Modelo predeterminado '{self.model.id}' cargado como fallback.")
                    return self.model.id
                except Exception as e_fallback:
                    debug_print(f"Error crítico al cargar el modelo predeterminado '{default_model_id}' como fallback: {e_fallback}", exc_info=True)
                    self.model = None
                    self.conversation = None
                    self.emit('error', f"No se pudo cargar el modelo: {target_model_id} ni el predeterminado.")
                    return None # No se pudo cargar ningún modelo
            else:
                self.model = None
                self.conversation = None
                self.emit('error', f"No se pudo cargar el modelo predeterminado: {target_model_id}.")
                return None # No se pudo cargar el modelo predeterminado

    def _process_stream(self, prompt: str):
        success = False
        full_response = ""
        chat_history = self.chat_history
        try:
            debug_print(f"LLMClient: Sending prompt: '{prompt[:50]}' (len={len(prompt)})")

            # Depurar el contenido de self.conversation.responses antes de enviar el prompt
            debug_print("LLMClient: Current conversation history before sending prompt:")
            
            # ENFOQUE MÁS ESTRICTO: Reconstruir las conversaciones por turnos
            # Solo mantener prompts válidos de usuario y respuestas válidas de asistente
            filtered_responses = []
            is_user_turn = True  # Alternamos entre turno de usuario y asistente
            
            for response in self.conversation.responses:
                if is_user_turn:
                    # Si es turno de usuario, verificar que tenga prompt válido
                    if response.prompt and response.prompt.prompt and response.prompt.prompt.strip():
                        filtered_responses.append(response)
                        is_user_turn = False  # Siguiente sería turno del asistente
                else:
                    # Si es turno del asistente, verificar que tenga chunks válidos
                    if hasattr(response, '_chunks') and response._chunks and any(chunk.strip() for chunk in response._chunks):
                        filtered_responses.append(response)
                        is_user_turn = True  # Siguiente sería turno del usuario
                    else:
                        # Si el asistente tiene chunks vacíos, descartamos y volvemos a turno de usuario
                        # También eliminamos el prompt del usuario anterior para mantener la alternancia
                        if filtered_responses:
                            filtered_responses.pop()  # Quitar el último prompt de usuario
                        is_user_turn = True  # Volver a turno de usuario
            
            # Revisar si el último elemento es un turno de usuario sin respuesta
            if filtered_responses and is_user_turn == False:
                # Último elemento es un prompt de usuario sin respuesta, lo eliminamos
                filtered_responses.pop()
            
            # Mostrar el historial después de filtrar (solo para depuración)
            if self.conversation.responses:
                valid_responses = []
                for idx, response in enumerate(self.conversation.responses):
                    if idx % 2 == 0:  # Usuario
                        # Verificar que el prompt sea válido
                        user_text = response.prompt.prompt
                        # Buscar la siguiente respuesta (asistente)
                        if idx + 1 < len(self.conversation.responses):
                            assistant_response = self.conversation.responses[idx + 1]
                            if hasattr(assistant_response, '_chunks') and assistant_response._chunks and any(chunk.strip() for chunk in assistant_response._chunks):
                                # Par válido: usuario con prompt y asistente con chunks
                                valid_responses.append(response)
                                valid_responses.append(assistant_response)
                                debug_print(f"  [{len(valid_responses)-2}] User: '{user_text[:50]}'")
                                assistant_text = "".join(assistant_response._chunks)
                                debug_print(f"  [{len(valid_responses)-1}] Assistant: '{assistant_text[:50]}'")
                
                # Reemplazar con respuestas filtradas
                if len(valid_responses) != len(self.conversation.responses):
                    debug_print(f"LLMClient: Se filtraron {len(self.conversation.responses) - len(valid_responses)} respuestas inválidas")
                    self.conversation.responses = valid_responses
            else:
                debug_print("  [No conversation history available]")

            if prompt is None or str(prompt).strip() == "":
                debug_print("LLMClient: ERROR: prompt vacío o None detectado en _process_stream. Abortando.")
                GLib.idle_add(self.emit, 'error', "No se puede enviar un prompt vacío al modelo.")
                GLib.idle_add(self.emit, 'finished', False)
                return
            prompt_args = {}
            if self.config.get('system'):
                prompt_args['system'] = self.config['system']
            if self.config.get('temperature'):
                try:
                    temp_val = float(self.config['temperature'])
                    prompt_args['temperature'] = temp_val
                except ValueError:
                    debug_print(_("LLMClient: Ignoring invalid temperature:"), self.config['temperature'])

            # --- NEW FRAGMENT HANDLING ---
            fragments = []
            system_fragments = []

            if self.config.get('fragments'):
                try:
                    fragments = [chat_history.resolve_fragment(f) for f in self.config['fragments']]
                except ValueError as e:
                    GLib.idle_add(self.emit, 'error', str(e))
                    return  # Abort processing

            if self.config.get('system_fragments'):
                try:
                    system_fragments = [chat_history.resolve_fragment(sf) for sf in self.config['system_fragments']]
                except ValueError as e:
                    GLib.idle_add(self.emit, 'error', str(e))
                    return  # Abort processing

            try:
                if len(fragments):
                    prompt_args['fragments'] = fragments
                if len(system_fragments):
                    prompt_args['system_fragments'] = system_fragments
                response = self.conversation.prompt(
                    prompt,
                    **prompt_args
                )
            except Exception as e:
                # Mensaje de error simplificado
                debug_print(f"LLMClient: Error en conversation.prompt: {e}")
                GLib.idle_add(self.emit, 'error', f"Error al procesar el prompt: {e}")
                return

            debug_print(_("LLMClient: Starting stream processing..."))
            for chunk in response:
                if not self._is_generating_flag:
                    debug_print(_("LLMClient: Stream processing cancelled externally."))
                    break
                if chunk:
                    full_response += chunk
                    GLib.idle_add(self.emit, 'response', chunk)
            success = True
            debug_print(_("LLMClient: Stream finished normally."))

        except Exception as e:
            debug_print(_(f"LLMClient: Error during streaming: {e}"))
            import traceback
            debug_print(traceback.format_exc())
            GLib.idle_add(self.emit, 'error', f"Error durante el streaming: {str(e)}")
        finally:
            try:
                debug_print(_(f"LLMClient: Cleaning up stream task (success={success})."))
                self._is_generating_flag = False
                self._stream_thread = None
                # Solo guardar en el historial si fue exitoso Y HUBO RESPUESTA DEL ASISTENTE
                if success and full_response and full_response.strip(): 
                    cid = self.config.get('cid')
                    model_id = self.get_model_id()
                    
                    # Asegurarse de que cid se cree si no existe (para nuevas conversaciones)
                    if not cid and self.conversation and self.conversation.id:
                        cid = self.conversation.id
                        self.config['cid'] = cid # Guardar el nuevo cid en la config
                        debug_print(f"LLMClient: New conversation detected, cid set to: {cid}")
                        # Crear la conversación en la BD si es la primera vez que se guarda algo para ella
                        self.chat_history.create_conversation_if_not_exists(cid, DEFAULT_CONVERSATION_NAME(), model_id)

                    if cid and model_id: 
                        try:
                            self.chat_history.add_history_entry( 
                                cid,
                                prompt,
                                full_response, 
                                model_id,
                                fragments=self.config.get('fragments'),
                                system_fragments=self.config.get('system_fragments')
                            )
                            debug_print(f"LLMClient: History entry added for cid={cid} with assistant response.")
                        except Exception as e:
                            debug_print(_(f"Error al guardar en historial: {e}"))
                    else:
                        debug_print("LLMClient: Not saving history because cid or model_id is missing.")
                elif success: 
                    debug_print("LLMClient: Stream was successful but assistant response was empty. Not saving to history.")
                else: 
                    debug_print("LLMClient: Stream was not successful. Not saving to history.")
            finally:
                # self.chat_history.close_connection() # No cerrar aquí si es un atributo de instancia
                pass 
            GLib.idle_add(self.emit, 'finished', success)

    def cancel(self):
        """No-op cancel (el stream no se cancela)."""
        pass

    def get_model_id(self):
        # self._ensure_model_loaded()
        return self.model.model_id if self.model else llm.get_default_model()

    def get_conversation_id(self):
        self._ensure_model_loaded()
        return self.conversation.id if self.conversation else None

    def load_history(self, history_entries):
        """
        Carga entradas de historial en el objeto self.conversation actual.
        Asume que self.model y self.conversation ya están correctamente inicializados
        para el contexto/modelo deseado.
        """
        if not self.model or not self.conversation:
            debug_print("LLMClient: load_history - Error: Modelo o conversación no inicializados.")
            # Podríamos emitir un error o intentar una carga de emergencia, pero es mejor que la lógica previa lo asegure.
            # self._ensure_model_loaded() # Podría ser una opción, pero puede tener efectos secundarios.
            # if not self.model or not self.conversation: # Comprobar de nuevo
            #     GLib.idle_add(self.emit, 'error', "No se puede cargar el historial: modelo no listo.")
            #     return
            # Considerar si es mejor fallar ruidosamente si se llega aquí en un estado inesperado.
            # Por ahora, solo advertir y retornar si no hay modelo/conversación.
            GLib.idle_add(self.emit, 'error', "No se puede cargar el historial: modelo o conversación no están listos.")
            return

        debug_print(f"LLMClient: load_history - Cargando {len(history_entries)} entradas en la conversación del modelo {self.model.model_id}")

        # Limpiar respuestas previas del objeto de conversación actual
        self.conversation.responses = []

        # Cargar pares válidos de prompt/respuesta
        for entry in history_entries:
            user_prompt = entry.get('prompt')
            assistant_response = entry.get('response')

            # Asegurarse de que tanto el prompt como la respuesta existan y no sean solo espacios.
            if not (user_prompt and str(user_prompt).strip() and assistant_response and str(assistant_response).strip()):
                debug_print(f"LLMClient: load_history - Saltando entrada de historial inválida o incompleta: P='{user_prompt}', R='{assistant_response}'")
                continue

            # Crear objetos Prompt y Response de la biblioteca llm
            # El objeto Prompt se crea con el modelo actual (self.model)
            try:
                prompt_obj = llm.Prompt(user_prompt, model=self.model)

                # Simular la estructura que llm.py usa para los prompts de usuario
                user_resp_obj = llm.Response(prompt_obj, model=self.model, stream=False, conversation=self.conversation)
                user_resp_obj._prompt_json = {'prompt': user_prompt} # Simular cómo llm podría almacenar esto
                user_resp_obj.text = "" # El prompt del usuario no tiene "texto de respuesta"
                user_resp_obj._done = True 
                self.conversation.responses.append(user_resp_obj)
                
                # Simular la estructura para las respuestas del asistente
                assistant_resp_obj = llm.Response(prompt_obj, model=self.model, stream=False, conversation=self.conversation)
                assistant_resp_obj.text = assistant_response # El texto de la respuesta del asistente
                # Aquí podríamos intentar reconstruir _response_json si lo tuviéramos, pero text es lo principal.
                assistant_resp_obj._done = True
                self.conversation.responses.append(assistant_resp_obj)

            except Exception as e:
                debug_print(f"LLMClient: load_history - Error al procesar entrada de historial: P='{user_prompt}', R='{assistant_response}'. Error: {e}")
                # Continuar con las siguientes entradas si una falla

        debug_print(f"LLMClient: load_history - Historial cargado. Total de respuestas en self.conversation: {len(self.conversation.responses)}")

    def set_conversation(self, cid):
        debug_print(f"LLMClient.set_conversation: Cambiando a CID: {cid}")
        if not cid:
            debug_print("LLMClient.set_conversation: CID es None. Iniciando nueva conversación.")
            self.config['cid'] = None
            # _load_model_internal sin override usará config['model'] o el predeterminado.
            # Esto efectivamente inicia una nueva conversación con el modelo actual o predeterminado.
            loaded_model_id = self._load_model_internal() 
            if loaded_model_id:
                self.load_history() # Limpiará el historial para la nueva conversación
                self.emit('model-loaded', loaded_model_id)
            else:
                debug_print("LLMClient.set_conversation: No se pudo cargar el modelo para nueva conversación.")
            return

        try:
            conversation_details = self.chat_history.get_conversation(cid)
            if not conversation_details:
                debug_print(f"LLMClient.set_conversation: No se encontró la conversación con CID {cid}. No se puede cambiar.")
                self.emit('error', f"Conversación {cid} no encontrada.")
                return

            self.config['cid'] = cid
            model_id_for_cid = conversation_details.get('model_id')
            
            debug_print(f"LLMClient.set_conversation: CID {cid} usa el modelo '{model_id_for_cid if model_id_for_cid else 'no especificado en BD'}'.")

            # _load_model_internal priorizará el modelo del CID si está disponible.
            # Si model_id_for_cid es None, _load_model_internal usará config['model'] o el predeterminado,
            # y luego actualizaremos la BD si es necesario.
            loaded_model_id = self._load_model_internal() # Esto ahora debería recoger el modelo del CID

            if not loaded_model_id:
                debug_print(f"LLMClient.set_conversation: No se pudo cargar el modelo para CID {cid}. Error emitido por _load_model_internal.")
                return

            # Si la conversación no tenía un model_id en la BD, o si _load_model_internal
            # terminó usando un modelo diferente (ej. el predeterminado porque el del CID falló),
            # actualizamos la BD con el modelo que *realmente* se cargó.
            if model_id_for_cid != loaded_model_id:
                debug_print(f"LLMClient.set_conversation: Actualizando modelo en BD para CID {cid} de '{model_id_for_cid}' a '{loaded_model_id}'.")
                try:
                    self.chat_history.update_conversation_model(cid, loaded_model_id)
                except Exception as e:
                    debug_print(f"LLMClient.set_conversation: Error al actualizar modelo en BD para CID {cid}: {e}")
            
            # Actualizar self.config['model'] para que coincida con el modelo cargado para este CID
            self.config['model'] = loaded_model_id

            self.load_history() # Cargar el historial de la conversación seleccionada
            self.emit('model-loaded', loaded_model_id) # Notificar a la UI que el modelo (y la conversación) están listos

        except Exception as e:
            debug_print(f"LLMClient.set_conversation: Error al establecer conversación {cid}: {e}", exc_info=True)
            self.emit('error', f"Error al cambiar a conversación {cid}.")

    def get_provider_for_model(self, model_id):
        """Obtiene el proveedor asociado a un modelo dado su ID."""
        if not model_id:
            debug_print("get_provider_for_model: model_id es None")
            return "Unknown Provider"

        # Obtener todos los modelos disponibles
        try:
            all_models = llm.get_models()

            # Buscar el modelo por ID y devolver su proveedor
            for model in all_models:
                if getattr(model, 'model_id', None) == model_id:
                    provider = getattr(model, 'needs_key', None) or "Local/Other"
                    debug_print(f"Proveedor encontrado: {provider} para modelo {model_id}")
                    self.provider = provider
                    return provider
        except Exception as e:
            debug_print(f"Error al obtener modelos: {e}")

        debug_print(f"No se encontró proveedor para el modelo: {model_id}")
        return "Unknown Provider"  # Si no se encuentra el modelo
        
    def get_all_models(self):
        """Obtiene todos los modelos disponibles. Utilizado para compartir estado entre componentes."""
        try:
            from llm.plugins import load_plugins
            # Asegurar que los plugins estén cargados, pero sin forzar recarga
            if not hasattr(llm.plugins, '_loaded') or not llm.plugins._loaded:
                load_plugins()
                debug_print("LLMClient: Plugins cargados en get_all_models")
            
            return llm.get_models()
        except Exception as e:
            debug_print(f"LLMClient: Error obteniendo modelos: {e}")
            return []
GObject.type_register(LLMClient)
