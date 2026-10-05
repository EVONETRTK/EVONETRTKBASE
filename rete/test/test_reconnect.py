exec(open("test_network_page.py", encoding="utf-8").read().split("fake = FakeNM()")[0])
fake = FakeNM(); n.run_cmd = fake
calls = []
real_run = n.run
n.run = lambda args, timeout=15: (calls.append(args) if args[:2] == ["systemctl", "try-restart"] else None) or real_run(args, timeout)
n.apply_interfaces(n.load_settings())
before = n.internet_device()
fake.devices["wlan0"]["state"] = "disconnected"; fake.cons["preconfigured"]["dev"] = None; fake.devices["wlan0"]["con"] = None
after = n.internet_device()
print(before, "->", after)
assert before == "wlan0" and after == "usb0"
n.reconnect_outgoing(before, after)
assert calls and "str2str_ntrip_A.service" in calls[0] and "str2str_rtcm_client.service" in calls[0]
print("RICONNESSIONE NTRIP OK")
