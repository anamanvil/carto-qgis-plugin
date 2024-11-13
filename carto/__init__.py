import os
import sys

extlibs = os.path.abspath(os.path.dirname(__file__) + "/libs")
if os.path.exists(extlibs) and extlibs not in sys.path:
    sys.path.insert(0, extlibs)


def classFactory(iface):
    from carto.plugin import CartoPlugin

    return CartoPlugin(iface)
