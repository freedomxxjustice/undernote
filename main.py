import asyncio
from db.database import init_db
from bot.bot import main as run_bot
from userbot.userbot import main as run_userbot

async def start_all():
    print("🚀 Initializing Database...")
    await init_db()
    
    print("🚀 Launching Both Bots...")
    await asyncio.gather(
        run_bot(),
        run_userbot()
    )

if __name__ == "__main__":
    asyncio.run(start_all())