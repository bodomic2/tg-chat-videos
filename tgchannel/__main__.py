"""CLI: python -m tgchannel fetch | parse | catalog | all | stats"""

import argparse
import sys
from pathlib import Path

from . import catalog as catalog_mod
from . import config, db, parse


def _stdout_utf8():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def main(argv=None):
    _stdout_utf8()
    ap = argparse.ArgumentParser(
        prog="python -m tgchannel",
        description="Выгрузка истории телеграм-канала и каталог песен из постов.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="скачать историю канала в БД")
    p_fetch.add_argument("--limit", type=int, help="не больше N постов за запуск")
    p_fetch.add_argument("--full", action="store_true", help="качать с самого начала заново")

    p_parse = sub.add_parser("parse", help="разобрать посты в песни и исполнения")
    p_parse.add_argument("--dry-run", action="store_true", help="показать разбор, не писать в БД")
    p_parse.add_argument("--sample", type=int, default=30, help="сколько постов показать (dry-run)")
    p_parse.add_argument("--status", choices=("ok", "maybe", "other", "empty"),
                         help="в dry-run показывать только посты с этим статусом")

    p_catalog = sub.add_parser("catalog", help="сгенерировать out/CATALOG.md и out/catalog.html")
    p_catalog.add_argument("--with-maybe", action="store_true",
                           help="добавить в каталог даты из «похожих» постов про уже известные песни")
    p_export = sub.add_parser("export", help="список распознанных песен: txt или json")
    p_export.add_argument("--format", choices=("txt", "json"), default="txt")
    p_export.add_argument("--out", help="файл вместо stdout")
    p_export.add_argument("--with-maybe", action="store_true",
                          help="добавить даты из «похожих» постов про известные песни")
    p_export.add_argument("--no-dates", action="store_true",
                          help="только «Исполнитель - Название» (для txt)")

    p_concerts = sub.add_parser("concerts", help="скачать концерты и сетлисты с thejammers.org")
    p_concerts.add_argument("--force", action="store_true", help="перекачать и уже известные концерты")
    p_concerts.add_argument("--reparse", action="store_true",
                            help="пересобрать сетлисты из сохранённого JSON, сайт не трогать")

    sub.add_parser("stats", help="сводка по базе")

    p_all = sub.add_parser("all", help="fetch + parse + catalog")
    p_all.add_argument("--limit", type=int)
    p_all.add_argument("--full", action="store_true")
    p_all.add_argument("--with-maybe", action="store_true")

    args = ap.parse_args(argv)
    conn = db.connect()
    try:
        if args.cmd in ("fetch", "all"):
            from . import fetch  # импорт telethon только когда он реально нужен

            fetch.run(conn, limit=args.limit, full=args.full)

        if args.cmd == "concerts":
            from . import jammers

            if args.reparse:
                jammers.reparse(conn)
            else:
                jammers.run(conn, force=args.force)

        if args.cmd == "parse":
            if args.dry_run:
                parse.dry_run(conn, sample=args.sample, status=args.status)
                return 0
            print("Разбор постов:")
            parse.reparse_all(conn)

        if args.cmd == "all":
            print("Разбор постов:")
            parse.reparse_all(conn)

        if args.cmd in ("catalog", "all"):
            catalog_mod.generate(conn, include_maybe=args.with_maybe)

        if args.cmd == "export":
            catalog_mod.export(
                conn,
                fmt=args.format,
                out_path=Path(args.out) if args.out else None,
                include_maybe=args.with_maybe,
                with_dates=not args.no_dates,
            )

        if args.cmd == "stats":
            print(f"База: {config.db_path()}")
            for key, value in db.counts(conn).items():
                print(f"  {key:12} {value}")
    finally:
        conn.commit()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
