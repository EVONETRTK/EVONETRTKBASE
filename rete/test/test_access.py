import json
exec(open("test_network_page.py", encoding="utf-8").read().split("fake = FakeNM()")[0])
fake = FakeNM(); n.run_cmd = fake
real_run = n.run
ts = '{"BackendState":"Running","Self":{"DNSName":"evonetrtkbase.tail1a2b.ts.net.","TailscaleIPs":["100.64.0.10","fd7a:115c::1"],"Online":true}}'
n.run = lambda args, timeout=15: ts if args[:2] == ["tailscale", "status"] else real_run(args, timeout)
open(n.RTKBASE_SETTINGS, "w").write("[general]\nweb_port='80'\n")
n.apply_interfaces(n.load_settings())
a = n.get_status()["access"]
print(a)
assert a["tailscale"] == {"ip": "100.64.0.10", "name": "evonetrtkbase.tail1a2b.ts.net", "online": True, "account": None}, a["tailscale"]
ts2 = json.loads(ts); ts2["Self"]["UserID"] = 7; ts2["User"] = {"7": {"LoginName": "utente@example.com"}}; ts = json.dumps(ts2); n._access_cache["time"] = 0
assert n.tailscale_info()["account"] == "utente@example.com"
assert [l["ip"] for l in a["local"]] == ["10.0.0.5"] and a["local"][0]["kind"] == "wifi"   # niente LTE
assert a["hotspot_ip"] == "10.42.0.1" and a["port"] == "80"
print("ACCESSO OK")

# password del pannello di fabbrica e note di accesso
from werkzeug.security import generate_password_hash
open(n.RTKBASE_SETTINGS, "w").write("[general]\nweb_port='80'\nweb_password_hash=%s\n" % generate_password_hash("admin"))
assert n.web_password_is_default() is True
open(n.RTKBASE_SETTINGS, "w").write("[general]\nweb_password_hash=%s\n" % generate_password_hash("altra"))
assert n.web_password_is_default() is False
s = n.load_settings(); s["access_notes"] = "SSH filippo / prova"; n.save_settings(s)
a = n.get_status()["access"]
assert a["notes"] == "SSH filippo / prova" and a["hotspot_password"] and "web_password_hash" not in a
print("CREDENZIALI OK")
