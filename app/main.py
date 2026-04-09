from __future__ import annotations

import asyncio

from app.config import load_settings
from app.runtime import BotRuntime


async def _main() -> None:
    settings = load_settings()
    runtime = BotRuntime(settings)
    await runtime.run()


if __name__ == "__main__":
    asyncio.run(_main())
