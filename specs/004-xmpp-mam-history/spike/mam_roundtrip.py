#!/usr/bin/env python3
"""Spike T1 (spec 004): raw MAM round-trip against a real server.

Not wired into the app. Confirms:
  - nbxmpp's MAM.make_query(...) round-trips against a real XMPP server.
  - Archived results arrive as ordinary 'message' stanzas via the message
    StanzaHandler, with properties.is_mam_message True and
    properties.mam a MAMData(id, query_id, archive, namespace, timestamp).
  - properties.mam.query_id correlates results back to the queryid passed
    to make_query.
  - The query's own completion (done-callback -> task.finish() ->
    MAMQueryData(jid, complete, rsm)) fires once, after the results.

Usage:
  XMPP_JID=icarito-test@yax.im XMPP_PASSWORD=*** \
      .venv/bin/python specs/004-xmpp-mam-history/spike/mam_roundtrip.py [with_jid]

with_jid defaults to icarito@yax.im (the mutually-subscribed contact used
in prior spec 001/002 testing).
"""
import os
import sys
import uuid

import gi
gi.require_version('Gtk', '4.0')  # nbxmpp doesn't need this, but keep GLib happy re: imports
from gi.repository import GLib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from nbxmpp.client import Client as NbxmppClient
from nbxmpp.protocol import JID
from nbxmpp.structs import StanzaHandler


def main():
    jid = os.environ.get('XMPP_JID')
    password = os.environ.get('XMPP_PASSWORD')
    if not jid or not password:
        print("Set XMPP_JID and XMPP_PASSWORD env vars.", file=sys.stderr)
        sys.exit(1)
    with_jid = sys.argv[1] if len(sys.argv) > 1 else 'icarito@yax.im'

    my_jid = JID.from_string(jid)
    loop = GLib.MainLoop()
    received = []       # (query_id, mam_id, timestamp, body, from_jid)
    state = {'query_id': None, 'query_done': False, 'query_result': None}

    def on_message(_client, _stanza, properties):
        if not getattr(properties, 'is_mam_message', False):
            return
        mam = properties.mam
        body = properties.body
        print(f"[message] mam_id={mam.id} query_id={mam.query_id} "
              f"ts={mam.timestamp} from={properties.jid} body={body!r}")
        received.append((mam.query_id, mam.id, mam.timestamp, body, str(properties.jid)))

    def on_query_done(task):
        try:
            result = task.finish()
            print(f"[query done] complete={result.complete} "
                  f"first={result.rsm.first} last={result.rsm.last}")
            state['query_result'] = result
        except Exception as e:
            print(f"[query FAILED] {e!r}")
            state['query_result'] = e
        state['query_done'] = True
        GLib.timeout_add(500, lambda: loop.quit() or GLib.SOURCE_REMOVE)

    def on_connected(_client, _signal_name):
        print("[connected] issuing MAM query...")
        queryid = str(uuid.uuid4())
        state['query_id'] = queryid
        task = client.get_module('MAM').make_query(
            jid=my_jid, queryid=queryid, with_=with_jid, max_=20)
        task.add_done_callback(on_query_done)

    def on_disconnected(_client, _signal_name):
        print("[disconnected]")
        loop.quit()

    def on_connection_failed(_client, _signal_name):
        error, text, _extra = client.get_error()
        print(f"[connection failed] {error}: {text}")
        loop.quit()

    client = NbxmppClient(log_context='mam-spike')
    client.set_username(my_jid.localpart)
    client.set_domain(my_jid.domain)
    client.set_resource('mam-spike')
    client.set_password(password)
    client.subscribe('connected', on_connected)
    client.subscribe('disconnected', on_disconnected)
    client.subscribe('connection-failed', on_connection_failed)
    client.register_handler(StanzaHandler(name='message', callback=on_message))
    client.connect()

    def timeout_guard():
        print("[TIMEOUT] no result after 30s, aborting")
        loop.quit()
        return GLib.SOURCE_REMOVE
    GLib.timeout_add_seconds(30, timeout_guard)

    loop.run()

    # --- Assertions ---
    print("\n--- Results ---")
    print(f"messages received: {len(received)}")
    print(f"query_done: {state['query_done']}")
    result = state['query_result']

    ok = True
    if not state['query_done']:
        print("FAIL: query never completed")
        ok = False
    elif isinstance(result, Exception):
        print(f"FAIL: query errored: {result!r}")
        ok = False
    else:
        print(f"query complete flag: {result.complete}")

    mismatched = [r for r in received if r[0] != state['query_id']]
    if mismatched:
        print(f"FAIL: {len(mismatched)} message(s) with mismatched query_id: {mismatched}")
        ok = False
    else:
        print(f"OK: all {len(received)} received message(s) correlate to queryid "
              f"{state['query_id']}")

    if received:
        ids = [r[1] for r in received]
        if len(ids) != len(set(ids)):
            print("FAIL: duplicate mam_id in a single page")
            ok = False
        else:
            print("OK: no duplicate mam_id within the page")

    print("\nSPIKE RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
