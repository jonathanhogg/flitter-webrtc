"""
Flitter WebRTC Signalling Server
"""

import argparse
from pathlib import Path
import ssl

from flitter import configure_logger
from .server import SignallingServer


def main():
    parser = argparse.ArgumentParser(description="Flitter WebRTC Signalling Server")
    parser.set_defaults(level=None)
    levels = parser.add_mutually_exclusive_group()
    levels.add_argument('--trace', action='store_const', const='TRACE', dest='level', help="Trace logging")
    levels.add_argument('--debug', action='store_const', const='DEBUG', dest='level', help="Debug logging")
    levels.add_argument('--verbose', action='store_const', const='INFO', dest='level', help="Informational logging")
    levels.add_argument('--quiet', action='store_const', const='WARNING', dest='level', help="Only log warnings and errors")
    parser.add_argument('--port', type=int, default=None, help="Port to listen on")
    parser.add_argument('--host', type=str, default='', help="Hostname to listen on")
    parser.add_argument('--certificate', type=Path, default=None, help="Certificate file to use")
    parser.add_argument('--key', type=Path, default=None, help="Certificate private key file to use")
    args = parser.parse_args()
    configure_logger(args.level)
    server = SignallingServer()
    if args.certificate is not None:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(args.certificate, keyfile=args.key)
    else:
        ssl_context = None
    server.run(host=args.host, port=args.port, ssl_context=ssl_context)


if __name__ == '__main__':
    main()
