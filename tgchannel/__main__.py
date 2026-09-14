"""CLI: python -m tgchannel concerts | fetch | match | all | stats | serve | login"""

import argparse
import sys

from . import config, db


def _stdout_utf8():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def main(argv=None):
    _stdout_utf8()
    ap = argparse.ArgumentParser(
        prog="python -m tgchannel",
        description="Каталог видео с концертов The Jammers из чата музыкантов.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login", help="разовый интерактивный вход в Telegram (создаёт сессию)")

    p_concerts = sub.add_parser("concerts", help="скачать концерты и сетлисты с thejammers.org")
    p_concerts.add_argument("--force", action="store_true", help="перекачать и уже известные концерты")
    p_concerts.add_argument("--reparse", action="store_true",
                            help="пересобрать сетлисты из сохранённого JSON, сайт не трогать")

    p_fetch = sub.add_parser("fetch", help="скачать сообщения с видео из чата в БД")
    p_fetch.add_argument("--limit", type=int, help="не больше N видео за запуск")
    p_fetch.add_argument("--full", action="store_true", help="качать с самого начала заново")

    sub.add_parser("match", help="привязать видео к концертам и песням сетлистов")

    p_all = sub.add_parser("all", help="concerts + fetch + match")
    p_all.add_argument("--limit", type=int)

    sub.add_parser("stats", help="сводка по базе")

    p_serve = sub.add_parser("serve", help="веб-каталог с поиском и правкой привязок")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8080)
    p_serve.add_argument("--debug", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd == "serve":
        from . import web  # flask; соединения с БД открывает сам, на запрос

        web.serve(host=args.host, port=args.port, debug=args.debug)
        return 0
    conn = db.connect()
    try:
        if args.cmd == "login":
            from . import fetch  # импорт telethon только когда он реально нужен

            fetch.login()

        if args.cmd == "concerts":
            from . import jammers

            if args.reparse:
                jammers.reparse(conn)
            else:
                jammers.run(conn, force=args.force)

        if args.cmd == "all":
            from . import jammers

            jammers.run(conn)

        if args.cmd in ("fetch", "all"):
            from . import fetch

            fetch.run(conn, limit=args.limit, full=getattr(args, "full", False))

        if args.cmd in ("match", "all"):
            from . import match

            match.run(conn)

        if args.cmd == "stats":
            print(f"База: {config.db_path()}")
            for key, value in db.counts(conn).items():
                print(f"  {key:18} {value}")
    finally:
        conn.commit()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
