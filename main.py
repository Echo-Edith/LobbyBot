import os
import discord
from discord.ext import commands
from keep_alive import keep_alive

# Enabling required gateway intents (voice and messages)
intents = discord.Intents.default()
intents.voice_states = True     
intents.message_content = True  

class LobbyBotClient(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="/", intents=intents)

    async def setup_hook(self):
        """Loads the lobbybot extension from the cogs folder before connecting."""
        try:
            await self.load_extension("cogs.lobbybot")
            print("📁 Loaded 'cogs.lobbybot' successfully.")
        except Exception as e:
            print(f"❌ Failed to load cog: {e}")

bot = LobbyBotClient()

@bot.event
async def on_ready():
    print(f"🛡️ LobbyBot Startup Initialized: {bot.user}")
    print(f"Connected to {len(bot.guilds)} servers.")
    
    # PUBLIC BOT OPTIMIZATION:
    # We only sync globally here. This registers commands with Discord's central cache.
    # New servers will instantly have the commands when they add the bot, completely
    # avoiding rate limits from syncing individual guilds.
    print("🌍 Syncing commands globally...")
    try:
        global_synced = await bot.tree.sync()
        print(f"✅ Global sync complete! {len(global_synced)} commands registered globally.")
    except Exception as e:
        print(f"❌ Global sync failed: {e}")

if __name__ == "__main__":
    keep_alive()
    bot.run(os.getenv("DISCORD_TOKEN"))
