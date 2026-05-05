# loxone-av-sync

System synchronizacji multimediów z automatyką budynkową w czasie rzeczywistym.  
Kontroler działa na RPi3, pobiera timestamp z Kodi (Firestick) i wyzwala zdarzenia
w Loxone Miniserver i AudioSerwerze według zdefiniowanego scenariusza JSON.

## Architektura

```
Firestick (Kodi)  →  RPi3 (kontroler Python)  →  Loxone Miniserver
                                               →  AudioSerwer
```

Polling Kodi JSON-RPC API co 500ms → precyzyjne wyzwalanie zdarzeń (±500ms).

## Wymagania

- Python 3.11+
- RPi3 / RPi4 (Raspberry Pi OS)
- Kodi z włączonym JSON-RPC API (port 8080)
- Loxone Miniserver z HTTP API Connector
- Loxone AudioSerwer (opcjonalnie)

## Instalacja

```bash
git clone https://github.com/rqureshi/loxone-av-sync.git
cd loxone-av-sync

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp config.yaml.example config.yaml
nano config.yaml          # uzupełnij adresy IP i dane logowania

python -m src.main
```

Panel webowy dostępny pod: `http://<ip-rpi>:5000`

## Autostart (systemd)

```bash
sudo cp systemd/loxone-av-sync.service /etc/systemd/system/
sudo systemctl enable loxone-av-sync
sudo systemctl start loxone-av-sync
sudo journalctl -u loxone-av-sync -f
```

## Format scenariusza

Scenariusze to pliki JSON w katalogu `scenarios/`. Każde zdarzenie definiuje
czas (HH:MM:SS) i listę akcji wysyłanych do Loxone lub AudioSerwer.

```json
{
  "title": "Nazwa scenariusza",
  "events": [
    {
      "id": "evt_001",
      "time": "00:05:32",
      "label": "Opis zdarzenia",
      "actions": [
        { "type": "loxone", "command": "LightScene_Burza", "value": 1 },
        { "type": "audio", "command": "play", "file": "grzmot.mp3", "volume": 80 }
      ]
    }
  ]
}
```

### Typy akcji

| type | Opis |
|------|------|
| `loxone` | Komenda do Loxone Virtual Input (`command`, `value`) |
| `loxone_scene` | Aktywacja sceny Loxone (`scene_name`) |
| `audio` | Odtworzenie dźwięku (`command: play/stop`, `file`, `volume`) |

## Konfiguracja Kodi (Firestick)

Settings → Services → Control → Enable HTTP control: **ON**, port 8080, user/pass: kodi/kodi

## Do weryfikacji przed uruchomieniem

- [ ] JSON-RPC API włączone w Kodi
- [ ] Nazwy Virtual Inputs w Loxone Config
- [ ] Endpointy HTTP API AudioSerwer
- [ ] Test: `curl -u kodi:kodi http://<firestick-ip>:8080/jsonrpc -d '{"jsonrpc":"2.0","method":"JSONRPC.Ping","id":1}'`
- [ ] Test: `curl -u admin:admin http://<loxone-ip>/dev/sps/io/test/1`
