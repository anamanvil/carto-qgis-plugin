"""
Code adapted from the Felt QGIS Plugin
Original code at https://github.com/felt/qgis-plugin
"""

from http.server import BaseHTTPRequestHandler, HTTPServer

import os
import json
import requests
import hashlib
import base64
import urllib.parse as urlparse
import urllib.request
import secrets
from qgis.PyQt.QtCore import QThread, pyqtSignal, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import QgsBlockingNetworkRequest


OAUTH_BASE = "/auth.carto.com"


CLIENT_ID = "FhFSweQg2JzGgbfVhiyOCB64ipQZvAKo"

REDIRECT_PORT = 5000
REDIRECT_URL = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
SCOPE = " ".join(
    [
        "profile",
        "email",
        "read:current_user",
        "update:current_user",
        "read:connections",
        "write:connections",
        "read:maps",
        "write:maps",
        "read:account",
        "admin:account",
    ]
)

TOKEN_URL = "https://auth.carto.com/oauth/token"


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse.urlparse(self.path)
        query_params = urlparse.parse_qs(parsed_path.query)

        self.server.error = None
        if parsed_path.path == "/callback":
            code = query_params.get("code", [None])[0]
            if code:
                body = {
                    "grant_type": "authorization_code",
                    "client_id": CLIENT_ID,
                    "code_verifier": self.server.code_verifier,
                    "code": code,
                    "redirect_uri": REDIRECT_URL,
                }

                request = QgsBlockingNetworkRequest()
                token_body = urlparse.urlencode(body).encode()

                network_request = QNetworkRequest(QUrl(TOKEN_URL))
                network_request.setHeader(
                    QNetworkRequest.ContentTypeHeader,
                    "application/x-www-form-urlencoded",
                )

                result_code = request.post(
                    network_request, data=token_body, forceRefresh=True
                )
                if result_code != QgsBlockingNetworkRequest.NoError:
                    self.server.error = (
                        request.reply().content().data().decode()
                        or request.reply().errorString()
                    )
                    self.send_response(302)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"Authorization failed.")
                    self.server.access_token = None
                    return

                resp = json.loads(request.reply().content().data().decode())

                access_token = resp.get("access_token")

                if not access_token:
                    self.server.error = "Could not find access_token in reply"
                    self.send_response(302)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"Authorization failed.")
                    self.server.access_token = None
                    return

                self.server.access_token = access_token

                html_file = os.path.join(
                    os.path.dirname(__file__),
                    "..",
                    "gui",
                    "webpages",
                    "authorized.html",
                )
                file_url = urlparse.urljoin(
                    "file:", urllib.request.pathname2url(html_file)
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                with open(html_file, "r") as f:
                    html = f.read()
                for img in ["carto-logo.png", "bg-image.png"]:
                    img_path = os.path.join(
                        os.path.dirname(__file__),
                        "..",
                        "gui",
                        "webpages",
                        img,
                    )
                    base64_img = base64.b64encode(open(img_path, "rb").read()).decode(
                        "utf-8"
                    )
                    html = html.replace(img, f"data:image/png;base64,{base64_img}")

                self.wfile.write(html.encode())
            else:
                self.send_response(302)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Authorization canceled or failed.")
                self.server.access_token = None
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")


def auth0_url_encode(byte_data):
    """
    Safe encoding handles + and /, and also replace = with nothing
    :param byte_data:
    :return:
    """
    return base64.urlsafe_b64encode(byte_data).decode("utf-8").replace("=", "")


def generate_challenge(a_verifier):
    return auth0_url_encode(hashlib.sha256(a_verifier.encode()).digest())


class OAuthWorkflow(QThread):
    """
    A custom thread which handles the OAuth workflow.

    When the thread is run either the finished or error_occurred signals
    will be emitted
    """

    finished = pyqtSignal(str)
    error_occurred = pyqtSignal()

    def __init__(self):
        super().__init__()

        self.server = None

        verifier = auth0_url_encode(secrets.token_bytes(32))
        challenge = generate_challenge(verifier)
        state = auth0_url_encode(secrets.token_bytes(32))

        base_url = "https://auth.carto.com/authorize?"
        url_parameters = {
            "audience": "carto-cloud-native-api",
            "scope": SCOPE,
            "response_type": "code",
            "redirect_uri": REDIRECT_URL,
            "client_id": CLIENT_ID,
            "code_challenge": challenge.replace("=", ""),
            "code_challenge_method": "S256",
            "state": state,
        }
        self.code_verifier = verifier
        self.authorization_url = base_url + urlparse.urlencode(url_parameters)

    @staticmethod
    def force_stop():
        """
        Forces the local server to gracefully shutdown
        """
        # we have to dummy a dummy request in order to abort the
        # blocking handle_request() loop
        # pylint: disable=missing-timeout
        requests.get(REDIRECT_URL)
        # pylint: enable=missing-timeout

    def close_server(self):
        """
        Closes and cleans up the local server
        """
        self.server.server_close()

        del self.server
        self.server = None

    def run(self):
        """
        Starts the server thread
        """
        self.server = HTTPServer(("127.0.0.1", REDIRECT_PORT), CallbackHandler)
        self.server.code_verifier = self.code_verifier
        self.server.access_token = None
        self.server.error = None
        QDesktopServices.openUrl(QUrl(self.authorization_url))

        self.server.handle_request()

        if self.server.access_token is None:
            self.error_occurred.emit()
        else:
            self.finished.emit(self.server.access_token)
