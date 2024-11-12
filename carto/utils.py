from qgis.PyQt.QtCore import QSettings

NAMESPACE = "carto"
MAXROWS = "maxrows"
TOKEN = "token"

setting_types = {}


def setSetting(name, value):
    QSettings().setValue(f"{NAMESPACE}/{name}", value)


def setting(name):
    v = QSettings().value(f"{NAMESPACE}/{name}", None)
    if setting_types.get(name, str) == bool:
        return str(v).lower() == str(True).lower()
    else:
        return v
