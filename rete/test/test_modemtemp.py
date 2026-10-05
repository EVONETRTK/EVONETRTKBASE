exec(open("test_network_page.py", encoding="utf-8").read().split("fake = FakeNM()")[0])
answers = {}
n.modem_at = lambda settings, cmd: answers[cmd]
st = n.load_settings()
answers['AT+ECADC="TEMP"'] = (True, ["+ECADC: TEMP, 60", "OK"])
assert n.modem_temperature(st) == 60.0
answers['AT+ECADC="TEMP"'] = (False, ["nessuna risposta dal modem"])
assert n.modem_temperature(st) is None and n.MODEM_TEMP["supported"]      # risposta mancata: si riprova
answers['AT+ECADC="TEMP"'] = (False, ["ERROR"])
assert n.modem_temperature(st) is None and not n.MODEM_TEMP["supported"]  # non supportato: basta
answers['AT+ECADC="TEMP"'] = (True, ["+ECADC: TEMP, 61", "OK"])
assert n.modem_temperature(st) is None
# allarme modem nel controllo temperature
n.MODEM_TEMP["supported"] = True
events = []; n.log = lambda m: events.append(m)
n.pi_temperature = lambda: 50.0
n.LTE_RADIO["on"] = True
answers["AT+CBC"] = (True, ["+CBC: 3866", "OK"])
answers['AT+ECADC="TEMP"'] = (True, ["+ECADC: TEMP, 82", "OK"])
n.TEMPS_FILE = os.path.join(tmp, "t.json")
temps = {}
n.check_temperatures(st, temps, 0, False)
assert temps["modem"] == 82.0 and temps["modem_mv"] == 3866 and "modem LTE alta" in events[-1], events
answers['AT+ECADC="TEMP"'] = (True, ["+ECADC: TEMP, 70", "OK"])
n.check_temperatures(st, temps, 60, False)
assert "modem LTE rientrata" in events[-1]
n.LTE_RADIO["on"] = False
n.check_temperatures(st, temps, 120, False)
assert temps["modem"] is None
print("TEMPERATURA MODEM OK")
