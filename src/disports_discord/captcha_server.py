from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse


class CaptchaHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: any) -> None:
        # Prevent spamming the console with HTTP requests
        pass

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()

            rq_data_js = ""
            if self.server.rqdata:
                rq_data_js = f"rqdata: {json.dumps(self.server.rqdata)},"

            sitekey_js = json.dumps(self.server.sitekey)

            html = f"""<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0">
    <title>Disports Security Check</title>
    <script src="https://js.hcaptcha.com/1/api.js?onload=onHcaptchaLoad&render=explicit&host=discord.com" async defer></script>
    <style>
        body {{
            background-color: #36393f;
            color: #ffffff;
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
        }}
        .container {{
            text-align: center;
            padding: 20px;
            background: #2f3136;
            border-radius: 8px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.2);
            width: 90%;
            max-width: 400px;
        }}
        h2 {{
            margin-bottom: 20px;
            font-weight: 500;
        }}
        p {{
            color: #b9bbbe;
            font-size: 14px;
            margin-bottom: 20px;
        }}
        #captcha {{
            display: inline-block;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h2>Security Check</h2>
        <p>Please solve the hCaptcha puzzle below to continue logging in to Disports.</p>
        <div id="captcha"></div>
    </div>
    <script>
        function gotToken(token) {{
            window.location.href = '/solved?token=' + encodeURIComponent(token);
        }}
        window.onHcaptchaLoad = function() {{
            hcaptcha.render('captcha', {{
                sitekey: {sitekey_js},
                theme: 'dark',
                callback: gotToken,
                {rq_data_js}
            }});
        }};
    </script>
</body>
</html>
"""
            self.wfile.write(html.encode("utf-8"))

        elif parsed.path == "/solved":
            query = parse_qs(parsed.query)
            token_list = query.get("token")
            token = token_list[0] if token_list else ""

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()

            html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Verification Successful</title>
    <style>
        body {
            background-color: #36393f;
            color: #43b581;
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            text-align: center;
        }
        .container {
            padding: 30px;
            background: #2f3136;
            border-radius: 8px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.2);
            width: 90%;
            max-width: 400px;
        }
        h1 {
            margin-top: 0;
            font-size: 24px;
        }
        p {
            color: #b9bbbe;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>✓ Success</h1>
        <p>Security check solved successfully! You can now close this browser tab and return to the Disports application.</p>
    </div>
</body>
</html>
"""
            self.wfile.write(html.encode("utf-8"))

            if token and self.server.callback:
                self.server.callback(token)

            # Shutdown the server asynchronously so we can finish sending this response
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self.send_response(404)
            self.end_headers()


class CaptchaServer(HTTPServer):
    def __init__(self, sitekey: str, rqdata: str, callback: callable) -> None:
        self.sitekey = sitekey
        self.rqdata = rqdata
        self.callback = callback
        super().__init__(("127.0.0.1", 0), CaptchaHandler)


def start_captcha_server(sitekey: str, rqdata: str, callback: callable) -> tuple[CaptchaServer, str]:
    server = CaptchaServer(sitekey, rqdata, callback)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}/"
