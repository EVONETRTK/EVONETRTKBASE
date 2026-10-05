exec(open("test_network_page.py", encoding="utf-8").read().split("fake = FakeNM()")[0])
fake = FakeNM(); n.run_cmd = fake
clock = {"t": 1000.0}; n.time.time = lambda: clock["t"]
n._CACHE["enabled"] = True
fake.log.clear()
for _ in range(5): n.list_devices(); n.hotspot_active(); n.get_radio_wifi()
assert len([a for a in fake.log if a[0] == "nmcli"]) == 2, fake.log   # hotspot dallo stato interfacce
calls = [a for a in fake.log if a[0] == "nmcli"]
assert len(calls) == 2, calls
n.nm("radio", "wifi", "off")                       # modifica -> cache svuotata
assert n.get_radio_wifi() is False
clock["t"] += 6; fake.log.clear(); n.list_devices(); assert len(fake.log) == 1   # scaduta dopo 5 s
d = n.list_devices(); d[0]["state"] = "xxx"; assert n.list_devices()[0]["state"] != "xxx"   # copia
print("CACHE OK")
