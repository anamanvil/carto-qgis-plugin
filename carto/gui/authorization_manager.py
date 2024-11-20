"""
Code taken from the Felt QGIS Plugin
Original code at https://github.com/felt/qgis-plugin
"""

import platform
from typing import Optional

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject, pyqtSignal, QTimer, QDate
from qgis.PyQt.QtNetwork import QNetworkReply
from qgis.PyQt.QtWidgets import QAction, QPushButton
from qgis.core import Qgis, QgsSettings, QgsApplication
from qgis.gui import QgsMessageBarItem
from qgis.utils import iface

from carto.gui.authorizedialog import AuthorizeDialog
from carto.core.auth import OAuthWorkflow
from carto.core.utils import setting, TOKEN
from carto.core.enums import AuthState
from carto.core.user import User
from carto.core.api import CartoApi

AUTH_CONFIG_ID = "carto_auth_id"
AUTH_CONFIG_EXPIRY = "carto_auth_expiry"


class AuthorizationManager(QObject):
    """
    Handles the GUI component of client authorization
    """

    authorized = pyqtSignal()
    authorization_failed = pyqtSignal()
    status_changed = pyqtSignal(AuthState)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.status: AuthState = AuthState.NotAuthorized
        self._workflow: Optional[OAuthWorkflow] = None
        self.oauth_close_timer: Optional[QTimer] = None

        self._authorizing_message = None
        self._authorization_failed_message = None

        self.queued_callbacks = []
        self.user: Optional[User] = None

        self.login_action = QAction(self.tr("Sign In…"))
        self.login_action.triggered.connect(self.login)

    @staticmethod
    def remove_api_token():
        """
        Remove stored API token
        """
        if platform.system() == "Darwin":
            # remove stored plain text tokens on MacOS
            QgsSettings().remove("Carto/token", QgsSettings.Plugins)
        else:
            QgsApplication.authManager().removeAuthSetting(AUTH_CONFIG_ID)

    @staticmethod
    def store_api_token(token: str, expiry: int) -> bool:
        """
        Stores the API token in the secure QGIS password store, IF available

        Returns True if the key could be stored
        """
        expiry_day = QDate.currentDate().addDays(int(expiry / 60 / 60 / 24))
        if platform.system() == "Darwin":
            # store tokens in plain text on MacOS as keychain isn't
            # available due to MacOS security
            QgsSettings().setValue("Carto/token", token, QgsSettings.Plugins)
            QgsSettings().setValue(
                "Carto/token_expiry",
                expiry_day.toString("yyyy-MM-dd"),
                QgsSettings.Plugins,
            )
        else:
            QgsApplication.authManager().storeAuthSetting(AUTH_CONFIG_ID, token, True)
            QgsApplication.authManager().storeAuthSetting(
                AUTH_CONFIG_EXPIRY, expiry_day.toString("yyyy-MM-dd"), True
            )
        return True

    @staticmethod
    def retrieve_api_token() -> Optional[str]:
        """
        Retrieves a previously stored API token, if available

        Returns None if no stored token is available
        """
        if platform.system() == "Darwin":
            api_token = QgsSettings().value(
                "Carto/token", None, str, QgsSettings.Plugins
            )
            token_expiry = QgsSettings().value(
                "Carto/token_expiry", None, str, QgsSettings.Plugins
            )
            if not api_token:
                api_token = None
        else:
            api_token = (
                QgsApplication.authManager().authSetting(
                    AUTH_CONFIG_ID, defaultValue="", decrypt=True
                )
                or None
            )
            token_expiry = (
                QgsApplication.authManager().authSetting(
                    AUTH_CONFIG_EXPIRY, defaultValue="", decrypt=True
                )
                or None
            )

        if token_expiry:
            token_expiry_date = QDate.fromString(token_expiry, "yyyy-MM-dd")
            if token_expiry_date <= QDate.currentDate():
                api_token = None
        else:
            api_token = None

        return api_token

    def _set_status(self, status: AuthState):
        """
        Sets the current authorization status
        """
        if self.status == status:
            return

        self.status = status
        self.status_changed.emit(self.status)

        if self.status == AuthState.NotAuthorized:
            self.login_action.setText(self.tr("Sign In…"))
            self.login_action.setEnabled(True)
            self.user = None
        elif self.status == AuthState.Authorizing:
            self.login_action.setText(self.tr("Authorizing…"))
            self.login_action.setEnabled(False)
            self.user = None
        elif self.status == AuthState.Authorized:
            self.login_action.setText(self.tr("Log Out"))
            self.login_action.setEnabled(True)

    def is_authorized(self) -> bool:
        """
        Returns True if the client is authorized
        """
        return self.status == AuthState.Authorized

    def login(self):
        """
        Called when the login action is triggered
        """
        if self.status == AuthState.NotAuthorized:
            self.attempt_authorize()
        elif self.status == AuthState.Authorized:
            self.deauthorize()

    def authorization_callback(self, callback) -> bool:
        """
        Returns True if the client is already authorized, or False
        if an authorization is in progress and the operation needs to wait
        for the authorized signal before proceeding
        """
        if self.status == AuthState.Authorized:
            callback()
            return True

        self.queued_callbacks.append(callback)
        self.attempt_authorize()
        return False

    def deauthorize(self):
        """
        Deauthorizes the client
        """
        self._set_status(AuthState.NotAuthorized)
        CartoApi.instance().set_token(None)
        AuthorizationManager.remove_api_token()

    def attempt_authorize(self):
        """
        Tries to authorize the client, using previously fetched token if
        available. Otherwise shows the login dialog to the user.
        """
        previous_token = AuthorizationManager.retrieve_api_token()
        if previous_token:
            self._cleanup_messages()

            self._set_status(AuthState.Authorized)
            CartoApi.instance().set_token(previous_token)
            self.authorized.emit()
            user_reply = CartoApi.instance().user()
            self._set_user_details(user_reply)
            return

        self.show_authorization_dialog()

    def show_authorization_dialog(self):
        """
        Shows the authorization dialog before commencing the authorization
        process
        """
        dlg = AuthorizeDialog()
        if dlg.exec_():
            try:
                CartoApi.instance().set_token(setting(TOKEN))
                CartoApi.instance().get_json("https://accounts.app.carto.com/users/me")
                self._set_status(AuthState.Authorized)
            except Exception:
                self._cleanup_messages()
                iface.messageBar().pushMessage(
                    "Login failed",
                    "Please check your token and try again",
                    level=Qgis.Warning,
                    duration=10,
                )
            else:
                self._cleanup_messages()
                iface.messageBar().pushMessage(
                    "Login successful",
                    "You are now logged in",
                    level=Qgis.Success,
                    duration=10,
                )
            # self.start_authorization_workflow()
        else:
            self.queued_callbacks = []

    def start_authorization_workflow(self):
        """
        Start an authorization process
        """

        assert not self._workflow

        self._cleanup_messages()

        self._workflow = OAuthWorkflow()
        self._workflow.error_occurred.connect(self._authorization_error_occurred)
        self._workflow.finished.connect(self._authorization_success)

        self._set_status(AuthState.Authorizing)

        self._authorizing_message = QgsMessageBarItem(
            self.tr("Carto"), self.tr("Authorizing…"), Qgis.MessageLevel.Info
        )
        iface.messageBar().pushItem(self._authorizing_message)

        self._workflow.start()
        return False

    def _cleanup_messages(self):
        """
        Removes outdated message bar items
        """
        if self._authorizing_message and not sip.isdeleted(self._authorizing_message):
            iface.messageBar().popWidget(self._authorizing_message)
            self._authorizing_message = None
        if self._authorization_failed_message and not sip.isdeleted(
            self._authorization_failed_message
        ):
            iface.messageBar().popWidget(self._authorization_failed_message)
            self._authorization_failed_message = None

    def _authorization_error_occurred(self, error: str):
        """
        Triggered when an authorization error occurs
        """
        self.queued_callbacks = []
        self._cleanup_messages()

        self._clean_workflow()

        self._set_status(AuthState.NotAuthorized)
        login_error = self.tr("Authorization error - {}".format(error))

        self._authorization_failed_message = QgsMessageBarItem(
            self.tr("Carto"), login_error, Qgis.MessageLevel.Critical
        )

        retry_button = QPushButton(self.tr("Try Again"))
        retry_button.clicked.connect(self.show_authorization_dialog)
        self._authorization_failed_message.layout().addWidget(retry_button)

        iface.messageBar().pushItem(self._authorization_failed_message)

        self.queued_callbacks = []
        self.authorization_failed.emit()

    def _authorization_success(self, token: str, expiry: int):
        """
        Triggered when an authorization succeeds
        """
        self._cleanup_messages()

        self._set_status(AuthState.Authorized)
        iface.messageBar().pushSuccess(self.tr("Carto"), self.tr("Authorized"))
        CartoApi.instance().set_token(token)
        AuthorizationManager.store_api_token(token, expiry)

        self._clean_workflow()

        self.authorized.emit()

        user_reply = CartoApi.instance().user()
        self._set_user_details(user_reply)

    def _set_user_details(self, reply: QNetworkReply):
        """
        Sets user details
        """

        if reply.status_code == 401:
            self.deauthorize()
            self.attempt_authorize()
            return

        try:
            reply.raise_for_status()
            self.user = User.from_json(reply.readAll().data().decode())
            callbacks = self.queued_callbacks
            self.queued_callbacks = []
            for callback in callbacks:
                callback()
        except:
            return

    def cleanup(self):
        """
        Must be called when the authorization handler needs to be gracefully
        shutdown (e.g. on plugin unload)
        """
        self._close_auth_server(force_close=True)

    def _clean_workflow(self):
        """
        Cleans up the oauth workflow
        """
        if self._workflow and not sip.isdeleted(self._workflow):
            self.oauth_close_timer = QTimer(self)
            self.oauth_close_timer.setSingleShot(True)
            self.oauth_close_timer.setInterval(1000)
            self.oauth_close_timer.timeout.connect(self._close_auth_server)
            self.oauth_close_timer.start()

    def _close_auth_server(self, force_close=False):
        """
        Gracefully closes and cleans up the oauth workflow
        """
        if self.oauth_close_timer and not sip.isdeleted(self.oauth_close_timer):
            self.oauth_close_timer.timeout.disconnect(self._close_auth_server)
            self.oauth_close_timer.deleteLater()
        self.oauth_close_timer = None

        if self._workflow and not sip.isdeleted(self._workflow):
            if force_close:
                self._workflow.force_stop()

            self._workflow.close_server()
            self._workflow.quit()
            self._workflow.wait()
            self._workflow.deleteLater()

        self._workflow = None


AUTHORIZATION_MANAGER = AuthorizationManager()
