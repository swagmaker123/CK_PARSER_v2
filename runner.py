import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from common.logging import RunStats, log_run_summary, setup_run_logger
from config.ck import discover_ck_profiles
from config.sources.registry import get_parser_class, source_ids
from export.enricher import enrich_excel
from export.from_cache import load_all_from_cache
from export.writer import write_unified_excel
from mailer import require_llm_columns_for_send, resolve_email_header_path, send_news_email

ALL_CK = "all"
DEFAULT_CK = ALL_CK
DEFAULT_DAYS = 30
MIN_REFRESH_DAYS = 2


def resolve_sources(args):
    if args.all or args.source is None:
        return source_ids()
    return [args.source]


def resolve_ck_profiles(ck_arg):
    profiles = discover_ck_profiles() if ck_arg == ALL_CK else [ck_arg]
    if not profiles:
        raise SystemExit("Не найдено ни одного профиля ЦК в filters/ck")
    return profiles


def run_source(source_id, ck_profiles, days, refresh_days, logger, log_file, stats):
    parser_cls = get_parser_class(source_id)
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


def _load_excel_for_send(excel_path):
    excel_path = Path(excel_path)
    df = pd.read_excel(excel_path)
    require_llm_columns_for_send(df, excel_path)
    return df


def send_digest_email(
    attachment_path,
    subject,
    send_to=None,
    logger=None,
    header_image_path=None,
    latest_news_limit=10,
):
    smtp_login = os.getenv("SMTP_LOGIN")
    smtp_password = os.getenv("SMTP_PASSWORD")
    if not smtp_login or not smtp_password:
        print("Ошибка: SMTP_LOGIN / SMTP_PASSWORD не заданы в .env")
        raise SystemExit(1)

    attachment_path = Path(attachment_path)
    news_df = _load_excel_for_send(attachment_path)
    header_path = resolve_email_header_path(header_image_path)
    recipients = _resolve_email_recipients(send_to)
    send_news_email(
        smtp_login=smtp_login,
        smtp_password=smtp_password,
        recipients=recipients,
        subject=subject,
        final_df=news_df,
        header_image_path=header_path,
        latest_news_limit=latest_news_limit,
        attachments=[str(attachment_path)],
    )
    print(
        f"HTML-письмо отправлено: {', '.join(recipients)}  |  "
        f"вложение: {attachment_path.name}  |  шапка: {header_path.name}"
    )
    if logger is not None:
        logger.info("Письмо отправлено: %s", ", ".join(recipients))


def run_send_only(args):
    target = Path(args.send_only)
    if not target.exists():
        print(f"Ошибка: файл не найден — {target}")
        raise SystemExit(1)

    send_digest_email(
        target,
        subject=f"Дайджест новостей — {target.stem}",
        send_to=args.send_to,
        header_image_path=args.email_header,
        latest_news_limit=args.send_top_n,
    )
    print(f"Завершено: {datetime.now():%Y-%m-%d %H:%M:%S}")


def run_enrich_only(args):
    from common.paths import PROJECT_ROOT

    logger, log_file = setup_run_logger()

    if args.output:
        target_path = Path(args.output)
    else:
        output_dir = Path(PROJECT_ROOT) / "output"
        today_name = f"news_{datetime.now():%Y-%m-%d}.xlsx"
        target_path = output_dir / today_name
        if not target_path.exists():
            print(f"Ошибка: в директории output/ не найден файл {today_name}")
            raise SystemExit(1)

    print(f"LLM audit ranking файла: {target_path.name}")
    enrich_excel(
        target_path,
        top_n=args.top_n,
        reserve_n=args.reserve_n,
        ck_filter=args.ck,
    )
    print(f"Завершено: {datetime.now():%Y-%m-%d %H:%M:%S}")


def run_pipeline(args):
    refresh_days = max(args.refresh_days, MIN_REFRESH_DAYS)
    days = args.days
    sources = resolve_sources(args)
    ck_profiles = resolve_ck_profiles(args.ck)

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
    print(f"\n========== РЕЗУЛЬТ ==========")
    print(f"Excel: {unified_path}")
    logger.info("Итоговый Excel: %s", unified_path)

    if args.enrich:
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
        send_digest_email(
            unified_path,
            subject=f"Дайджест новостей — {run_date}",
            send_to=args.send_to,
            logger=logger,
            header_image_path=args.email_header,
            latest_news_limit=args.send_top_n,
        )

    print(f"\nЗавершено: {datetime.now():%Y-%m-%d %H:%M:%S}")
