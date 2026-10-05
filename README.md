# EVONETRTKBASE

Software per **basi GNSS RTK su Raspberry Pi** della rete EVONETRTK. È
[ELT_RTKBase](https://github.com/GNSSOEM/ELT_RTKBase) (a sua volta basato su
[RTKBase](https://github.com/Stefal/rtkbase)) con in più la pagina **Rete**, pensata per basi installate in
posti senza un tecnico vicino e collegate con la rete mobile.

Il README originale di ELT_RTKBase è in [README_ELT.md](README_ELT.md).

## Cosa aggiunge a ELT_RTKBase

- **Pagina Rete** nel pannello: priorità tra Ethernet, WiFi e LTE, scelta della rete WiFi, LTE acceso solo
  quando serve, APN e PIN della SIM, traffico mensile LTE con soglia, registro eventi.
- **Modem LTE Air780E** (scheda a pogo pin per Raspberry Pi Zero, RNDIS): riconoscimento automatico, recupero
  della connessione, segnale, gestore, tensione e temperatura.
- **Hotspot di emergenza**: se la base resta senza internet, accende una sua rete WiFi e chi si collega viene
  portato alla pagina Rete.
- **Controlli automatici**: temperature (Pi, ricevitore, modem), ricevitore che smette di trasmettere (con il
  numero di satelliti visti), chip WiFi bloccato (riavvio), servizi della base fermi (ripartenza),
  ricollegamento veloce al caster dopo i tagli della rete mobile.
- **Scheda di accesso stampabile**: indirizzi, QR, utenti e password, istruzioni passo per passo e cosa fare se
  la base non risponde.
- **Aggiornamenti online da questo repository**, con canale stabile/prova, verifica dell'impronta SHA-256 di
  `install.sh` e copia di sicurezza prima di installare. La base avvisa, non installa mai da sola.

## Installazione su una base nuova

1. Scrivere sulla scheda SD **Raspberry Pi OS Lite (64 bit)** con Raspberry Pi Imager (nome host, utente, WiFi
   e SSH si impostano nell'Imager).
2. Collegare il ricevitore GNSS (Unicore UM98x o un altro supportato da ELT_RTKBase) e, se c'è, il modem LTE.
3. Entrare in SSH e lanciare:

   ```bash
   wget https://github.com/EVONETRTK/EVONETRTKBASE/releases/latest/download/install.sh
   chmod +x install.sh
   ./install.sh
   ```

   Per una versione del canale prova, scaricare `install.sh` dalla [pagina dei rilasci](../../releases).
4. Aprire `http://<nome-base>.local`, completare la configurazione di ELT_RTKBase e poi la pagina **Rete**.

## Aggiornare una base

- Pagina Rete → **Aggiornamenti del software**: versione installata, canale, novità.
- Per installare: Settings → **Check update** → Update.
- Senza internet: `http://<base>/settings?update=manual` e caricare un `install.sh` preso dai
  [rilasci](../../releases).

| Canale | Ramo | Per |
|---|---|---|
| stabile | `main` | basi in campo |
| prova | `prova` | base di test: ogni versione passa da qui prima di andare su stabile |

## Per chi sviluppa

Struttura dei file, numerazione delle versioni, test e pubblicazione dei rilasci: [rete/LEGGIMI.md](rete/LEGGIMI.md).

## Licenza

AGPL-3.0, come ELT_RTKBase e RTKBase (vedi [LICENSE](LICENSE)). Codice originale di
[GNSSOEM/ELT_RTKBase](https://github.com/GNSSOEM/ELT_RTKBase) e [Stefal/rtkbase](https://github.com/Stefal/rtkbase).
