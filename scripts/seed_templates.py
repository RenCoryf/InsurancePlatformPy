#!/usr/bin/env python3
"""Seed template phrases (idempotent). Run after migrations:

    python -m scripts.seed_templates          # или: uv run python scripts/seed_templates.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.tables.template_phrase import TemplatePhrase

SEED = [
    ("user", "Хочу оформить ОСАГО", 1),
    ("user", "Сколько стоит полис КАСКО?", 2),
    ("user", "Как начисляются бонусы?", 3),
    ("user", "Где посмотреть мои заявки?", 4),
    ("user", "Свяжите меня с менеджером", 5),
    ("bonus", "Как обменять бонусы на сертификат?", 1),
    ("bonus", "Когда сгорают бонусы?", 2),
    ("bonus", "Сколько бонусов у меня накоплено?", 3),
    ("support", "Здравствуйте! Чем могу помочь?", 1),
    ("support", "Пришлите, пожалуйста, фото документов.", 2),
    ("support", "Расчёт будет готов в течение 10 минут.", 3),
    ("support", "Спасибо за обращение! Обращайтесь ещё.", 4),
]


async def main() -> None:
    async with AsyncSessionLocal() as session:
        added = 0
        for scope, text, order in SEED:
            existing = await session.execute(
                select(TemplatePhrase).where(
                    TemplatePhrase.scope == scope, TemplatePhrase.text == text
                )
            )
            if existing.scalar_one_or_none() is None:
                session.add(TemplatePhrase(scope=scope, text=text, sort_order=order))
                added += 1
        await session.commit()
    print(f"seed_templates: {added} added, {len(SEED) - added} already present")


if __name__ == "__main__":
    asyncio.run(main())
