import os

from qgis.core import QgsProject, Qgis, QgsMessageOutput, QgsApplication

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon

from carto.gui.dataitemprovider import DataItemProvider
from carto.core.layers import LayerTracker

pluginPath = os.path.dirname(__file__)


def icon(f):
    return QIcon(os.path.join(pluginPath, "img", f))


CartoIcon = icon("carto.png")


class CartoPlugin(object):
    def __init__(self, iface):
        self.iface = iface
        self.tracker = LayerTracker.instance()
        self.dip = None

    def initGui(self):
        self.dip = DataItemProvider()
        QgsApplication.instance().dataItemProviderRegistry().addProvider(self.dip)

        QgsProject.instance().layerRemoved.connect(self.tracker.layer_removed)
        QgsProject.instance().layerWasAdded.connect(self.tracker.layer_added)

    def unload(self):
        QgsApplication.instance().dataItemProviderRegistry().removeProvider(self.dip)
        self.dip = None

        QgsProject.instance().layerRemoved.disconnect(self.tracker.layer_removed)
        QgsProject.instance().layerWasAdded.disconnect(self.tracker.layer_added)
