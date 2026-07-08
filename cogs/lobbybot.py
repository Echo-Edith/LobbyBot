import sqlite3
import random
import discord
import time
from discord import app_commands
from discord.ext import commands, tasks

DB_FILE = "lobbybot_data.db"

class LobbyBot(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.init_db()
        self.cycle_status.start()

    def cog_unload(self):
        self.cycle_status.cancel()

    def init_db(self):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS vc_config (guild_id INTEGER PRIMARY KEY, restricted_mode TEXT, allowed_role_ids TEXT, log_channel_id INTEGER)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS ephemeral_vcs (channel_id INTEGER PRIMARY KEY, guild_id INTEGER, creator_id INTEGER, created_at REAL, members_count INTEGER)''')
        conn.commit()
        conn.close()

    # Database Helpers
    def save_log_channel(self, guild_id, channel_id):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('UPDATE vc_config SET log_channel_id = ? WHERE guild_id = ?', (channel_id, guild_id))
        conn.commit()
        conn.close()

    def get_log_channel(self, guild_id):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT log_channel_id FROM vc_config WHERE guild_id = ?', (guild_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    # Status & VC Management logic remains the same...
    STATUS_LIST = ["Managing Ephemeral VCs", "Cleaning empty rooms...", "Securing voice routes"]

    @tasks.loop(seconds=20)
    async def cycle_status(self):
        await self.bot.wait_until_ready()
        await self.bot.change_presence(activity=discord.CustomActivity(name=random.choice(self.STATUS_LIST)))

    # NEW: /setup-logs Command
    @app_commands.command(name="setup-logs", description="Admin Only: Sets up a private log channel for VC activity.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_logs(self, interaction: discord.Interaction):
        guild = interaction.guild
        overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False), guild.me: discord.PermissionOverwrite(view_channel=True)}
        log_channel = await guild.create_text_channel("lobbybot-logs", overwrites=overwrites, topic="Logging channel for LobbyBot activity.")
        
        # Ensure config exists
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO vc_config (guild_id, restricted_mode) VALUES (?, ?)', (guild.id, 'everyone'))
        conn.commit()
        conn.close()
        
        self.save_log_channel(guild.id, log_channel.id)
        await interaction.response.send_message(f"✅ Setup Complete: Logs are now being sent to {log_channel.mention}", ephemeral=True)

    @app_commands.command(name="open-vc", description="Spawns a temporary voice channel.")
    async def open_vc_command(self, interaction: discord.Interaction, name: str, user_limit: int = 0):
        guild = interaction.guild
        await interaction.response.defer(ephemeral=True)
        new_vc = await guild.create_voice_channel(name=name, user_limit=user_limit)
        
        # Store metadata for tracking
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO ephemeral_vcs VALUES (?, ?, ?, ?, ?)', (new_vc.id, guild.id, interaction.user.id, time.time(), 0))
        conn.commit()
        conn.close()
        
        await interaction.followup.send("✅ Channel Created.", ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # Track unique member join count
        if after.channel:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute('UPDATE ephemeral_vcs SET members_count = members_count + 1 WHERE channel_id = ?', (after.channel.id,))
            conn.commit()
            conn.close()

        # Delete on empty and send log
        if before.channel and len(before.channel.members) == 0:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute('SELECT creator_id, created_at, members_count FROM ephemeral_vcs WHERE channel_id = ?', (before.channel.id,))
            row = cursor.fetchone()
            if row:
                creator_id, created_at, m_count = row
                log_chan_id = self.get_log_channel(before.channel.guild.id)
                if log_chan_id:
                    log_chan = self.bot.get_channel(log_chan_id)
                    if log_chan:
                        duration = round((time.time() - created_at) / 60, 2)
                        await log_chan.send(f"📢 **VC Log:** `{before.channel.name}`\n👤 Creator: <@{creator_id}>\n⏳ Duration: {duration} mins\n👥 Users Joined: {m_count}")
                cursor.execute('DELETE FROM ephemeral_vcs WHERE channel_id = ?', (before.channel.id,))
                await before.channel.delete()
            conn.commit()
            conn.close()

async def setup(bot: commands.Bot):
    await bot.add_cog(LobbyBot(bot)) 
