# loxone-av-sync — kontekst projektu

## Cel i przeznaczenie

Mobilny zestaw demo do prezentacji możliwości Loxone u klienta.
Synchronizuje film odtwarzany na Firestick ze zdarzeniami w automatyce budynkowej
(światła, rolety, dźwięk) według scenariusza JSON.

**Kluczowe założenie: system działa w pełni autonomicznie, bez internetu i bez
sieci klienta.** Wystarczy zasilanie.

---

## Architektura sieciowa — mobilna, self-contained

```
Cudy LT3000 (router, SSID: cudy_4444)
    │
    ├── WiFi
    │     └── Firestick (10.1.1.240) — Kodi 21.2 Omega, film zapisany lokalnie
    │
    └── Switch (LAN)
          ├── RPi3 (10.1.1.105)       — kontroler Python, loxone-av-sync
          ├── Loxone Miniserver (10.1.1.13)
          └── AudioSerwer (10.1.1.11)
```

### Zasada działania

1. Technik przyjeżdża do klienta, podłącza sprzęt i router Cudy
2. Cudy tworzy lokalną sieć `cudy_4444` — wszystkie urządzenia łączą się automatycznie
3. Firestick przez WiFi, pozostałe urządzenia przez switch
4. Film jest zapisany **lokalnie na Firestick** (pendrive USB lub pamięć wewnętrzna)
5. RPi3 co 500ms odpytuje Kodi o aktualny timestamp przez JSON-RPC
6. Na podstawie timestamp wyzwala zdarzenia w Loxone i AudioSerwerze
7. **Brak streamowania** — RPi3 nie serwuje plików wideo, tylko czyta czas odtwarzania

---

## Zweryfikowane dane dostępowe

| Urządzenie | IP | Auth |
|---|---|---|
| Firestick / Kodi | 10.1.1.240:8080 | kodi:kodi |
| Loxone Miniserver | 10.1.1.13 | Basic Auth admin:075600jrH!1a |
| AudioSerwer | 10.1.1.11:7091 | brak (paired z Loxone) |
| RPi3 | 10.1.1.105 | — |

---

## Ważne odkrycia techniczne

### AudioSerwer — sterowanie przez Loxone, nie bezpośrednio

AudioSerwer jest **spairowany z Loxone Miniserver**. Bezpośrednie HTTP komendy
do AudioSerwer (port 7091) zwracają `"command not allowed when paired"`.

Sterowanie audio musi iść przez Loxone:
- Virtual Output w Loxone → AudioSerwer
- Komendy w scenariuszu JSON typu `"loxone"`, nie `"audio"` (do ustalenia z Loxone Config)

### Loxone Miniserver — Basic Auth (nie token)

Firmware wymaga tokenu dla niektórych endpointów, ale `/dev/sps/io/` działa
przez Basic Auth. Hasło: `075600jrH!1a`.

### Kodi — JSON-RPC na port 8080

Zainstalowany przez ADB, ustawiony przez Settings API. Autoryzacja: `kodi:kodi`.
Film odtwarzany z lokalnego storage Firestick — pendrive USB lub `/sdcard/`.

### Dostępne kontrolki w Miniserver "DET"

| Typ | Nazwa | UUID |
|---|---|---|
| AudioZoneV2 | Odtwarzacz Audio | 202a2ae5-0272-a407-ffff0a0fb1695586 |
| LightControllerV2 | Sterownik oświetlenia | 202a29e1-02cc-745e-ffff0a0fb1695586 |
| Jalousie | Automatyczne zacienianie | 202a2a0e-03bb-7c3a-ffff0a0fb1695586 |
| PresenceDetector | Obecność | 202a33f3-0070-1c04-ffff0a0fb1695586 |
| Switch | LED obecnosc OFF | 20498c76-00b3-cc55-ffff0a0fb1695586 |

---

## Stack technologiczny

- **Python 3.11+** na RPi3
- **Flask** — panel webowy (port 5000)
- **Kodi JSON-RPC API** — timestamp odtwarzania
- **Loxone HTTP API** — `/dev/sps/io/{VirtualInput}/{value}`
- **SQLite** — historia wykonanych zdarzeń
- **systemd** — autostart na RPi3

---

## Priorytety implementacji

1. `kodi_client.py` — polling timestamp, obsługa pauzy/seek/koniec
2. `scheduler.py` — silnik zdarzeń, pre-trigger 200ms, tolerancja ±500ms
3. `loxone_client.py` — Basic Auth + retry
4. `audio_client.py` — **przez Loxone**, nie bezpośrednio do AudioSerwer
5. `web/app.py` — panel webowy
6. `systemd` — autostart

---

## Do zrobienia

- [ ] Zweryfikować nazwy Virtual Inputs w Loxone Config (jakie VI sterują strefą audio)
- [ ] Przepisać audio_client.py — komendy audio przez Loxone zamiast bezpośrednio
- [ ] Zaktualizować config.yaml.example z poprawnymi IP i hasłami
- [ ] Deploy na RPi3
- [ ] Test end-to-end z filmem na Firestick
