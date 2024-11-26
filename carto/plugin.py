import os

from qgis.core import QgsProject, QgsApplication, Qgis

from qgis.PyQt.QtWidgets import QMenu, QAction
from qgis.PyQt.QtGui import QIcon

from carto.gui.dataitemprovider import DataItemProvider
from carto.gui.authorizationsuccessdialog import AuthorizationSuccessDialog
from carto.core.layers import LayerTracker
from carto.core.api import CartoApi

from qgis.utils import iface

from carto.gui.authorization_manager import AUTHORIZATION_MANAGER

pluginPath = os.path.dirname(__file__)


def icon(f):
    return QIcon(os.path.join(pluginPath, "gui", "img", f))


CARTO_ICON = icon("carto.svg")


class CartoPlugin(object):
    def __init__(self, iface):
        self.iface = iface
        self.tracker = LayerTracker.instance()
        self.dip = None

    def initGui(self):
        web_menu = self.iface.webMenu()
        self.carto_menu = QMenu("CARTO")
        web_menu.addMenu(self.carto_menu)

        self.carto_menu.addAction(AUTHORIZATION_MANAGER.login_action)

        self.login_action = QAction()
        self.login_action.setIcon(CARTO_ICON)
        self.login_action.triggered.connect(self.login)
        self.iface.addWebToolBarIcon(self.login_action)

        self.dip = DataItemProvider()
        QgsApplication.instance().dataItemProviderRegistry().addProvider(self.dip)

        QgsProject.instance().layerRemoved.connect(self.tracker.layer_removed)
        QgsProject.instance().layerWasAdded.connect(self.tracker.layer_added)

    def unload(self):
        QgsApplication.instance().dataItemProviderRegistry().removeProvider(self.dip)
        self.dip = None

        QgsProject.instance().layerRemoved.disconnect(self.tracker.layer_removed)
        QgsProject.instance().layerWasAdded.disconnect(self.tracker.layer_added)

        self.iface.removeWebToolBarIcon(self.login_action)
        self.carto_menu.clear()
        self.iface.webMenu().removeAction(self.carto_menu.menuAction())
        self.carto_menu = None

    def login(self):
        if AUTHORIZATION_MANAGER.is_authorized():
            try:
                CartoApi.instance().user()
                dlg = AuthorizationSuccessDialog(iface.mainWindow())
                dlg.exec_()
                if dlg.logout:
                    AUTHORIZATION_MANAGER.deauthorize()
            except:
                AUTHORIZATION_MANAGER.login()
        else:
            AUTHORIZATION_MANAGER.login()
