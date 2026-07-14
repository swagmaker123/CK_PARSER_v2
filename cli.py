import argparse

from config.sources.registry import source_choices
from mailer import DEFAULT_EMAIL_HEADER_FILENAME
from runner import (
    ALL_CK,
    DEFAULT_CK,
    DEFAULT_DAYS,
    MIN_REFRESH_DAYS,
    run_enrich_only,
    run_pipeline,
    run_rank_only,
    run_send_only,
)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Парсер новостей по источнику и профилю ЦК",
        epilog=(
            "Примеры:\n"
            "  python main.py                       # все источники по всем ЦК\n"
            "  python main.py --source interfax     # только Interfax\n"
            "  python main.py --source kommersant   # Kommersant (Playwright)\n"
            "  python main.py --source consultant   # Consultant\n"
            "  python main.py --days 30             # все источники за 30 дней\n"
            "  python main.py --export-only         # Excel из кэша, без загрузки\n"
            "  python main.py --enrich              # парсинг + LLM score/dedupe\n"
            "  python main.py --enrich-only         # enrich активного периода\n"
            "  python main.py --rank-only           # 2-й проход по активному Excel (cron)\n"
            "  python main.py --enrich --send --plain\n"
            "  python main.py --send-only output/sent/news_2026-07-01_2026-07-31.xlsx --plain"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        choices=source_choices(),
        default=None,
        help="Один источник. Если не указан, запускаются все источники",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Все источники по очереди (оставлено для совместимости)",
    )
    parser.add_argument(
        "--ck",
        default=DEFAULT_CK,
        help=f"ID профиля ЦК или all (по умолчанию: {DEFAULT_CK})",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"Сколько дней парсить (по умолчанию: {DEFAULT_DAYS})",
    )
    parser.add_argument(
        "--refresh-days",
        type=int,
        default=MIN_REFRESH_DAYS,
        metavar="N",
        help=(
            "Перекачать заново последние N дней от сегодня. "
            f"Минимум {MIN_REFRESH_DAYS}, чтобы последние дни всегда проверялись заново"
        ),
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Собрать единый Excel из кэша без загрузки сайтов",
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="После парсинга: LLM score + semantic dedupe (без top ranking)",
    )
    parser.add_argument(
        "--enrich-only",
        action="store_true",
        help="Только LLM score + dedupe: активный Excel-период или --output",
    )
    parser.add_argument(
        "--rank-only",
        action="store_true",
        help=(
            "Только 2-й LLM-проход по активному периоду (или --output); "
            "удобно для cron раз в месяц"
        ),
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Путь к Excel для --enrich-only / --rank-only (по умолчанию — активный период)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="Количество топ-новостей для --rank-only (default: 10)",
    )
    parser.add_argument(
        "--reserve-n",
        type=int,
        default=5,
        help="Количество резервных новостей для --rank-only (default: 5)",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="После прогона отправить HTML-письмо с топом новостей и Excel (нужен enrich)",
    )
    parser.add_argument(
        "--send-only",
        type=str,
        metavar="FILE",
        default=None,
        help="Только отправить указанный enrich-Excel по email (HTML + вложение)",
    )
    parser.add_argument(
        "--send-to",
        nargs="+",
        default=None,
        help="Адресаты email (если не задано — DEFAULT_RECIPIENTS из .env)",
    )
    parser.add_argument(
        "--email-header",
        type=str,
        default=None,
        help=(
            "Картинка шапки для HTML-письма "
            f"(по умолчанию: assets/{DEFAULT_EMAIL_HEADER_FILENAME})"
        ),
    )
    parser.add_argument(
        "--send-top-n",
        type=int,
        default=10,
        help="Сколько новостей показать в письме (default: 10)",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="Отправить текстовое письмо вместо HTML (для --send / --send-only)",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.send_only:
        run_send_only(args)
        return

    if args.rank_only:
        run_rank_only(args)
        return

    if args.enrich_only:
        run_enrich_only(args)
        return

    run_pipeline(args)
