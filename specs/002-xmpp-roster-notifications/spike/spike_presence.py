#!/usr/bin/env python3
"""Spike for spec 002: validate presence + subscription APIs in nbxmpp.

Resolves the open technical questions before writing tasks.md:
- How incoming <presence> stanzas surface (available/unavailable + from JID)
- How subscription requests (type=subscribe) surface
- How to accept/deny a subscription (BasePresence.subscribed/unsubscribed)

Usage:
    XMPP_JID=user@yax.im XMPP_PASSWORD=... python spike_presence.py

Sends a self-directed presence and a self subscription request so the
server reflects them back — no second account needed to see the shapes.
Credentials from the environment only.
"""
import os
import sys

from gi.repository import GLib

from nbxmpp.client import Client
from nbxmpp.protocol import JID, Presence
from nbxmpp.structs import StanzaHandler

TIMEOUT_SECONDS = 30

jid_str = os.environ.get('XMPP_JID')
password = os.environ.get('XMPP_PASSWORD')
if not jid_str or not password:
    sys.exit('Set XMPP_JID and XMPP_PASSWORD in the environment.')

observations = []

loop = GLib.MainLoop()
client = Client(log_context='spike-presence')
jid = JID.from_string(jid_str)
client.set_username(jid.localpart)
client.set_domain(jid.domain)
client.set_resource('spike-presence')
client.set_password(password)


def on_presence(_client, _stanza, properties):
    # What does an incoming presence look like?
    ptype = properties.type
    from_jid = properties.jid
    show = properties.show
    observations.append(
        f"presence: type={ptype} show={show} from={from_jid} "
        f"available={properties.type.is_available if ptype else '?'}")
    # A subscription request arrives as type=subscribe
    if ptype is not None and ptype.value == 'subscribe':
        observations.append(f"  -> SUBSCRIPTION REQUEST from {from_jid}")
        # Accept it via BasePresence.subscribed
        client.get_module('BasePresence').subscribed(from_jid)
        observations.append(f"  -> sent 'subscribed' (accept) to {from_jid}")


def on_connected(_client, _signal_name):
    observations.append(f"connected as {client.get_bound_jid()}")
    # Announce our own presence
    client.send_stanza(Presence())
    # Send a self-directed available presence (server reflects to our resources)
    client.send_stanza(Presence(to=jid.bare, show='away', status='spike test'))
    # Send a self subscription request to see the request shape
    client.get_module('BasePresence').subscribe(jid.bare)
    GLib.timeout_add_seconds(6, finish)


def on_failure(_client, signal_name):
    error, text, _extra = client.get_error()
    observations.append(f"FAIL {signal_name}: {error} {text or ''}")
    loop.quit()


def finish():
    client.disconnect()
    GLib.timeout_add(500, loop.quit)
    return GLib.SOURCE_REMOVE


client.subscribe('connected', on_connected)
client.subscribe('connection-failed', on_failure)
client.register_handler(StanzaHandler(name='presence', callback=on_presence))

client.connect()
GLib.timeout_add_seconds(TIMEOUT_SECONDS, lambda: (finish(), loop.quit()))
loop.run()

print("=== Presence/subscription spike observations ===")
for obs in observations:
    print(f"  {obs}")
saw_presence = any('presence:' in o for o in observations)
sys.exit(0 if saw_presence else 1)
