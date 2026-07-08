import os
import discord
from discord.ext import commands
from keep_alive import keep_alive

# Enabling all required gateway intents (including message content)
intents = discord.Intents.default()
intents.voice_states = True     
intents.message_content = True  

class LobbyBotClient(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="/", intents=intents)

    async def setup_hook(self):
        """Loads the lobbybot extension from the cogs folder before connecting to Gateway."""
        try:
            await self.load_extension("cogs.lobbybot")
            print("📁 Loaded 'cogs.lobbybot' successfully.")
        except Exception as e:
            print(f"❌ Failed to load cog: {e}")

bot = LobbyBotClient()

@bot.event
async def on_ready():
    print(f"🛡️ LobbyBot Startup Initialized: {bot.user}")
    
    # 1. Sync globally: This restores the "Supports Slash Commands" badge on your bot profile!
    print("🌍 Syncing commands globally for the Discord badge...")
    try:
        global_synced = await bot.tree.sync()
        print(f"✅ Global sync complete! {len(global_synced)} commands registered globally (Badge restored).")
    except Exception as e:
        print(f"❌ Global sync failed: {e}")

    # 2. Sync to current servers: Makes commands work instantly in servers it's already in
    print("⚡ Performing local sync on existing servers...")
    for guild in bot.guilds:
        try:
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
            print(f"✅ Local sync verified for existing server: {guild.name}")
        except Exception as e:
            print(f"❌ Failed to local sync to {guild.name}: {e}")

@bot.event
async def on_guild_join(guild):
    """Automatically fires the second the bot joins a new server! No more restarts needed."""
    print(f"📥 Joined a new server: {guild.name} ({guild.id})")
    try:
        # Copy global commands to the newly joined server and sync them instantly!
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"⚡ Auto-sync complete! Synced {len(synced)} commands to new server: {guild.name}")
    except Exception as e:
        print(f"❌ Failed to auto-sync to newly joined server {guild.name}: {e}")

if __name__ == "__main__":
    keep_alive()
    bot.run(os.getenv("DISCORD_TOKEN"))
