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

DEFAULT_CONVERSATION_NAME = lambda: _("New Conversation")
DEBUG = False


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
        """Establece el modelo actual y actualiza el proveedor."""
        debug_print(f"LLMClient: Request to set model to: {model_id}")

        # Buscar el modelo en la lista de modelos disponibles
        all_models = llm.get_models()
        self.model = next((model for model in all_models if getattr(model, 'model_id', None) == model_id), None)
        if not self.model:
            debug_print(f"LLMClient: No se pudo encontrar el modelo con ID: {model_id}")
            return False

        # Actualizar el proveedor basado en el atributo needs_key del modelo
        self.provider = getattr(self.model, 'needs_key', None) or "Local/Other"
        debug_print(f"LLMClient: Proveedor actualizado a: {self.provider}")

        # --- INICIO DE LA MODIFICACIÓN ---
        # Reinicializar la conversación para el nuevo modelo.
        # Esto asegura que self.conversation no sea None.
        debug_print(f"LLMClient: Creando nueva instancia de conversación para el modelo {self.model.model_id}")
        self.conversation = self.model.conversation() # Crea una nueva conversación vacía

        # Si se está gestionando un ID de conversación actual (current_cid),
        # cambiar el modelo implica que la conversación actual se considera nueva
        # para el historial. Reseteamos el CID.
        if hasattr(self, 'current_cid'):
            debug_print(f"LLMClient: Reseteando current_cid (era: {self.current_cid}) a None debido al cambio de modelo.")
            self.current_cid = None
        # --- FIN DE LA MODIFICACIÓN ---

        # Emitir la señal model-loaded para que la UI se actualice
        self.emit('model-loaded', model_id)
        debug_print(f"LLMClient: Modelo {model_id} cargado y conversación reinicializada.")
        return True

    def _load_model_internal(self, model_id=None):
        """Internal method to load a model. Can be called from init or set_model."""
        current_cid = self.config.get('cid') # Store current cid
        try:
            # Determine the model_id to load
            if model_id is None:
                # Use config or default if no specific model_id is provided (initial load)
                model_id = self.config.get('model') or llm.get_default_model()

            debug_print(f"LLMClient: Attempting to load model: {model_id} (in _load_model_internal)")
            new_model = llm.get_model(model_id)  # Load the potentially new model
            self.model = new_model  # Assign the new model
            debug_print(f"LLMClient: Using model {self.model.model_id}")
            
            # Siempre crear una nueva conversación
            conversation_recreated_or_model_changed = False
            debug_print(f"LLMClient: Creating new conversation object for model {new_model.model_id} in _load_model_internal.")
            self.conversation = new_model.conversation()
            conversation_recreated_or_model_changed = True
                
            self._init_error = None

            # If model setup was successful and a cid exists (especially for initial load with a persisted session)
            if current_cid and conversation_recreated_or_model_changed:
                debug_print(f"LLMClient: Attempting to reload history for cid '{current_cid}' during model initialization.")
                history_entries = self.chat_history.get_conversation_history(current_cid) # Corrected method name
                if history_entries:
                    self.load_history(history_entries)
                    debug_print(f"LLMClient: Successfully reloaded {len(history_entries)} entries for cid '{current_cid}' (initial load).")
                else:
                    debug_print(f"LLMClient: No history entries found for cid '{current_cid}' to reload (initial load).")
            elif not current_cid and conversation_recreated_or_model_changed:
                 debug_print("LLMClient: New conversation created, no prior cid to reload history from.")

            GLib.idle_add(self.emit, 'model-loaded', self.model.model_id)
        except llm.UnknownModelError as e:
            debug_print(f"LLMClient: Error - Unknown model: {e}")
            self._init_error = str(e)
            # Don't overwrite self.model if loading fails, keep the old one if any
            GLib.idle_add(self.emit, 'error', f"Modelo desconocido: {e}")
        except Exception as e:
            debug_print(f"LLMClient: Unexpected error loading model: {e}")
            self._init_error = str(e)
            # Don't overwrite self.model if loading fails
            GLib.idle_add(self.emit, 'error', f"Error inesperado al cargar modelo: {e}")

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
            
            # SOLUCIÓN UNIVERSAL: Recrear el objeto conversation para todos los modelos
            # Esto asegura que no haya problemas de compatibilidad entre modelos
            debug_print(f"LLMClient: Recreando conversation para modelo {self.model.model_id}")
            self.conversation = self.model.conversation() # Nueva conversación limpia
            filtered_responses = [] # No usaremos las respuestas filtradas
            
            # Mostrar el historial después de filtrar
            if self.conversation.responses:
                valid_responses = []
                for idx, response in enumerate(self.conversation.responses):
                    if idx % 2 == 0:  # Usuario
                        # Verificar que el prompt sea válido
                        if response.prompt and response.prompt.prompt and response.prompt.prompt.strip():
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
        debug_print(_("LLMClient: Cancel request received."))
        self._is_generating_flag = False
        if self._stream_thread and self._stream_thread.is_alive():
            debug_print(_("LLMClient: Terminating active stream thread."))
            self._stream_thread = None
        else:
            debug_print(_("LLMClient: No active stream thread to cancel."))

    def get_model_id(self):
        # self._ensure_model_loaded()
        return self.model.model_id if self.model else llm.get_default_model()

    def get_conversation_id(self):
        self._ensure_model_loaded()
        return self.conversation.id if self.conversation else None

    def load_history(self, history_entries):
        # Permitir cargar historial aunque no haya modelo/conversación inicializada
        chat_history = self.chat_history
        try:
            # Si no hay modelo, usar el de la config o el primero del historial
            if not self.model:
                model_id = self.config.get('model')
                if not model_id and history_entries:
                    for entry in history_entries:
                        if entry.get('model'):
                            model_id = entry['model']
                            break
                if model_id:
                    try:
                        self.model = llm.get_model(model_id)
                    except Exception as e:
                        debug_print(f"LLMClient: Error cargando modelo '{model_id}' para historial: {e}")
                        return 
            
            if not self.model: 
                debug_print("LLMClient: Error - Modelo no disponible para cargar historial.")
                return

            if not self.conversation or self.conversation.model != self.model:
                self.conversation = self.model.conversation()
            
            if not self.conversation: 
                debug_print(_("LLMClient: Error - Conversación no disponible para cargar historial."))
                return

            current_model = self.model
            current_conversation = self.conversation
            
            # Limpiar conversación existente
            current_conversation.responses = []
            debug_print(_(f"LLMClient: Historial limpiado. Cargando {len(history_entries)} entradas..."))
            
            valid_pairs = []  # Lista de pares (user_prompt, assistant_response) válidos
            
            # Primero, recopilamos pares válidos de prompt-response
            for entry in history_entries:
                user_prompt = entry.get('prompt')
                assistant_response = entry.get('response')
                
                # Solo incluir pares donde AMBOS (prompt y response) son válidos
                if (user_prompt and str(user_prompt).strip() and 
                    assistant_response and str(assistant_response).strip()):
                    valid_pairs.append((entry, user_prompt, assistant_response))
                else:
                    debug_print(f"LLMClient: Omitiendo entrada incompleta o inválida (id: {entry.get('id')})")
            
            # Ahora procesamos solo los pares válidos
            for entry, user_prompt, assistant_response in valid_pairs:
                try:
                    # Resolver fragmentos
                    resolved_fragments = []
                    resolved_system_fragments = []
                    response_id = entry.get('id')
                    if response_id:
                        # Obtener y resolver fragmentos
                        fragments_data = chat_history.get_fragments_for_response(response_id, 'prompt_fragments')
                        system_fragments_data = chat_history.get_fragments_for_response(response_id, 'system_fragments')
                        
                        for fragment_spec in fragments_data:
                            try:
                                resolved_fragments.append(chat_history.resolve_fragment(fragment_spec))
                            except ValueError as e:
                                debug_print(f"LLMClient: Error resolviendo fragmento: {e}")
                        
                        for sys_fragment_spec in system_fragments_data:
                            try:
                                resolved_system_fragments.append(chat_history.resolve_fragment(sys_fragment_spec))
                            except ValueError as e:
                                debug_print(f"LLMClient: Error resolviendo fragmento de sistema: {e}")
                
                    # Crear el prompt del usuario
                    last_prompt_obj = llm.Prompt(
                        user_prompt,
                        current_model,
                        fragments=resolved_fragments,
                        system_fragments=resolved_system_fragments
                    )
                    
                    # Crear y añadir la respuesta del usuario
                    resp_user = llm.Response(
                        last_prompt_obj, current_model, stream=False,
                        conversation=current_conversation
                    )
                    resp_user._prompt_json = {'prompt': user_prompt}
                    resp_user._done = True
                    resp_user._chunks = []
                    current_conversation.responses.append(resp_user)
                    
                    # Crear y añadir la respuesta del asistente
                    resp_assistant = llm.Response(
                        last_prompt_obj, current_model, stream=False,
                        conversation=current_conversation
                    )
                    resp_assistant._done = True
                    resp_assistant._chunks = [str(assistant_response).strip()]  # Asegurar que no hay espacios innecesarios
                    current_conversation.responses.append(resp_assistant)
                    
                except Exception as e:
                    debug_print(f"LLMClient: Error procesando entrada (id: {entry.get('id')}): {e}")
                    import traceback
                    debug_print(traceback.format_exc())
            
            debug_print(_("LLMClient: Historial cargado. Total de respuestas en conversación: "
                         + f"{len(current_conversation.responses)}"))
                
        finally:
            chat_history.close_connection()

    def set_conversation(self, conversation_id: str):
        """
        Sets the active conversation ID and loads the associated model and history.
        """
        if not conversation_id:
            debug_print("LLMClient: Error - No conversation ID provided")
            return False
        
        # First, get the conversation details including the model
        conv_details = self.chat_history.get_conversation(conversation_id)
        if not conv_details:
            debug_print(f"LLMClient: Error - Conversation {conversation_id} not found")
            return False
        
        # Get the model associated with this conversation
        model_id = conv_details.get('model')
        
        # Store the conversation ID in the config
        self.config['cid'] = conversation_id
        
        # Load the appropriate model if it differs from current model
        if model_id and (not self.model or self.model.model_id != model_id):
            debug_print(f"LLMClient: Changing model to {model_id} as per conversation {conversation_id}")
            success = self.set_model(model_id)
            if not success:
                debug_print(f"LLMClient: Failed to set model {model_id} for conversation {conversation_id}")
                # Continue anyway, will try to use default or current model
        
        # Load the conversation history
        history_entries = self.chat_history.get_conversation_history(conversation_id)
        if history_entries:
            self.load_history(history_entries)
            debug_print(f"LLMClient: Loaded {len(history_entries)} entries for conversation {conversation_id}")
            return True
        else:
            debug_print(f"LLMClient: No history found for conversation {conversation_id}")
            # We still consider this a success even if there's no history
            return True

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
GObject.type_register(LLMClient)
