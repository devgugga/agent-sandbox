#!/usr/bin/env python3
"""broker/asb-docker-broker.py — socket do Docker, filtrado e so-leitura.

Roda como root (unidade de sistema) e expoe um socket pertencente ao operador
com apenas os endpoints de LEITURA que o debug exige. Mutacao recebe 403 e nao
e configuravel: `exec` num container root com bind mount do host E root do
host, e chamar isso de contencao seria mentira.

Valida a linha de requisicao e os cabecalhos, depois relaciona bytes sem
reinterpretar a resposta — assim `logs --follow`, que e um fluxo, funciona sem
que este programa precise entender chunked encoding.
"""
from __future__ import annotations

import os
import re
import socket
import socketserver
import sys
import threading

DOCKER_SOCK = os.environ.get("ASB_DOCKER_SOCK", "/var/run/docker.sock")
LISTEN = os.environ.get("ASB_BROKER_SOCK", "/run/asb-docker/docker.sock")
OWNER_UID = int(os.environ.get("ASB_BROKER_UID", "1000"))

# Prefixo de versao opcional; o caminho e comparado ja normalizado.
VERSION = re.compile(r"^/v[0-9]+\.[0-9]+")
ALLOWED = (
    re.compile(r"^/version$"),
    re.compile(r"^/info$"),
    re.compile(r"^/events$"),
    re.compile(r"^/containers/json$"),
    re.compile(r"^/containers/[A-Za-z0-9_.-]+/json$"),
    re.compile(r"^/containers/[A-Za-z0-9_.-]+/logs$"),
    re.compile(r"^/containers/[A-Za-z0-9_.-]+/stats$"),
    re.compile(r"^/containers/[A-Za-z0-9_.-]+/top$"),
)

DENY = (b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n"
        b"Connection: close\r\n\r\n")


def permitted(method: str, target: str) -> bool:
    if method != "GET":
        return False
    path = target.split("?", 1)[0]
    # Comparar depois de normalizar: "/containers/../../x" nao pode virar um
    # caminho permitido por acidente.
    path = os.path.normpath(path)
    if not path.startswith("/"):
        return False
    path = VERSION.sub("", path, count=1) or "/"
    return any(rule.match(path) for rule in ALLOWED)


def relay(source: socket.socket, sink: socket.socket) -> None:
    try:
        while chunk := source.recv(65536):
            sink.sendall(chunk)
    except OSError:
        pass
    finally:
        try:
            sink.shutdown(socket.SHUT_WR)
        except OSError:
            pass


class Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        client = self.request
        client.settimeout(30)
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = client.recv(4096)
            if not chunk:
                return
            head += chunk
            if len(head) > 32768:
                client.sendall(DENY)
                return

        request_line = head.split(b"\r\n", 1)[0].decode("latin-1")
        parts = request_line.split()
        if len(parts) != 3 or not permitted(parts[0], parts[1]):
            client.sendall(DENY)
            return

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as upstream:
            upstream.connect(DOCKER_SOCK)
            # Uma requisicao por conexao: com keep-alive, uma segunda
            # requisicao no mesmo socket passaria sem validacao.
            head = re.sub(rb"\r\nConnection:[^\r\n]*", b"", head,
                          flags=re.IGNORECASE)
            head = head.replace(b"\r\n\r\n", b"\r\nConnection: close\r\n\r\n",
                                1)
            upstream.sendall(head)
            downward = threading.Thread(target=relay, args=(upstream, client))
            downward.start()
            relay(client, upstream)
            downward.join()


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    if not os.path.exists(DOCKER_SOCK):
        print(f"socket do Docker ausente: {DOCKER_SOCK}", file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(LISTEN), exist_ok=True)
    # Um socket antigo faz bind() falhar com EADDRINUSE, e o sintoma seria "o
    # broker nao sobe" sem dizer por que.
    if os.path.exists(LISTEN):
        os.unlink(LISTEN)
    os.umask(0o177)
    with Server(LISTEN, Handler) as server:
        os.chown(LISTEN, OWNER_UID, OWNER_UID)
        os.chmod(LISTEN, 0o600)
        print(f"broker ouvindo em {LISTEN} -> {DOCKER_SOCK}", file=sys.stderr)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
