""" Test di network_page.py con un NetworkManager simulato """
import os, sys, json, uuid as uuidlib, tempfile, contextlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "Install"))
import network_page as n

tmp = tempfile.mkdtemp()
n.SETTINGS_FILE = os.path.join(tmp, "settings.json")
n.SCAN_CACHE = os.path.join(tmp, "scan.json")
n.PIN_STATE = os.path.join(tmp, "pin.json")
n.ACTIVATION_STATE = os.path.join(tmp, "activation.json")
n.EVENTS_FILE = os.path.join(tmp, "events.log")
n.TRAFFIC_FILE = os.path.join(tmp, "traffic.json")
n.HEALTH_FILE = os.path.join(tmp, "health.json")
n.LTE_STATE_FILE = os.path.join(tmp, "lte.json")
n.RTKBASE_SETTINGS = os.path.join(tmp, "rtkbase_settings.conf")
n.time.sleep = lambda s: None
n.file_lock = lambda *a, **k: contextlib.nullcontext()
n.is_locked = lambda p: False
n.get_driver = lambda d: {"usb0": "rndis_host", "eth0": "r8152"}.get(d)
INTERNET = {"ok": True}
n.internet_ok = lambda max_age=0: INTERNET["ok"]
VIA = {}
n.internet_via = lambda dev: VIA.get(dev, INTERNET["ok"])


class FakeNM:
    def __init__(self):
        self.radio = True
        self.devices = {"eth0": {"type": "ethernet", "state": "unavailable", "con": None, "autoconnect": True},
                        "wlan0": {"type": "wifi", "state": "disconnected", "con": None, "autoconnect": True},
                        "usb0": {"type": "ethernet", "state": "disconnected", "con": None, "autoconnect": True}}
        self.cons = {}
        self.scan = [("Casa", 70, "WPA2"), ("Vicino", 40, "WPA1 WPA2"), ("Ufficio", 55, "WPA3")]
        self.good_psk = {"Casa": "passwordcasa", "Ufficio": "ufficio123"}
        self.log = []
        self.add("preconfigured", "802-11-wireless", {"802-11-wireless.ssid": "Casa", "802-11-wireless-security.psk": "passwordcasa",
                                                       "802-11-wireless.mode": "infrastructure", "ipv4.route-metric": "-1", "ifname": "wlan0"})
        self.up("preconfigured", "wlan0")

    def add(self, name, ctype, settings):
        u = str(uuidlib.uuid4())
        self.cons[name] = {"uuid": u, "type": ctype, "s": settings, "dev": None}
        return u

    def find(self, key):
        for name, c in self.cons.items():
            if key in (name, c["uuid"]):
                return name
        return None

    def up(self, name, dev=None):
        c = self.cons[name]
        dev = dev or c["s"].get("ifname")
        if c["type"] == "802-11-wireless":
            if not self.radio:
                return False
            if c["s"].get("802-11-wireless.mode") != "ap":
                ssid = c["s"]["802-11-wireless.ssid"]
                if ssid not in [s[0] for s in self.scan] or self.good_psk.get(ssid) != c["s"].get("802-11-wireless-security.psk"):
                    self.down_dev(dev)
                    return False
        elif self.devices[dev]["state"] == "unavailable":
            return False
        self.down_dev(dev)
        c["dev"] = dev
        self.devices[dev].update(state="connected", con=name, rt_metric=None)
        return True

    def down_dev(self, dev):
        d = self.devices[dev]
        if d["con"]:
            self.cons[d["con"]]["dev"] = None
        d.update(state="disconnected" if d["state"] != "unavailable" else "unavailable", con=None)

    def metric(self, dev):
        if self.devices[dev].get("rt_metric") is not None:
            return self.devices[dev]["rt_metric"]
        con = self.devices[dev]["con"]
        m = int(self.cons[con]["s"].get("ipv4.route-metric", "-1"))
        return m if m >= 0 else {"ethernet": 100, "wifi": 600}[self.devices[dev]["type"]]

    def __call__(self, args, timeout=None):
        self.log.append(args)
        a = list(args)
        if a[:1] == ["iw"]:
            return True, "", ""
        if a[:3] == ["ip", "-4", "route"]:
            out = ""
            for dev, d in self.devices.items():
                if d["state"] == "connected" and not (dev == "wlan0" and self.cons[d["con"]]["s"].get("802-11-wireless.mode") == "ap"):
                    out += "default via 10.0.0.1 dev %s proto dhcp metric %d\n" % (dev, self.metric(dev))
            return True, out, ""
        if a[:1] == ["tailscale"]:
            return False, "", "tailscale non installato"
        if a[:1] == ["dmesg"]:
            return True, "", ""
        if a[:1] == ["systemctl"]:
            self.log.append(a)
            return True, "", ""
        assert a[0] == "nmcli", a
        a = a[1:]
        if a[:1] == ["--wait"]:
            a = a[2:]
        if a == ["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"]:
            return True, "".join("%s:%s:%s:%s\n" % (dev, d["type"], d["state"], d["con"] or "") for dev, d in self.devices.items()), ""
        if a[:3] == ["-t", "-f", "IP4.ADDRESS,IP4.GATEWAY,IP4.DNS,GENERAL.HWADDR"]:
            return True, "IP4.ADDRESS[1]:10.0.0.5/24\nIP4.GATEWAY:10.0.0.1\nGENERAL.HWADDR:AA\\:BB\n", ""
        if a[:5] == ["-t", "-f", "ACTIVE,SSID,SIGNAL", "device", "wifi"]:
            con = self.devices["wlan0"]["con"]
            ssid = self.cons[con]["s"].get("802-11-wireless.ssid") if con else None
            return True, "".join("%s:%s:%d\n" % ("yes" if s == ssid else "no", s, sig) for s, sig, _ in self.scan), ""
        if a[:5] == ["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi"]:
            return True, "".join(":%s:%d:%s\n" % (s, sig, sec) for s, sig, sec in self.scan), ""
        if a == ["radio", "wifi"]:
            return True, "enabled\n" if self.radio else "disabled\n", ""
        if a[:2] == ["radio", "wifi"]:
            was = self.radio
            self.radio = a[2] == "on"
            if not self.radio:
                self.down_dev("wlan0")
            elif not was:   # autoconnect di NetworkManager
                for name, c in list(self.cons.items()):
                    if c["type"] == "802-11-wireless" and c["s"].get("802-11-wireless.mode") != "ap" and self.up(name, "wlan0"):
                        break
            return True, "", ""
        if a == ["-g", "NAME", "connection", "show"]:
            return True, "".join(n + "\n" for n in self.cons), ""
        if a[:2] == ["-s", "-g"]:
            name = self.find(a[5])
            if not name:
                return False, "", "no such connection"
            field = a[2]
            c = self.cons[name]
            val = {"connection.uuid": c["uuid"]}.get(field, c["s"].get(field, ""))
            return True, val.replace(":", "\\:") + "\n", ""
        if a[:3] == ["-t", "-f", "NAME,UUID,TYPE,ACTIVE"]:
            return True, "".join("%s:%s:%s:%s\n" % (n.replace(":", "\\:"), c["uuid"], c["type"], "yes" if c["dev"] else "no") for n, c in self.cons.items()), ""
        if a[:3] == ["-t", "-f", "UUID,DEVICE"]:
            return True, "".join("%s:%s\n" % (c["uuid"], c["dev"]) for c in self.cons.values() if c["dev"]), ""
        if a[:4] == ["-t", "-f", "NAME", "connection"]:
            return True, "".join(n + "\n" for n, c in self.cons.items() if c["dev"]), ""
        if a[:2] == ["connection", "add"]:
            kv = a[2:]
            opts = dict(zip(kv[0::2], kv[1::2]))
            name = opts["con-name"]
            if name in self.cons:
                name = name  # NM permette duplicati; qui basta
            s = {"ifname": opts.get("ifname")}
            for k, v in opts.items():
                k = {"ssid": "802-11-wireless.ssid", "wifi-sec.psk": "802-11-wireless-security.psk",
                     "wifi-sec.key-mgmt": "802-11-wireless-security.key-mgmt"}.get(k, k)
                s[k] = v
            s.setdefault("802-11-wireless.mode", "infrastructure")
            u = self.add(name, {"wifi": "802-11-wireless", "gsm": "gsm"}.get(opts["type"], "802-3-ethernet"), s)
            return True, "Connection '%s' (%s) successfully added.\n" % (name, u), ""
        if a[:2] == ["connection", "modify"]:
            name = self.find(a[2])
            kv = a[3:]
            for k, v in zip(kv[0::2], kv[1::2]):
                k = {"wifi-sec.psk": "802-11-wireless-security.psk", "wifi-sec.key-mgmt": "802-11-wireless-security.key-mgmt"}.get(k, k)
                self.cons[name]["s"][k] = v
            return True, "", ""
        if a[:2] == ["connection", "delete"]:
            name = self.find(a[2])
            if self.cons[name]["dev"]:
                self.down_dev(self.cons[name]["dev"])
            del self.cons[name]
            return True, "", ""
        if a[:2] == ["connection", "up"]:
            name = self.find(a[2])
            dev = a[4] if len(a) > 4 else None
            ok = self.up(name, dev)
            return ok, "", "" if ok else "Error: activation failed"
        if a[:2] == ["connection", "down"]:
            name = self.find(a[2])
            if name and self.cons[name]["dev"]:
                self.down_dev(self.cons[name]["dev"])
            return True, "", ""
        if a[:2] == ["device", "set"]:
            self.devices[a[2]]["autoconnect"] = a[4] == "yes"
            return True, "", ""
        if a[:2] == ["device", "disconnect"]:
            self.down_dev(a[2])
            return True, "", ""
        if a[:2] == ["device", "reapply"]:
            self.devices[a[2]]["rt_metric"] = None
            return True, "", ""
        if a[:2] == ["device", "modify"]:
            self.devices[a[2]]["rt_metric"] = int(a[4])
            return True, "", ""
        if a[:2] == ["device", "connect"]:
            for name, c in self.cons.items():
                if c["s"].get("ifname") == a[2] and self.up(name, a[2]):
                    return True, "", ""
            return False, "", "no profile"
        raise AssertionError("comando non simulato: %s" % args)


fake = FakeNM()
n.run_cmd = fake

# --- stato iniziale
s = n.get_status()
kinds = [(i["device"], i["kind"], i["state"]) for i in s["interfaces"]]
print(kinds)
assert kinds == [("eth0", "ethernet", "unavailable"), ("wlan0", "wifi", "connected"), ("usb0", "lte", "disconnected")]
assert s["internet_device"] == "wlan0" and s["interfaces"][1]["wifi"]["ssid"] == "Casa"

# --- apply: crea i profili, collega LTE, metriche per priorità
n.apply_interfaces(n.load_settings(), print)
assert "Rete-Ethernet-eth0" in fake.cons and "Rete-LTE-usb0" in fake.cons
assert fake.devices["usb0"]["con"] == "Rete-LTE-usb0"
assert fake.cons["preconfigured"]["s"]["ipv4.route-metric"] == "200"
assert fake.cons["Rete-LTE-usb0"]["s"]["ipv4.route-metric"] == "300"
assert n.get_status()["internet_device"] == "wlan0"
print("apply OK")

# --- priorità: LTE prima del WiFi
assert n.change_interfaces({"ethernet": True, "wifi": True, "lte": True}, ["lte", "wifi", "ethernet"], print)
assert fake.cons["Rete-LTE-usb0"]["s"]["ipv4.route-metric"] == "100"
assert n.get_status()["internet_device"] == "usb0"
print("priorita' OK")

# --- disabilitare LTE mentre si perde internet -> ripristino
def lose_internet_when_lte_off(orig=fake.down_dev):
    def f(dev):
        orig(dev)
        if dev == "usb0":
            INTERNET["ok"] = False
    return f
fake.down_dev = lose_internet_when_lte_off()
ok = n.change_interfaces({"ethernet": True, "wifi": False, "lte": False}, ["lte", "wifi", "ethernet"], print)
fake.down_dev = FakeNM.down_dev.__get__(fake)
INTERNET["ok"] = True
assert not ok and n.load_settings()["enabled"]["lte"] is True and fake.radio
print("ripristino interfacce OK")
n.apply_interfaces(n.load_settings())
assert fake.devices["usb0"]["con"] == "Rete-LTE-usb0"

# --- WiFi: scansione
nets = n.wifi_scan()
assert [x["ssid"] for x in nets] == ["Casa", "Ufficio", "Vicino"]

# --- WiFi: password errata -> profilo nuovo cancellato, torna a Casa
ok = n.wifi_connect("Ufficio", "sbagliata1", False, "WPA3", print)
assert not ok and "Ufficio" not in fake.cons and fake.devices["wlan0"]["con"] == "preconfigured"
print("wifi errata OK")

# --- WiFi: connessione riuscita, WPA3 -> sae, metrica WiFi
ok = n.wifi_connect("Ufficio", "ufficio123", False, "WPA3", print)
assert ok and fake.devices["wlan0"]["con"] == "Ufficio"
assert fake.cons["Ufficio"]["s"]["802-11-wireless-security.key-mgmt"] == "sae"
assert fake.cons["Ufficio"]["s"]["ipv4.route-metric"] == "200"
print("wifi ok OK")

# --- WiFi esistente con password sbagliata -> ripristina la password vecchia
ok = n.wifi_connect("Casa", "cambiata99", False, "WPA2", print)
assert not ok and fake.cons["preconfigured"]["s"]["802-11-wireless-security.psk"] == "passwordcasa"
assert fake.devices["wlan0"]["con"] == "Ufficio"
print("wifi esistente OK")

saved = n.wifi_profiles()
assert sorted(p["ssid"] for p in saved) == ["Casa", "Ufficio"]
ok, _ = n.wifi_forget(fake.cons["Ufficio"]["uuid"])
assert ok and "Ufficio" not in fake.cons

# --- hotspot
st = n.load_settings()
n.hotspot_start(st)
assert n.hotspot_active() and fake.cons["Rete-Hotspot"]["s"]["802-11-wireless.mode"] == "ap"
assert fake.cons["Rete-Hotspot"]["s"]["ssid"] if "ssid" in fake.cons["Rete-Hotspot"]["s"] else True
# con hotspot attivo la scansione usa la cache
assert [x["ssid"] for x in n.wifi_scan()] == ["Casa", "Ufficio", "Vicino"]
assert n.get_status()["hotspot"]["active"]
# connessione dall'hotspot a una rete: ok
ok = n.wifi_connect("Casa", "", False, "WPA2", print)
assert ok and not n.hotspot_active()
print("hotspot OK")
assert n.change_hotspot(True, "BASE-TEST", "segreta123", 60, print)
assert fake.cons["Rete-Hotspot"]["s"]["802-11-wireless.ssid"] == "BASE-TEST"

# --- LTE con modem simulato
n.find_at_port = lambda settings: "/dev/ttyUSB2"
answers = {
    "AT+CGMM": (True, ["Air780E"]),
    "AT+CPIN?": (True, ["+CPIN: READY"]),
    "AT+CSQ": (True, ["+CSQ: 20,99"]),
    "AT+COPS?": (True, ['+COPS: 0,0,"I TIM",7']),
    "AT+CEREG?": (True, ["+CEREG: 0,1"]),
    "AT+CGDCONT?": (True, ['+CGDCONT: 1,"IP","ibox.tim.it","0.0.0.0",0,0']),
}
sent = []
def fake_at(port, command, timeout=5):
    sent.append(command)
    return answers.get(command, (True, []))
n.at_command = fake_at
lte = n.lte_status()
print(lte)
assert lte["operator"] == "I TIM" and lte["technology"] == "4G" and lte["signal_dbm"] == -73 and lte["apn"] == "ibox.tim.it"
assert lte["registration"].startswith("registrato")

assert n.change_lte("wap.tim.it", None, print)
assert any("wap.tim.it" in c for c in sent)

# PIN: provato una sola volta se errato
answers["AT+CPIN?"] = (True, ["+CPIN: SIM PIN"])
answers['AT+CPIN="1111"'] = (False, ["+CME ERROR: 16"])
sent.clear()
assert not n.change_lte("wap.tim.it", "1111", print)
assert sent.count('AT+CPIN="1111"') == 1
sent.clear()
assert n.lte_pin_check(n.load_settings()).startswith("PIN errato")
assert 'AT+CPIN="1111"' not in sent
print("LTE OK")

ok, lines = n.lte_manual_at("rm -rf /")
assert not ok

# --- modem gestito da ModemManager (device gsm): profilo gsm con APN, niente AT
fake.devices["cdc-wdm0"] = {"type": "gsm", "state": "disconnected", "con": None, "autoconnect": True}
del fake.devices["usb0"]
n.apply_interfaces(n.load_settings(), print)
assert fake.cons["Rete-LTE-cdc-wdm0"]["type"] == "gsm" and fake.cons["Rete-LTE-cdc-wdm0"]["s"]["gsm.apn"] == "wap.tim.it"
assert fake.devices["cdc-wdm0"]["con"] == "Rete-LTE-cdc-wdm0"
sent.clear()
assert n.change_lte("internet.it", None, print)
assert fake.cons["Rete-LTE-cdc-wdm0"]["s"]["gsm.apn"] == "internet.it" and not any("CGDCONT" in c for c in sent)
print("gsm OK")

# --- modem solo seriale: comando di attivazione, una volta per avvio
del fake.devices["cdc-wdm0"]
n.modem_port_candidates = lambda: ["/dev/ttyUSB0"]
assert n.modem_without_network() and n.get_status()["lte_serial_only"]
sent.clear()
assert n.change_lte("internet.it", None, print, "AT+RNDISTEST=1")
assert sent.count("AT+RNDISTEST=1") == 1
n.lte_activate(n.load_settings())
assert sent.count("AT+RNDISTEST=1") == 1          # non ripetuto
st = n.lte_status()
assert st["activation_command"] == "AT+RNDISTEST=1" and st["serial_only"]
print("attivazione OK")

print("\nTUTTI I TEST OK")
