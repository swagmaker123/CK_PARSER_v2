import argparse
import os
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common.logging import RunStats, log_run_summary, setup_run_logger
from dotenv import load_dotenv

# Загружаем .env из профиля OpenClaw
load_dotenv(os.path.join(os.path.expanduser("~"), ".openclaw", ".env"))
from export.from_cache import load_all_from_cache
from export.writer import write_unified_excel
from parsers.banki.parser import BankiParser
from parsers.cbr.parser import CbrParser
from parsers.consultant.parser import ConsultantParser
from parsers.garant.parser import GarantParser
from parsers.interfax.parser import InterfaxParser
from parsers.minfin.parser import MinfinParser
from parsers.nalog.parser import NalogParser
from parsers.palata.parser import PalataParser
from parsers.rbc.parser import RbcParser

ALL_CK = "all"
DEFAULT_CK = ALL_CK
DEFAULT_DAYS = 30
MIN_REFRESH_DAYS = 2

PARSERS = {
    "banki": BankiParser,
    "cbr": CbrParser,
    "garant": GarantParser,
    "interfax": InterfaxParser,
    "minfin": MinfinParser,
    "nalog": NalogParser,
    "palata": PalataParser,
    "rbc": RbcParser,
    "consultant": ConsultantParser,
}

# Playwright подтягивается только при запуске kommersant
LAZY_PARSERS = ("kommersant",)

SOURCE_ORDER = (
    "banki",
    "cbr",
    "garant",
    "interfax",
    "kommersant",
    "minfin",
    "nalog",
    "palata",
    "rbc",
    "consultant",
)

SOURCE_CHOICES = sorted(set(PARSERS) | set(LAZY_PARSERS))


def discover_ck_profiles():
    ck_root = os.path.join(PROJECT_ROOT, "filters", "ck")
    profiles = []

    for name in sorted(os.listdir(ck_root)):
        if name.startswith("__"):
            continue

        rules_path = os.path.join(ck_root, name, "rules.py")
        if os.path.isfile(rules_path):
            profiles.append(name)

    return profiles


def _lazy_import_kommersant():
    from parsers.kommersant.parser import KommersantParser
    return KommersantParser


def run_source(source_id, ck_profiles, days, refresh_days, logger, log_file, stats):
    if source_id == "kommersant":
        parser_cls = _lazy_import_kommersant()
    else:
        parser_cls = PARSERS[source_id]
    instance = parser_cls()

    return instance.run(
        ck_profiles=ck_profiles,
        days=days,
        refresh_days=refresh_days,
        logger=logger,
        log_file=log_file,
        stats=stats,
    )


def _resolve_email_recipients(send_to):
    recipients = send_to or [
        r.strip()
        for r in os.getenv("DEFAULT_RECIPIENTS", "").split(",")
        if r.strip()
    ]
    if not recipients:
        print("Ошибка: не указаны адресаты (--send-to или DEFAULT_RECIPIENTS в .env)")
        raise SystemExit(1)
    return recipients


def _send_digest_email(attachment_path, subject, send_to=None, logger=None):
    from mailer import send_news_email_plain

    smtp_login = os.getenv("SMTP_LOGIN")
    smtp_password = os.getenv("SMTP_PASSWORD")
    if not smtp_login or not smtp_password:
        print("Ошибка: SMTP_LOGIN / SMTP_PASSWORD не заданы в .env")
        raise SystemExit(1)

    recipients = _resolve_email_recipients(send_to)
    send_news_email_plain(
        smtp_login=smtp_login,
        smtp_password=smtp_password,
        recipients=recipients,
        subject=subject,
        attachments=[str(attachment_path)],
    )
    print(f"Письмо отправлено: {', '.join(recipients)}  |  вложение: {attachment_path}")
    if logger is not None:
        logger.info("Письмо отправлено: %s", ", ".join(recipients))


def main():
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
            "  python main.py --send                # после прогона отправить Excel по email\n"
            "  python main.py --send-only output/news_2026-07-01.xlsx  # только отправка файла"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        choices=SOURCE_CHOICES,
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
        help="После прогона отправить итоговый Excel по email",
    )
    parser.add_argument(
        "--send-only",
        type=str,
        metavar="FILE",
        default=None,
        help="Только отправить указанный Excel по email, без парсинга",
    )
    parser.add_argument(
        "--send-to",
        nargs="+",
        default=None,
        help="Адресаты email (если не задано — DEFAULT_RECIPIENTS из .env)",
    )
    args = parser.parse_args()

    refresh_days = max(args.refresh_days, MIN_REFRESH_DAYS)
    days = args.days

    if args.send_only:
        from pathlib import Path as _Path

        target = _Path(args.send_only)
        if not target.exists():
            print(f"Ошибка: файл не найден — {target}")
            raise SystemExit(1)

        _send_digest_email(
            target,
            subject=f"Дайджест новостей — {target.stem}",
            send_to=args.send_to,
        )
        print(f"Завершено: {datetime.now():%Y-%m-%d %H:%M:%S}")
        raise SystemExit(0)

    # --- Режимы постобработки готового Excel ---
    postprocess_only = args.enrich_only
    postprocess_after_export = args.enrich

    if postprocess_only:
        from common.paths import PROJECT_ROOT
        from pathlib import Path as _Path

        logger, log_file = setup_run_logger()

        if args.output:
            target_path = _Path(args.output)
        else:
            output_dir = _Path(PROJECT_ROOT) / "output"
            today_name = f"news_{datetime.now():%Y-%m-%d}.xlsx"
            target_path = output_dir / today_name
            if not target_path.exists():
                print(f"Ошибка: в директории output/ не найден файл {today_name}")
                raise SystemExit(1)

        from export.enricher import enrich_excel

        print(f"LLM audit ranking файла: {target_path.name}")
        enrich_excel(
            target_path,
            top_n=args.top_n,
            reserve_n=args.reserve_n,
            ck_filter=args.ck,
        )

        print(f"Завершено: {datetime.now():%Y-%m-%d %H:%M:%S}")
        raise SystemExit(0)

    if args.all or args.source is None:
        sources = list(SOURCE_ORDER)
    else:
        sources = [args.source]

    ck_profiles = (
        discover_ck_profiles()
        if args.ck == ALL_CK
        else [args.ck]
    )

    if not ck_profiles:
        raise SystemExit("Не найдено ни одного профиля ЦК в filters/ck")

    logger, log_file = setup_run_logger()
    stats = RunStats()

    print(f"Старт: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Лог: {log_file}")
    logger.info("Старт прогона")
    logger.info("Источники: %s", ", ".join(sources))
    logger.info("ЦК: %s", ", ".join(ck_profiles))
    logger.info("Дней: %s, refresh-days: %s", days, refresh_days)

    run_date = datetime.now().strftime("%Y-%m-%d")

    if args.export_only:
        logger.info("Режим: только экспорт из кэша")
        combined_by_ck = load_all_from_cache(sources, ck_profiles, days)

        for ck_id in ck_profiles:
            for source_id in sources:
                count = len(combined_by_ck[ck_id].get(source_id, []))
                logger.info("  %s / %s: %s статей", source_id, ck_id, count)
    else:
        combined_by_ck = {ck_id: {} for ck_id in ck_profiles}

        for index, source_id in enumerate(sources):
            if len(sources) > 1:
                print(
                    f"\n========== {source_id.upper()} "
                    f"({index + 1}/{len(sources)}) =========="
                )

            source_results = run_source(
                source_id,
                ck_profiles,
                days,
                refresh_days=refresh_days,
                logger=logger,
                log_file=log_file,
                stats=stats,
            )

            for ck_id, articles in source_results.items():
                combined_by_ck[ck_id][source_id] = articles

    unified_path = write_unified_excel(combined_by_ck, run_date=run_date)
    print(f"\n========== РЕЗУЛЬАТ ==========")
    print(f"Excel: {unified_path}")
    logger.info("Итоговый Excel: %s", unified_path)

    # Опциональное LLM audit ranking после записи Excel
    if postprocess_after_export:
        from export.enricher import enrich_excel
        print("\n========== LLM AUDIT RANKING ==========")
        enrich_excel(
            unified_path,
            top_n=args.top_n,
            reserve_n=args.reserve_n,
            ck_filter=args.ck,
        )
        print(f"LLM audit ranking завершен: {unified_path}")

    if not args.export_only:
        logger.info("========== ИТОГ ПРОГОНА ==========")
        log_run_summary(logger, stats)

    if args.send:
        _send_digest_email(
            unified_path,
            subject=f"Дайджест новостей — {run_date}",
            send_to=args.send_to,
            logger=logger,
        )

    print(f"\nЗавершено: {datetime.now():%Y-%m-%d %H:%M:%S}")


if __name__ == "__main__":
    main()
