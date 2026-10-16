"""Uvicorn de teste com desligamento cooperativo via stdin, inclusive no Windows.

Não adiciona rotas à aplicação. EOF ou uma linha no pipe solicita o lifespan shutdown.
Os cenários de crash continuam usando os._exit explicitamente.
"""
import sys
import threading

import uvicorn


def main():
    server = uvicorn.Server(uvicorn.Config(
        sys.argv[1], host="127.0.0.1", port=int(sys.argv[2])))

    def stop_when_requested():
        sys.stdin.readline()
        server.should_exit = True

    threading.Thread(target=stop_when_requested, daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
