import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "Install"))
import network_page as n
# Air780E reale: ttyACM0-2 (19d1, 1-1.2), eth0 rndis; CH340 della scheda ttyUSB0 (1a86, 1-1.3)
USB = {"ttyACM0": "/u/1-1.2", "ttyACM1": "/u/1-1.2", "ttyACM2": "/u/1-1.2", "ttyUSB0": "/u/1-1.3"}
SYS = {"/u/1-1.2/idVendor": "19d1", "/u/1-1.2/manufacturer": "EigenComm", "/u/1-1.2/product": "EigenComm Compo",
       "/u/1-1.3/idVendor": "1a86", "/u/1-1.3/product": "USB Serial"}
n.tty_usb_device = lambda t: USB.get(t)
n.read_sys = lambda p: SYS.get(p.replace("\\", "/"), "")
n.receiver_usb_devices = lambda: set()
n.os.listdir = lambda p: ["ttyACM2", "ttyUSB0", "ttyACM10" if False else "ttyACM1", "ttyACM0"]
for lte in ({"/u/1-1.2"}, set()):          # con eth0 del modem e senza (solo seriali)
    n.lte_usb_devices = lambda lte=lte: lte
    c = n.modem_port_candidates()
    print(c)
    assert c == ["/dev/ttyACM0"], c
print("SOLO ttyACM0, CH340 ESCLUSO: OK")
