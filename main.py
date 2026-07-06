import discord
from discord.ext import commands

class FroggyBot(commands.Bot):
    def __init__(self):
        # Setting up intents
        intents = discord.Intents.default()
        # CRITICAL: This must be True so the bot can read guesses sent in chat
        intents.message_content = True  
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Automatically loads froggy.py when it starts up
        await self.load_extension("froggy")
        await self.tree.sync()

    async def on_ready(self):
        print(f"✅ Froggy Bot is online as {self.user}!")

if __name__ == "__main__":
    bot = FroggyBot()
    # Replace with your actual bot token from the Discord Developer Portal
    bot.run("YOUR_BOT_TOKEN")
