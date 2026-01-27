import os
import asyncio
from db.database import init_db
from bot.bot import main as run_bot
from userbot.userbot import main as run_userbot

# --- NEW: Dummy Server for Render ---
async def handle_client(reader, writer):
    """Simple HTTP response to keep Render happy."""
    data = await reader.read(100)
    message = "HTTP/1.1 200 OK\r\nContent-Length: 7\r\n\r\nI am up"
    writer.write(message.encode())
    await writer.drain()
    writer.close()

async def start_dummy_server():
    # Get the PORT from Render, default to 8080 if missing
    port = int(os.getenv("PORT", 8080))
    server = await asyncio.start_server(
        handle_client, '0.0.0.0', port
    )
    print(f"✅ Dummy server started on port {port}")
    await server.serve_forever()
# ------------------------------------

async def start_all():
    print("🚀 Initializing Database...")
    await init_db()
    
    print("🚀 Launching Bots & Server...")
    # Run the bot, userbot, AND the dummy server together
    await asyncio.gather(
        run_bot(),
        run_userbot(),
        start_dummy_server()
    )

if __name__ == "__main__":
    asyncio.run(start_all())