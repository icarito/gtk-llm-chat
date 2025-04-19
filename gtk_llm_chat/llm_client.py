import gi
import json
import os
import re
import signal
import sys
import unittest
from unittest.mock import patch, MagicMock
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import GObject, GLib
import llm
import threading
import time
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from db_operations import ChatHistory  # Import ChatHistory

import gettext

_ = gettext.gettext

DEFAULT_CONVERSATION_NAME = lambda: _("New Conversation")
DEBUG = False  # Global debug flag

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

    def __init__(self, config=None, chat_history=None):
        GObject.Object.__init__(self)
        self.config = config or {}
        self.model = None
        self.conversation = None
        self._is_generating_flag = False
        self._stream_thread = None
        self._init_error = None
        self.chat_history = None

        threading.Thread(target=self._load_model, daemon=True).start()

    def _load_model(self):
        try:
            model_id = self.config.get('model') or llm.get_default_model()
            debug_print(_(f"LLMClient: Attempting to load model: {model_id}"))
            self.model = llm.get_model(model_id)
            debug_print(_(f"LLMClient: Using model {self.model.model_id}"))
            self.conversation = self.model.conversation()
            GLib.idle_add(self.emit, 'model-loaded', self.model.model_id)
        except llm.UnknownModelError as e:
            debug_print(_(f"LLMClient: Error - Unknown model: {e}"))
            self._init_error = str(e)
            GLib.idle_add(self.emit, 'error', f"Modelo desconocido: {e}")
        except Exception as e:
            debug_print(_(f"LLMClient: Unexpected error in init: {e}"))
            self._init_error = str(e)
            GLib.idle_add(self.emit, 'error', f"Error inesperado al inicializar: {e}")

    def send_message(self, prompt: str):
        if self._is_generating_flag:
            GLib.idle_add(self.emit, 'error', "Ya se está generando una respuesta.")
            return

        if self._init_error or not self.model:
            GLib.idle_add(self.emit, 'error', f"Error al inicializar el modelo: {self._init_error or 'Modelo no disponible'}")
            return

        self._is_generating_flag = True

        self._stream_thread = threading.Thread(target=self._process_stream, args=(prompt,), daemon=True)
        self._stream_thread.start()

    def _process_stream(self, prompt: str):
        success = False
        full_response = ""
        chat_history = ChatHistory()
        try:
            debug_print(_(f"LLMClient: Sending prompt: {prompt[:50]}..."))
            prompt_args = {}
            if self.config.get('system'):
                prompt_args['system'] = self.config['system']
            if self.config.get('temperature'):
                try:
                    temp_val = float(self.config['temperature'])
                    prompt_args['temperature'] = temp_val
                except ValueError:
                    debug_print(_("LLMClient: Ignoring invalid temperature:"), self.config['temperature'])

            response = self.conversation.prompt(prompt, **prompt_args)

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
                            model_id
                        )
                    except Exception as e:
                        print(_(f"Error al guardar en historial: {e}"))
            chat_history.close()
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
        return self.model.model_id if self.model else None

    def get_conversation_id(self):
        return self.conversation.id if self.conversation else None

    def load_history(self, history_entries):
        if self._init_error or not self.model:
            debug_print(_("LLMClient: Error - Attempting to load history with model initialization error."))
            return
        if not self.conversation:
            debug_print(_("LLMClient: Error - Attempting to load history without initialized conversation."))
            return

        current_model = self.model
        current_conversation = self.conversation

        debug_print(_(f"LLMClient: Loading {len(history_entries)} history entries..."))
        current_conversation.responses.clear()

        last_prompt_obj = None

        for entry in history_entries:
            user_prompt = entry.get('prompt')
            assistant_response = entry.get('response')

            if user_prompt:
                last_prompt_obj = llm.Prompt(user_prompt, current_model)
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

GObject.type_register(LLMClient)
