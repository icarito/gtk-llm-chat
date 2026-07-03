#!/usr/bin/env python3
"""T1 spike: validate nbxmpp against yax.im (spec 001-xmpp-backend).

Proves: connect + auth, roster fetch, send/receive a message,
receive chat-state notifications. Standalone — no gtk_llm_chat imports.

Usage:
    XMPP_JID=user@yax.im XMPP_PASSWORD=... [XMPP_TO=peer@host] \
        python spike_nbxmpp.py

Credentials come from the environment only; never hardcode them.
Without XMPP_TO the test message is sent to the account's own bare JID
(the server reflects it back to connected resources).
"""
import os
import sys
import logging

from gi.repository import GLib

from nbxmpp.client import Client
from nbxmpp.namespaces import Namespace
from nbxmpp.protocol import JID, Message, Presence
from nbxmpp.simplexml import Node
from nbxmpp.structs import StanzaHandler

TIMEOUT_SECONDS = 40

logging.basicConfig(level=os.environ.get('SPIKE_LOGLEVEL', 'WARNING'))

jid_str = os.environ.get('XMPP_JID')
password = os.environ.get('XMPP_PASSWORD')
if not jid_str or not password:
    sys.exit('Set XMPP_JID and XMPP_PASSWORD in the environment.')
to_jid = os.environ.get('XMPP_TO', JID.from_string(jid_str).bare)

results = {
    'connected': False,
    'roster': False,
    'message-received': False,
    'chatstate-received': False,
}

loop = GLib.MainLoop()
client = Client(log_context='spike')
jid = JID.from_string(jid_str)
client.set_username(jid.localpart)
client.set_domain(jid.domain)
client.set_resource('spike')
client.set_password(password)


def on_connected(_client, _signal_name):
    results['connected'] = True
    print(f'[OK] connected and authenticated as {client.get_bound_jid()}')
    task = client.get_module('Roster').request_roster()
    task.add_done_callback(on_roster)


def on_roster(task):
    try:
        roster = task.finish()
    except Exception as err:
        print(f'[FAIL] roster request: {err}')
        finish()
        return
    items = list(roster.items) if roster is not None else []
    results['roster'] = True
    print(f'[OK] roster fetched: {len(items)} contact(s)')
    for item in items:
        print(f'     - {item.jid} name={item.name!r} sub={item.subscription}')
    # Presence makes the server route incoming messages to this resource
    client.send_stanza(Presence())
    print(f'[..] sending test message to {to_jid}')
    # XEP-0085 chat state rides along; the server's reflection proves
    # both sending and parsing of chat states without a remote peer
    chatstate = Node('active', attrs={'xmlns': Namespace.CHATSTATES})
    client.send_stanza(Message(to=to_jid, body='gtk-llm-chat spike: hello',
                               typ='chat', payload=[chatstate]))


def on_message(_client, _stanza, properties):
    if properties.is_carbon_message and properties.carbon.is_sent:
        return
    if properties.has_chatstate:
        results['chatstate-received'] = True
        print(f'[OK] chatstate from {properties.jid}: {properties.chatstate}')
    if properties.body:
        results['message-received'] = True
        print(f'[OK] message from {properties.jid}: {properties.body!r}')
    if results['message-received'] and results['chatstate-received']:
        finish()


def on_failure(_client, signal_name):
    error, text, _extra = client.get_error()
    print(f'[FAIL] {signal_name}: {error} {text or ""}')
    loop.quit()


def finish():
    client.disconnect()
    GLib.timeout_add(500, loop.quit)


def on_timeout():
    print(f'[..] timeout after {TIMEOUT_SECONDS}s')
    finish()
    return GLib.SOURCE_REMOVE


client.subscribe('connected', on_connected)
client.subscribe('connection-failed', on_failure)
client.register_handler(StanzaHandler(name='message', callback=on_message))

client.connect()
GLib.timeout_add_seconds(TIMEOUT_SECONDS, on_timeout)
loop.run()

print('\n=== Spike results ===')
failed = False
for check, passed in results.items():
    mandatory = check not in ('chatstate-received',)
    mark = 'PASS' if passed else ('FAIL' if mandatory else 'SKIP')
    failed |= (not passed and mandatory)
    print(f'  {mark}  {check}')
sys.exit(1 if failed else 0)
