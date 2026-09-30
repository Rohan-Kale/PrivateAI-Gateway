"""Bounded representation inspection; findings cover the original encoded token."""
import base64
import binascii
import json
import re
from urllib.parse import unquote

TOKEN = re.compile(r"(?<![A-Za-z0-9_%+/.-])[A-Za-z0-9_%+/=.-]{8,4096}(?![A-Za-z0-9_%+/=.-])")
JWT = re.compile(r"(?<![\w.-])([A-Za-z0-9_-]{8,2048})\.([A-Za-z0-9_-]{2,2048})\.([A-Za-z0-9_-]{8,2048})(?![\w.-])")


def decode64(value):
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True).decode("utf-8")


def jwt_spans(text):
    for match in JWT.finditer(text):
        try:
            header=json.loads(decode64(match[1])); payload=json.loads(decode64(match[2]))
            if isinstance(header,dict) and isinstance(header.get("alg"),str) and isinstance(payload,dict):
                yield match.start(),match.end(),"SECRET"
        except (ValueError,UnicodeError,binascii.Error):pass


def encoded_spans(text, secret_check, depth=2):
    if depth == 0:return
    for match in TOKEN.finditer(text):
        value=match.group(); decoded=[]
        if re.search(r"%[0-9a-fA-F]{2}",value):
            try:decoded.append(unquote(value,errors="strict"))
            except UnicodeError:pass
        try:decoded.append(decode64(value))
        except (ValueError,UnicodeError,binascii.Error):pass
        for candidate in decoded:
            if candidate == value or not candidate or not all(c.isprintable() or c in "\r\n\t" for c in candidate):continue
            if secret_check(candidate) or list(jwt_spans(candidate)) or any(encoded_spans(candidate,secret_check,depth-1)):
                yield match.start(),match.end(),"SECRET"
                break
