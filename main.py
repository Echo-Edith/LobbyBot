import os
import discord
from discord.ext import commands
from keep_alive import keep_alive

# Enabling intents since you have them turned on in the developer portal!
intents = discord.Intents.default()
intents.voice_states = True     
intents.message_content = True  

class LobbyBotClient(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="/", intents=intents)

    async def setup_hook(self):
        """Loads extensions before the bot logs in."""
        try:
            await self.load_extension("lobbybot")
            print("📁 Loaded 'lobbybot' cog successfully.")
        except Exception as e:
            print(f"❌ Failed to load 'lobbybot' cog: {e}")

bot = LobbyBotClient()

@bot.event
async def on_ready():
    print(f"🛡️ LobbyBot Startup Initialized: {bot.user}")
    
    # 1. Sync globally (takes some time to register everywhere)
    try:
        global_synced = await bot.tree.sync()
        print(f"🔄 Synced {len(global_synced)} commands globally.")
    except Exception as e:
        print(f"❌ Global sync error: {e}")

    # 2. Instant Sync to all guilds (makes commands show up immediately!)
    print("⚡ Performing instant sync on all connected servers...")
    for guild in bot.guilds:
        try:
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            print(f"✅ Instantly synced {len(synced)} commands to server: {guild.name} ({guild.id})")
        except Exception as e:
            print(f"❌ Failed instant sync for server {guild.name}: {e}")

if __name__ == "__main__":
    keep_alive()
    bot.run(os.getenv("DISCORD_TOKEN"))
