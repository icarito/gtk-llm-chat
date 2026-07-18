# Tasks

- [x] Start the configured XMPP session at application startup, independently
      of window restoration.
- [x] Suppress duplicate approval transport acknowledgements from chat history;
      retain the single actionable approval card.
- [ ] Introduce the application-scoped lifecycle state model and signals.
- [ ] Add immediate startup/splash surface with phase text and bounded timeout.
- [ ] Replace ambiguous spinners with retry, offline-by-user and error actions.
- [ ] Add self-presence editor and publish available/away/dnd/xa plus status.
- [ ] Add vCard read/edit for display name, avatar and supported profile fields.
- [ ] Update architecture documentation, translations and lifecycle tests.
- [ ] Verify cold start with no saved windows, warm activation and reconnect.
- [ ] Verify approval card transitions pending → submitted → resolved/error
      without duplicate bubbles or a stuck working state.
