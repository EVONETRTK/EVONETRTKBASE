import sys, os, json, hashlib, tarfile
exec(open("test_network_page.py", encoding="utf-8").read().split("fake = FakeNM()")[0])
events = []; n.log = lambda m: events.append(m)
n.VERSION_FILE = os.path.join(tmp, "version.txt")
n.UPDATE_STATE_FILE = os.path.join(tmp, "update.json")
n.BACKUP_DIR = os.path.join(tmp, "backup")

assert n.version_label(19801) == "1.9.8-01" and n.version_label(198) == "1.9.8" and n.version_label(0) == "sconosciuta"
assert n.installed_version() == 0                                   # base senza version.txt
open(n.VERSION_FILE, "w").write("19801\n")
assert n.installed_version() == 19801

script = b"#!/bin/bash\necho installa\n"
web = {}
def http_get(url, timeout=30, limit=1024 * 1024):
    web.setdefault("urls", []).append(url)
    if url not in web:
        raise OSError("404")
    return web[url]
n.http_get = http_get
st = n.load_settings()
assert st["update"]["channel"] == "stabile"
base = "https://raw.githubusercontent.com/EVONETRTK/EVONETRTKBASE/refs/heads/"
desc = {"version": "19802", "new_release": "EVONETRTKBASE 1.9.8-02", "comment": "novita'",
        "sha256": hashlib.sha256(script).hexdigest()}
web[base + "main/Description.json"] = json.dumps(desc).encode()
web[base + "main/install.sh"] = script

r = n.check_update()
assert r["available"] and r["latest_label"] == "1.9.8-02" and r["current_label"] == "1.9.8-01", r
assert n.update_status()["available"]

# canale prova: altro ramo
n.set_update_channel("prova")
assert not os.path.exists(n.UPDATE_STATE_FILE)
r = n.check_update(); assert r.get("error") and not r["available"]
assert web["urls"][-1] == base + "prova/Description.json"
try:
    n.set_update_channel("altro"); raise SystemExit("canale non valido accettato")
except ValueError:
    pass
n.set_update_channel("stabile")

# download con impronta giusta
out = os.path.join(tmp, "update.sh")
assert n.download_update(out) is None and open(out, "rb").read() == script
# impronta sbagliata (download incompleto)
web[base + "main/install.sh"] = script[:-3]
assert "impronta" in n.download_update(out)
web[base + "main/install.sh"] = script
# senza impronta
web[base + "main/Description.json"] = json.dumps({"version": "19802"}).encode()
assert "SHA-256" in n.download_update(out)
# versione non piu' recente
web[base + "main/Description.json"] = json.dumps(dict(desc, version="19801")).encode()
assert "Nessuna versione" in n.download_update(out)
web[base + "main/Description.json"] = json.dumps(desc).encode()

# copia di sicurezza: ne tiene 3
n.SETTINGS_FILE and n.save_settings(n.load_settings())
open(n.RTKBASE_SETTINGS, "w").write("[general]\n")
names = []
for i in range(5):
    n.time.strftime = (lambda i: (lambda fmt: "2026100%d-120000" % i))(i)
    names.append(n.backup_before_update())
left = sorted(os.listdir(n.BACKUP_DIR))
assert len(left) == 3 and os.path.basename(names[-1]) in left, left
with tarfile.open(names[-1]) as t:
    members = t.getnames()
assert any(m.endswith("network_page.py") for m in members) and not any("__pycache__" in m for m in members)
assert any(m.endswith("version.txt") for m in members)

# controllo periodico: un solo evento per versione nuova, mai installazione
events.clear()
os.path.exists(n.UPDATE_STATE_FILE) and os.remove(n.UPDATE_STATE_FILE)
INTERNET["ok"] = True
n.check_update_periodically(100000, st)
assert len(events) == 1 and "disponibile l'aggiornamento EVONETRTKBASE 1.9.8-02" in events[0], events
n.check_update_periodically(100000 + 13 * 3600, st)          # stessa versione: niente doppio avviso
assert len(events) == 1
s = json.load(open(n.UPDATE_STATE_FILE)); s["time"] = int(n.time.time()); json.dump(s, open(n.UPDATE_STATE_FILE, "w"))
calls = len(web["urls"]); n.check_update_periodically(int(n.time.time()) + 60, st)
assert len(web["urls"]) == calls                             # meno di 12 ore: nessuna richiesta
print("AGGIORNAMENTI OK")

# risposta per Settings (server.py)
import network_routes
res = network_routes.check_update_for_settings()
assert res["version"] == 19802 and res["new_release"] == "EVONETRTKBASE 1.9.8-02" and "canale stabile" in res["comment"]
open(n.VERSION_FILE, "w").write("19802\n")
assert network_routes.check_update_for_settings() == {}
web.pop(base + "main/Description.json")
assert "error" in network_routes.check_update_for_settings()
print("AGGIORNAMENTI SETTINGS OK")
