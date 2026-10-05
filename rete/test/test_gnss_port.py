import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "Install"))
import network_page as n

tmp = tempfile.mkdtemp()
n.RTKBASE_SETTINGS = os.path.join(tmp, "settings.conf")
n.GNSS_RULE = os.path.join(tmp, "92-elt-gnss-port.rules")
n.log = print

# ttyUSB0-2 = modem Air780E (usb 1-1.1, ha anche usb0), ttyUSB3 = ricevitore CH340 (usb 1-1.2)
USB = {"ttyUSB0": "/sys/1-1.1", "ttyUSB1": "/sys/1-1.1", "ttyUSB2": "/sys/1-1.1", "ttyUSB3": "/sys/1-1.2"}
DEV = {"/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyUSB2", "/dev/ttyUSB3", "/dev/serial0"}
n.tty_usb_device = lambda tty: USB.get(tty)
n.lte_usb_devices = lambda: {"/sys/1-1.1"}
real_read = n.read_sys
n.read_sys = lambda p: {"/sys/1-1.1/product": "Air780E", "/sys/1-1.2/product": "USB Serial"}.get(p.replace("\\", "/"), real_read(p))
real_exists = os.path.exists
n.os.path.exists = lambda p: p in DEV or (not p.startswith("/dev/") and real_exists(p))
n.os.path.realpath = lambda p: p
udev_calls = []


def fake_run(args, timeout=None):
    udev_calls.append(args)
    if args[:3] == ["udevadm", "info", "-q"]:
        if args[-1] == "/dev/ttyUSB3":
            return "ID_SERIAL=1a86_USB_Serial\nID_USB_INTERFACE_NUM=00\nID_VENDOR_ID=1a86\n"
    return ""


n.run = fake_run


def set_port(port):
    open(n.RTKBASE_SETTINGS, "w").write("[main]\ncom_port='%s'\ncom_port_settings='115200:8:n:1'\n" % port)


# 1) ricevitore su ttyUSB3 -> regola per ID_SERIAL + interfaccia
set_port("ttyUSB3")
assert n.receiver_port_status() == {"com_port": "ttyUSB3", "numbered": True, "link_ready": False}
assert n.pin_receiver_port() == "ttyGNSS"
rule = open(n.GNSS_RULE).read()
print(rule)
assert 'ENV{ID_SERIAL}=="1a86_USB_Serial", ENV{ID_USB_INTERFACE_NUM}=="00", SYMLINK+="ttyGNSS"' in rule
assert ["udevadm", "control", "--reload-rules"] in udev_calls

# gia' scritta: non riscrive e non ricarica udev
udev_calls.clear()
assert n.pin_receiver_port() == "ttyGNSS"
assert ["udevadm", "control", "--reload-rules"] not in udev_calls

# con il link creato la pagina dice "pronto"
DEV.add("/dev/ttyGNSS")
n.os.path.realpath = lambda p: "/dev/ttyUSB3" if p == "/dev/ttyGNSS" else p
assert n.receiver_port_status()["link_ready"]

# 2) com_port finito su una porta del modem -> nessuna regola
os.remove(n.GNSS_RULE)
DEV.discard("/dev/ttyGNSS")
set_port("ttyUSB1")
assert n.pin_receiver_port() is None and not os.path.exists(n.GNSS_RULE)

# 3) gia' ttyGNSS o ricevitore su UART GPIO -> niente da fare
for port in ("ttyGNSS", "serial0", ""):
    set_port(port)
    assert n.pin_receiver_port() is None
    assert not n.receiver_port_status()["numbered"]

print("PORTA RICEVITORE OK")
