"""Core page, auth, and file-serving handlers for the web channel."""

import hmac
import mimetypes
import os
import re
import time
from urllib.parse import quote

import web

from common.log import logger
from config import conf
from channel.web.web.utils import (
    check_auth,
    create_auth_token,
    get_upload_dir,
    get_workspace_root,
    is_password_enabled,
    json_error,
    json_success,
    read_json_body,
    require_auth,
    session_expire_seconds,
)


class RootHandler:
    def GET(self):
        raise web.seeother('/textbook')


class AuthCheckHandler:
    def GET(self):
        if not is_password_enabled():
            return json_success(auth_required=False)
        return json_success(auth_required=True, authenticated=check_auth())


class AuthLoginHandler:
    def POST(self):
        if not is_password_enabled():
            return json_success()
        try:
            data = read_json_body({})
        except Exception:
            return json_error("Invalid request")
        password = data.get("password", "")
        expected = conf().get("web_password", "")
        if not hmac.compare_digest(password, expected):
            logger.warning("[WebChannel] Invalid login attempt")
            return json_error("Wrong password")
        token = create_auth_token()
        web.setcookie(
            "cow_auth_token",
            token,
            expires=session_expire_seconds(),
            path="/",
            httponly=True,
            samesite="Lax",
        )
        return json_success()


class AuthLogoutHandler:
    def POST(self):
        web.setcookie("cow_auth_token", "", expires=-1, path="/")
        return json_success()


class MessageHandler:
    def POST(self):
        require_auth()
        from channel.web.web.web_channel import WebChannel
        return WebChannel().post_message()


class UploadHandler:
    def POST(self):
        require_auth()
        from channel.web.web.web_channel import WebChannel
        return WebChannel().upload_file()


class UploadsHandler:
    def GET(self, file_name):
        require_auth()
        try:
            upload_dir = get_upload_dir()
            full_path = os.path.normpath(os.path.join(upload_dir, file_name))
            if not os.path.abspath(full_path).startswith(os.path.abspath(upload_dir)):
                raise web.notfound()
            if not os.path.isfile(full_path):
                raise web.notfound()
            content_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"
            web.header('Content-Type', content_type)
            web.header('Cache-Control', 'public, max-age=86400')
            with open(full_path, 'rb') as f:
                return f.read()
        except web.HTTPError:
            raise
        except Exception as e:
            logger.error(f"[WebChannel] Error serving upload: {e}")
            raise web.notfound()


class FileServeHandler:
    def GET(self):
        require_auth()
        try:
            params = web.input(path="")
            file_path = params.path
            if not file_path or not os.path.isabs(file_path):
                raise web.notfound()
            file_path = os.path.realpath(os.path.normpath(file_path))
            workspace_root = os.path.realpath(get_workspace_root())
            if os.path.commonpath([workspace_root, file_path]) != workspace_root:
                raise web.notfound()
            if not os.path.isfile(file_path):
                raise web.notfound()
            content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
            file_name = os.path.basename(file_path)
            web.header('Content-Type', content_type)
            web.header('Content-Disposition', f"inline; filename*=UTF-8''{quote(file_name)}")
            web.header('Cache-Control', 'public, max-age=3600')
            with open(file_path, 'rb') as f:
                return f.read()
        except web.HTTPError:
            raise
        except Exception as e:
            logger.error(f"[WebChannel] Error serving file: {e}")
            raise web.notfound()


class PollHandler:
    def POST(self):
        require_auth()
        from channel.web.web.web_channel import WebChannel
        return WebChannel().poll_response()


class StreamHandler:
    def GET(self):
        require_auth()
        params = web.input(request_id='')
        request_id = params.request_id
        if not request_id:
            raise web.badrequest()

        web.header('Content-Type', 'text/event-stream; charset=utf-8')
        web.header('Cache-Control', 'no-cache')
        web.header('X-Accel-Buffering', 'no')
        web.header('Access-Control-Allow-Origin', '*')

        from channel.web.web.web_channel import WebChannel
        return WebChannel().stream_response(request_id)


class ChatHandler:
    def GET(self):
        web.header('Content-Type', 'text/html; charset=utf-8')
        web.header('Cache-Control', 'no-cache, no-store, must-revalidate')
        web.header('Pragma', 'no-cache')
        file_path = os.path.join(os.path.dirname(__file__), 'chat.html')
        with open(file_path, 'r', encoding='utf-8') as f:
            html = f.read()
        cache_bust = str(int(time.time()))
        html = html.replace('assets/js/console.js', f'assets/js/console.js?v={cache_bust}')
        html = html.replace('assets/css/console.css', f'assets/css/console.css?v={cache_bust}')
        return html


class TextbookPageHandler:
    @staticmethod
    def _expand_includes(html: str, base_dir: str) -> str:
        include_pattern = re.compile(r"<!--#include\s+([A-Za-z0-9_./-]+)\s+-->")

        def _replace(match):
            rel_path = match.group(1)
            full_path = os.path.realpath(os.path.join(base_dir, rel_path))
            root = os.path.realpath(base_dir)
            if os.path.commonpath([root, full_path]) != root:
                return ""
            if not os.path.isfile(full_path):
                logger.warning(f"[WebChannel] Missing textbook partial: {rel_path}")
                return ""
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                logger.warning(f"[WebChannel] Failed to read textbook partial {rel_path}: {e}")
                return ""

        return include_pattern.sub(_replace, html)

    def GET(self):
        web.header('Content-Type', 'text/html; charset=utf-8')
        web.header('Cache-Control', 'no-cache, no-store, must-revalidate')
        web.header('Pragma', 'no-cache')
        base_dir = os.path.dirname(__file__)
        file_path = os.path.join(base_dir, 'textbook.html')
        with open(file_path, 'r', encoding='utf-8') as f:
            html = f.read()
        html = self._expand_includes(html, base_dir)
        cache_bust = str(int(time.time()))
        for script_name in (
            'textbook.js',
            'textbook-chat.js',
            'textbook-skills.js',
            'textbook-settings.js',
            'textbook-knowledge.js',
            'textbook-detail.js',
        ):
            html = html.replace(f'assets/js/{script_name}', f'assets/js/{script_name}?v={cache_bust}')
        html = html.replace('assets/css/textbook.css', f'assets/css/textbook.css?v={cache_bust}')
        return html


class AssetsHandler:
    def GET(self, file_path):
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            static_dir = os.path.join(current_dir, 'static')
            full_path = os.path.normpath(os.path.join(static_dir, file_path))

            if not os.path.abspath(full_path).startswith(os.path.abspath(static_dir)):
                logger.error(f"Security check failed for path: {full_path}")
                raise web.notfound()
            if not os.path.isfile(full_path):
                logger.error(f"File not found: {full_path}")
                raise web.notfound()

            content_type = mimetypes.guess_type(full_path)[0] or 'application/octet-stream'
            web.header('Content-Type', content_type)
            with open(full_path, 'rb') as f:
                return f.read()
        except web.HTTPError:
            raise
        except Exception as e:
            logger.error(f"Error serving static file: {e}", exc_info=True)
            raise web.notfound()


class TextbookAssetsHandler:
    def GET(self, book_id, file_path):
        require_auth()
        try:
            from bridge.textbook_bridge import get_bridge
            bridge = get_bridge()
            book_dir = bridge.get_book_dir(book_id)
            if not book_dir or not os.path.exists(book_dir):
                raise web.notfound()

            full_path = os.path.normpath(os.path.join(book_dir, file_path))
            if not os.path.abspath(full_path).startswith(os.path.abspath(book_dir)):
                raise web.notfound()
            if not os.path.isfile(full_path):
                raise web.notfound()

            content_type = mimetypes.guess_type(full_path)[0] or 'application/octet-stream'
            web.header('Content-Type', content_type)
            web.header('Cache-Control', 'public, max-age=86400')
            with open(full_path, 'rb') as f:
                return f.read()
        except web.HTTPError:
            raise
        except Exception as e:
            logger.error(f"Error serving textbook asset: {e}")
            raise web.notfound()
