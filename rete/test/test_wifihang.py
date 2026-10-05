exec(open("test_network_page.py", encoding="utf-8").read().split("fake = FakeNM()")[0])
n.AUTO_REBOOT_FILE = os.path.join(tmp, "reboot.json")
events = []; n.log = lambda m: events.append(m)
cmds = []; state = {"flood": False}
popen = []
n.subprocess.Popen = lambda args, **kw: popen.append(args)
normal = "\n".join("[%d] usb 1-1: ok" % i for i in range(300))
flood = "\n".join("[%d.1] brcmfmac: brcmf_sdio_htclk: HT Avail request error: -5" % i for i in range(300))
def fake_run(args, timeout=15):
    cmds.append(args)
    if args[0] == "dmesg": return flood if state["flood"] else normal
    return ""
n.run = fake_run
n.check_wifi_chip(0); assert not events
state["flood"] = True
n.check_wifi_chip(1000); n.check_wifi_chip(1090); assert not popen
n.check_wifi_chip(1120)
assert popen == [["systemctl", "reboot", "--force"]] and "riavvio la base" in events[-1]
assert not any(c[0] == "modprobe" for c in cmds)                  # niente ricarica del driver
n.WIFI_HANG.update(since=None, warned=False); popen.clear()
n.check_wifi_chip(5000); n.check_wifi_chip(5130)
assert not popen and "meno di 6 ore" in events[-1]
state["flood"] = False
n.check_wifi_chip(5300); assert "di nuovo regolare" in events[-1]
print("CHIP WIFI OK")

# guardiano dei servizi
svc = {"str2str_tcp.service": ("enabled", "active"), "str2str_ntrip_A.service": ("enabled", "inactive"),
       "str2str_ntrip_B.service": ("disabled", "inactive")}
def show(args, timeout=15):
    cmds.append(args)
    if args[:2] == ["systemctl", "show"]:
        blocks = []
        for u in args[3:]:
            if u == "str2str_ntrip_E.service":            # unita' inesistente
                blocks.append("Id=%s\nActiveState=inactive\nUnitFileState=" % u)
                continue
            e, a = svc.get(u, ("disabled", "inactive"))
            blocks.append("Id=%s\nActiveState=%s\nUnitFileState=%s" % (u, a, e))
        return True, "\n\n".join(blocks) + "\n", ""
    return True, "", ""
def run2(args, timeout=15):
    cmds.append(args)
    if args[:2] == ["systemctl", "start"]: svc[args[2]] = ("enabled", "active")
    return ""
real_run_cmd = n.run_cmd
n.run_cmd = show; n.run = run2; cmds.clear(); events.clear()
n.guard_services(100); assert not any(c[:2] == ["systemctl", "start"] for c in cmds)   # aspetta 60 s
assert sum(1 for c in cmds if c[:2] == ["systemctl", "show"]) == 1                      # una sola chiamata
n.guard_services(170)
assert ["systemctl", "start", "str2str_ntrip_A.service"] in cmds and "str2str_ntrip_A abilitato ma fermo" in events[-1]
assert not any(c == ["systemctl", "start", "str2str_ntrip_B.service"] for c in cmds)   # disabilitato: non si tocca
print("GUARDIANO OK")

# chip bloccato "in silenzio": WiFi scollegato + scansione -110
n.run = fake_run
state["flood"] = False; popen.clear(); events.clear()
import json as J
os.remove(n.AUTO_REBOOT_FILE)
n.WIFI_HANG.update(since=None, warned=False, down_since=None, last_probe=0, probe_fails=0)
wifi = {"state": "disconnected"}; scan = {"err": "command failed: Connection timed out (-110)"}
n.list_devices = lambda: [{"device": "wlan0", "kind": "wifi", "type": "wifi", "state": wifi["state"], "connection": None}]
n.get_radio_wifi = lambda: True
n.hotspot_active = lambda: False
n.run_cmd = lambda args, timeout=15: (False, "", scan["err"]) if args[:2] == ["iw", "dev"] else (True, "", "")
st = n.load_settings()
for t in (10000, 10100, 10200):           # meno di 5 minuti scollegato: niente
    n.check_wifi_chip(t, st)
assert not popen
n.check_wifi_chip(10300, st); assert not popen          # 1a scansione fallita
n.check_wifi_chip(10330, st); assert not popen          # prova ogni 60 s
n.check_wifi_chip(10360, st)                            # 2a scansione fallita -> riavvio
assert popen == [["systemctl", "reboot", "--force"]] and "scansioni in timeout" in events[-1], events
# base in campo senza reti: scansione OK -> mai riavvio
os.remove(n.AUTO_REBOOT_FILE); popen.clear()
n.WIFI_HANG.update(since=None, warned=False, down_since=None, last_probe=0, probe_fails=0)
scan["err"] = ""
for t in range(20000, 22000, 30):
    n.check_wifi_chip(t, st)
assert not popen
# WiFi disabilitato: mai riavvio
st["enabled"]["wifi"] = False; scan["err"] = "(-110)"
for t in range(30000, 31000, 30):
    n.check_wifi_chip(t, st)
assert not popen
print("CHIP SILENZIOSO OK")

# scansione "occupata" (-16) di fila: riavvio solo alla 3a (01/10)
os.path.exists(n.AUTO_REBOOT_FILE) and os.remove(n.AUTO_REBOOT_FILE); popen.clear(); events.clear()
st["enabled"]["wifi"] = True
n.WIFI_HANG.update(since=None, warned=False, down_since=None, last_probe=0, probe_fails=0, probe_busy=False)
scan["err"] = "command failed: Device or resource busy (-16)"
for t in (40000, 40300, 40360):
    n.check_wifi_chip(t, st)
assert not popen, popen                                    # 2 scansioni occupate: non basta
n.check_wifi_chip(40420, st)
assert popen == [["systemctl", "reboot", "--force"]] and "o bloccate" in events[-1], events
# occupata una volta sola, poi la scansione riesce: nessun riavvio
os.remove(n.AUTO_REBOOT_FILE); popen.clear()
n.WIFI_HANG.update(since=None, warned=False, down_since=None, last_probe=0, probe_fails=0, probe_busy=False)
seq = iter(["(-16)", "", "(-16)", "", "(-16)", ""] * 20)
n.run_cmd = lambda args, timeout=15: (False, "", next(seq)) if args[:2] == ["iw", "dev"] else (True, "", "")
for t in range(50000, 52000, 30):
    n.check_wifi_chip(t, st)
assert not popen
print("SCANSIONE OCCUPATA OK")
