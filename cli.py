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
            "  python main.py --enrich-only --ck payment_systems  # топ по ПС из сегодняшнего Excel\n"
            "  python main.py --ck payment_systems  # только ЦК payment_systems\n"
            "  python main.py --enrich --send           # enrich + HTML-письмо с Excel\n"
            "  python main.py --send-only output/news_2026-07-01.xlsx  # только отправка enrich-Excel"
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
        help="Запустить LLM audit ranking после парсинга и записи Excel",
    )
    parser.add_argument(
        "--enrich-only",
        action="store_true",
        help="Только LLM audit ranking (без парсинга): берёт output/news_сегодня.xlsx",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Путь к конкретному Excel-файлу для --enrich-only",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="Количество топ-новостей для пометки (default: 10)",
    )
    parser.add_argument(
        "--reserve-n",
        type=int,
        default=5,
        help="Количество резервных новостей для audit ranking (default: 5)",
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
        help="Сколько новостей показать в HTML-письме (default: 10)",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.send_only:
        run_send_only(args)
        return

    if args.enrich_only:
        run_enrich_only(args)
        return

    run_pipeline(args)
