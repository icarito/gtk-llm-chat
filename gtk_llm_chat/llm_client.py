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
from db_operations import ChatHistory  # Import ChatHistory

import gettext

_ = gettext.gettext

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

    def set_model(self, model_id: str):
        """Sets or changes the LLM model."""
        # If model is already loaded and it's the same, do nothing
        if self.model and self.model.model_id == model_id:
            debug_print(f"LLMClient: Model {model_id} is already loaded.")
            return

        debug_print(f"LLMClient: Request to set model to: {model_id}")
        # Load the new model using the internal method
        # This will overwrite any existing model or load if none exists
        self._load_model_internal(model_id)

    def _load_model_internal(self, model_id=None):
        """Internal method to load a model. Can be called from init or set_model."""
        try:
            # Determine the model_id to load
            if model_id is None:
                # Use config or default if no specific model_id is provided (initial load)
                model_id = self.config.get('model') or llm.get_default_model()

            debug_print(f"LLMClient: Attempting to load model: {model_id}")
            new_model = llm.get_model(model_id)  # Load the potentially new model
            self.model = new_model  # Assign the new model
            debug_print(f"LLMClient: Using model {self.model.model_id}")
            # Create a new conversation object tied to the new model
            # Any existing conversation context is lost when changing models.
            self.conversation = self.model.conversation()
            self._init_error = None  # Clear previous errors if successful
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
            debug_print(f"LLMClient: Sending prompt: {prompt[:50]}...")
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
                response = self.conversation.prompt(
                    prompt,
                    fragments=fragments,
                    system_fragments=system_fragments,
                    **prompt_args
                )
            except Exception as e:
                GLib.idle_add(self.emit, 'error', f"Error al procesar el prompt con fragmentos: {e}")
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
            GLib.idle_add(self.emit, 'error', f"Error durante el streaming: {str(e)}")
        finally:
            try:
                debug_print(_(f"LLMClient: Cleaning up stream task (success={success})."))
                self._is_generating_flag = False
                self._stream_thread = None
                if success:
                    cid = self.config.get('cid')
                    model_id = self.get_model_id()
                    if not cid and self.get_conversation_id():
                        new_cid = self.get_conversation_id()
                        self.config['cid'] = new_cid
                        debug_print(f"Nueva conversación creada con ID: {new_cid}")
                        chat_history.create_conversation_if_not_exists(new_cid, DEFAULT_CONVERSATION_NAME())
                        cid = new_cid
                    if cid and model_id:
                        try:
                            chat_history.add_history_entry(
                                cid,
                                prompt,
                                full_response,
                                model_id,
                                fragments=self.config.get('fragments'),
                                system_fragments=self.config.get('system_fragments')
                            )
                        except Exception as e:
                            debug_print(_(f"Error al guardar en historial: {e}"))
            finally:
                chat_history.close_connection()
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
        self._ensure_model_loaded()
        return self.model.model_id if self.model else None

    def get_conversation_id(self):
        self._ensure_model_loaded()
        return self.conversation.id if self.conversation else None

    def load_history(self, history_entries):
        self._ensure_model_loaded()
        if self._init_error or not self.model:
            debug_print(_("LLMClient: Error - Attempting to load history with model initialization error."))
            return
        if not self.conversation:
            debug_print(_("LLMClient: Error - Attempting to load history without initialized conversation."))
            return
        chat_history = self.chat_history
        try:
            current_model = self.model
            current_conversation = self.conversation

            debug_print(_(f"LLMClient: Loading {len(history_entries)} history entries..."))
            last_prompt_obj = None

            for entry in history_entries:
                user_prompt = entry.get('prompt')
                assistant_response = entry.get('response')

                # Fetch fragments for this history entry
                fragments = []
                system_fragments = []
                try:
                    # Assuming 'entry' has 'id' corresponding to response_id in db
                    response_id = entry.get('id')
                    if response_id:
                        # Fetch fragments from the database
                        fragments = chat_history.get_fragments_for_response(response_id, 'prompt_fragments')
                        system_fragments = chat_history.get_fragments_for_response(response_id, 'system_fragments')

                        resolved_fragments = []
                        resolved_system_fragments = []

                        for fragment in fragments:
                            try:
                                resolved_fragments.append(chat_history.resolve_fragment(fragment))
                            except ValueError as e:
                                debug_print(_(f"LLMClient: Error resolving fragment: {e}"))

                        for fragment in system_fragments:
                            try:
                                resolved_system_fragments.append(chat_history.resolve_fragment(fragment))
                            except ValueError as e:
                                debug_print(_(f"LLMClient: Error resolving system fragment: {e}"))

                    else:
                        debug_print(_("LLMClient: Warning - No response ID found for history entry."))

                except Exception as e:
                    debug_print(_(f"LLMClient: Error fetching fragments for history entry: {e}"))
                    # Handle the error gracefully, e.g., by logging it or displaying a message

                if user_prompt:
                    last_prompt_obj = llm.Prompt(
                        user_prompt,
                        current_model,
                        fragments=resolved_fragments,
                        system_fragments=resolved_system_fragments
                    )
                    resp_user = llm.Response(
                        last_prompt_obj, current_model, stream=False,
                        conversation=current_conversation
                    )
                    resp_user._prompt_json = {'prompt': user_prompt}
                    resp_user._done = True
                    resp_user._chunks = []
                    current_conversation.responses.append(resp_user)

                if assistant_response and last_prompt_obj:
                    resp_assistant = llm.Response(
                        last_prompt_obj, current_model, stream=False,
                        conversation=current_conversation
                    )
                    resp_assistant._prompt_json = {
                        'prompt': last_prompt_obj.prompt
                    }
                    resp_assistant._done = True
                    resp_assistant._chunks = [assistant_response]
                    current_conversation.responses.append(resp_assistant)
                elif assistant_response and not last_prompt_obj:
                    debug_print(_("LLMClient: Warning - Assistant response without "
                                  "previous user prompt in history."))

            debug_print(_("LLMClient: History loaded. Total responses in conversation: "
                          + f"{len(current_conversation.responses)}"))
        finally:
            chat_history.close_connection()


GObject.type_register(LLMClient)
