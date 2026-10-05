# EVONETRTKBASE (ELT_RTKBase con la pagina "Rete")

Versione modificata di ELT_RTKBase con la pagina **Rete**: gestione di Ethernet, WiFi e LTE, hotspot di
emergenza, modem Air780E, traffico LTE, temperature, registro eventi, scheda di accesso stampabile.
Si aggiorna online dal repository [EVONETRTK/EVONETRTKBASE](https://github.com/EVONETRTK/EVONETRTKBASE), non da
quello ufficiale di ELT (che installerebbe la versione senza queste funzioni).

## File della pagina Rete (in `Install/`)

| File | A cosa serve |
|---|---|
| `network_page.py` | Logica: NetworkManager, hotspot, modem, controllo internet, traffico, temperature, aggiornamenti |
| `network_routes.py` | Route Flask della pagina |
| `network.html`, `network.js` | La pagina |
| `network_access.html`, `qrcode.min.js` | Scheda di accesso stampabile (`/network/access`) |
| `rtkbase_network_watch.service` | Servizio sempre attivo (priorità, hotspot, PIN, recupero LTE, controlli) |
| `rtkbase_hotspot_dns.conf` | Fa aprire la pagina Rete ai telefoni collegati all'hotspot |
| `90-rtkbase-network.conf`, `90-rtkbase-journald.conf` | sysctl (TCP, kernel.panic) e limiti del registro |
| `server_py_network.patch`, `base_html_network.patch` | Collegano la pagina a RTKBase |

Le modifiche a `install_script.sh`, `create_release.sh`, `uninstall.sh`, `UnicoreConfigure.sh` (salta le porte
dei modem LTE nel rilevamento del ricevitore), ai file UM98x e a `.gitattributes` sono salvate in
`rete/installer.patch`. `server_py_network.patch` si rigenera con `rete/genera_server_patch.py`, partendo da
`rete/riferimento/server_elt.py` (server.py di RTKBase con la patch di ELT già applicata).

## Versioni

`NEW_VERSION` in `install_script.sh` = versione ELT (3 cifre) + nostra revisione (2 cifre):
**19801** = ELT 1.9.8, revisione 01, mostrata come **1.9.8-01**. La base la salva in
`/usr/local/rtkbase/version.txt`.

## Test

```bash
rete/test/esegui_test.sh <python con flask, flask-login, werkzeug>
```

## Pubblicare una versione (aggiornamento online)

Due canali, scelti su ogni base nella pagina Rete, riquadro *Aggiornamenti del software*:

| Canale | Ramo GitHub | Per |
|---|---|---|
| prova | `prova` | la base di test |
| stabile | `main` | le basi in campo |

```bash
PYTHON=<python con flask> rete/rilascia.sh prova "cosa cambia" "altra novità"
#   test -> nuova revisione -> install.sh -> Description.json con impronta SHA-256 -> push sul ramo prova
rete/rilascia.sh promuovi      # dopo qualche giorno senza problemi: la stessa versione va su stabile
rete/rilascia.sh stato         # versioni pubblicate
```

Ogni rilascio crea anche il tag `v1.9.8-NN` e una Release su GitHub con `install.sh` allegato: pre-release
finché è sul canale prova, definitiva (e "latest", quella del link di installazione nel README) dopo
`promuovi`. Il ramo di lavoro sul PC è `evonet`.

Serve il remote git `evonet` (`git remote add evonet https://github.com/EVONETRTK/EVONETRTKBASE.git`).

## Aggiornare una base

- **Online:** pagina Rete → *Aggiornamenti del software* mostra se c'è una versione nuova (la base controlla da
  sola ogni 12 ore e lo scrive nel registro eventi, ma non installa mai da sola). Per installare:
  Settings → **Check update** → Update. Prima di eseguire, la base verifica l'impronta SHA-256 di `install.sh` e
  salva una copia di pannello e impostazioni in `/usr/local/rtkbase/backup` (ultime 3).
- **Senza internet:** `http://<base>/settings?update=manual` → Check update → caricare un `install.sh`.
- **Tornare indietro:** `sudo tar -xzf /usr/local/rtkbase/backup/<file>.tar.gz -C /` e riavviare.

## Passare a una nuova versione ufficiale di ELT_RTKBase

```bash
./rete/aggiorna_da_elt.sh prepara      # solo se abbiamo cambiato l'installer
./rete/aggiorna_da_elt.sh aggiorna     # crea ../ELT_RTKBase_rete_v<versione>
```

Lo script scarica ELT in una cartella nuova e ci rimette le nostre modifiche. Controlla poi che le patch
si applichino ancora al RTKBase contenuto e genera `install.sh`. Se qualcosa non si applica, lo segnala e
non genera `install.sh`. Poi: aggiornare `NEW_VERSION` alla nuova versione ELT con revisione 01 (es. 19901),
rigenerare `server_py_network.patch` se ELT ha cambiato server.py, e rilasciare sul canale prova.
