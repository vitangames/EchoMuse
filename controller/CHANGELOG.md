# Changelog

## 2.19.0-recorder.1

- Based on the official EchoMuse Controller 2.19 Home Assistant add-on.
- Adds a passive recorder to each Echo Dot device page. It saves 16 kHz mono
  PCM16 WAV clips from the same continuous microphone stream used by
  openWakeWord, without consuming or rerouting the detector audio.
- Supports single captures and short series, with phrase, distance,
  environment, notes, playback, download, deletion, and a JSONL manifest.
- Stores recordings under `/data/wake_samples`, so Home Assistant preserves
  them across add-on restarts and updates.
- Includes the latest upstream Home Assistant ingress, authentication, and
  automatic server-address fixes available after the 2.19.0 tag.

## 2.20.0-ea.1 — Early Access

- **Leaving "Server IP" empty now detects this host's LAN address.** The old
  fallback was a hardcoded address, so a fresh install with the field blank
  advertised it to every device over mDNS: the controller ran perfectly and
  no device could reach it, with nothing reporting an error anywhere. If you
  set the field by hand to work around that, you can clear it.
- **No separate dashboard login under Home Assistant.** HA has already
  authenticated you, so the panel signs you in as your HA user and the
  first-run setup token is gone. The first person through becomes admin;
  everyone after is read-only until promoted. There is no Sign out on an
  HA session — sign out of Home Assistant instead.
- **Recordings and transcripts are admin-only.** Saved utterances are
  recognisable speech from inside your home, and every household HA user can
  reach the panel, so read-only accounts no longer see the audio player or
  the transcript text. Enforced on the server, not hidden in the page.
- Roles can be changed via `PATCH /api/users/{id}`; the last admin cannot be
  demoted.
- The provisioning wizard's WebUSB error now names the exact origin the
  browser needs allowed, instead of suggesting an address the add-on refuses.
- Early Access is a separate add-on with its own storage. Switching channels
  is a migration, not a toggle — see this add-on's documentation.

## 1.0.1

- Initial Home Assistant Supervisor add-on packaging: install and run the
  controller from Settings → Add-ons instead of hand-run docker-compose.
- Ingress support for the dashboard (no separate port to expose).
- Add-on config UI labels, icon, and logo.
