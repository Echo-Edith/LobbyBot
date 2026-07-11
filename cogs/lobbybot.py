import sqlite3
import random
import re
import discord
import time
from discord import app_commands
from discord.ext import commands, tasks

DB_FILE = "lobbybot_data.db"
CHANGELOG_CHANNEL_ID = 1512576440930009159

class LobbyBot(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = time.time()
        self.init_db()
        self.cycle_status.start()
        
        # Schedule the clean sweep of any leftover empty VCs on startup
        self.bot.loop.create_task(self.cleanup_ghost_vcs())

    def cog_unload(self):
        self.cycle_status.cancel()

    # ==========================================================
    # STORAGE MANAGEMENT (SQLite - Auto-Migrating Columns)
    # ==========================================================
    def init_db(self):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vc_config (
                guild_id INTEGER PRIMARY KEY,
                restricted_mode TEXT,
                allowed_role_ids TEXT,
                log_channel_id INTEGER
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ephemeral_vcs (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER,
                creator_id INTEGER,
                created_at REAL,
                members_count INTEGER
            )
        ''')
        
        # Persistent stats tracker table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stats_tracker (
                stat_key TEXT PRIMARY KEY,
                stat_value INTEGER
            )
        ''')

        # Rolling 24-hour NEW server tracker table (Tracks additions only)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS server_daily_tracker (
                guild_id INTEGER PRIMARY KEY,
                joined_at REAL
            )
        ''')
        
        # Safe structural database update check
        cursor.execute("PRAGMA table_info(vc_config)")
        columns = [col[1] for col in cursor.fetchall()]
        if "log_channel_id" not in columns:
            cursor.execute("ALTER TABLE vc_config ADD COLUMN log_channel_id INTEGER")
            
        cursor.execute("PRAGMA table_info(ephemeral_vcs)")
        evc_columns = [col[1] for col in cursor.fetchall()]
        if "creator_id" not in evc_columns:
            cursor.execute("DROP TABLE IF EXISTS ephemeral_vcs")
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ephemeral_vcs (
                    channel_id INTEGER PRIMARY KEY,
                    guild_id INTEGER,
                    creator_id INTEGER,
                    created_at REAL,
                    members_count INTEGER
                )
            ''')
            
        conn.commit()
        conn.close()

    def save_vc_config(self, guild_id, restricted_mode, allowed_role_ids_str):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO vc_config (guild_id, restricted_mode, allowed_role_ids)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET 
                restricted_mode=excluded.restricted_mode,
                allowed_role_ids=excluded.allowed_role_ids
        ''', (guild_id, restricted_mode, allowed_role_ids_str))
        conn.commit()
        conn.close()

    def get_vc_config(self, guild_id):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT restricted_mode, allowed_role_ids FROM vc_config WHERE guild_id = ?', (guild_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {"restricted_mode": row[0], "allowed_role_ids": row[1]}
        return {"restricted_mode": "everyone", "allowed_role_ids": ""}

    def save_log_channel(self, guild_id, channel_id):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO vc_config (guild_id, log_channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET log_channel_id=excluded.log_channel_id
        ''', (guild_id, channel_id))
        conn.commit()
        conn.close()

    def get_log_channel(self, guild_id):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT log_channel_id FROM vc_config WHERE guild_id = ?', (guild_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    # Helpers for persistent stats
    def increment_stat(self, key):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO stats_tracker (stat_key, stat_value)
            VALUES (?, 1)
            ON CONFLICT(stat_key) DO UPDATE SET stat_value = stat_value + 1
        ''', (key,))
        conn.commit()
        conn.close()

    def get_stat(self, key):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT stat_value FROM stats_tracker WHERE stat_key = ?', (key,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else 0

    # ==========================================================
    # SECURE GHOST CHANNELS STARTUP CLEANER
    # ==========================================================
    async def cleanup_ghost_vcs(self):
        """Sweeps database records and deletes empty VCs ONLY if they are found in the ephemeral_vcs table."""
        await self.bot.wait_until_ready()
        print("🧹 Initializing ephemeral voice channel sweep sequence...")
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT channel_id, guild_id FROM ephemeral_vcs')
        rows = cursor.fetchall()
        conn.close()

        to_delete_from_db = []
        for channel_id, guild_id in rows:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                to_delete_from_db.append(channel_id)
                continue
                
            channel = guild.get_channel(channel_id)
            if not channel:
                to_delete_from_db.append(channel_id)
                continue
                
            # DOUBLE CHECK: Only delete empty channels that are confirmed bot-created
            if len(channel.members) == 0:
                try:
                    await channel.delete(reason="LobbyBot: Clean sweep of ghost channels on startup.")
                    print(f"🧹 Cleaned up expired dynamic voice room: '{channel.name}'")
                except Exception as e:
                    print(f"⚠️ Failed to delete ephemeral channel {channel_id}: {e}")
                to_delete_from_db.append(channel_id)

        if to_delete_from_db:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.executemany('DELETE FROM ephemeral_vcs WHERE channel_id = ?', [(cid,) for cid in to_delete_from_db])
            conn.commit()
            conn.close()
            print(f"🧹 Removed {len(to_delete_from_db)} expired channel records from database.")

    # ==========================================================
    # BOT PRESENCE CONTROL LOOP
    # ==========================================================
    STATUS_LIST = [
        "Managing Ephemeral VCs",
        "Cleaning empty voice rooms...",
        "Monitoring active voice channels",
        "Securing dynamic voice sectors",
        "Watching channel capacity limits",
        "Clearing ghost channels...",
        "Managing temporary VCs",
        "Restricting voice boundaries",
        "Optimizing database records...",
        "Securing server voice routes"
    ]

    @tasks.loop(seconds=20)
    async def cycle_status(self):
        await self.bot.wait_until_ready()
        status_phrase = random.choice(self.STATUS_LIST)
        try:
            await self.bot.change_presence(activity=discord.CustomActivity(name=status_phrase))
        except Exception as e:
            print(f"⚠️ Presence update error: {e}")

    # ==========================================================
    # LOGGING CHANNELS SETUP & RECOVERY ENGINE
    # ==========================================================
    async def resolve_log_channel(self, guild: discord.Guild) -> discord.TextChannel:
        saved_id = self.get_log_channel(guild.id)
        if saved_id:
            chan = guild.get_channel(saved_id)
            if chan:
                return chan

        for channel in guild.text_channels:
            if channel.name == "lobbybot-logs":
                self.save_log_channel(guild.id, channel.id)
                return channel
        return None

    @app_commands.command(
        name="setup-logs",
        description="Configure or recover an isolated private administration log channel."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_logs_command(self, interaction: discord.Interaction):
        guild = interaction.guild
        await interaction.response.defer(ephemeral=True)

        existing_chan = await self.resolve_log_channel(guild)
        if existing_chan:
            return await interaction.followup.send(
                f"ℹ️ Active logs channel already detected and synced: {existing_chan.mention}", 
                ephemeral=True
            )

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True)
        }
        
        try:
            new_log_chan = await guild.create_text_channel(
                "lobbybot-logs", 
                overwrites=overwrites, 
                reason="LobbyBot: Automatic Logging Channel creation requested."
            )
            self.save_log_channel(guild.id, new_log_chan.id)
            await interaction.followup.send(
                f"✅ Successful logs initialization! Logs will stream inside: {new_log_chan.mention}", 
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Access Denied: LobbyBot requires administrator authority to manage channel states.", ephemeral=True)

    # ==========================================================
    # CORE /RESTRICT-VC PERMISSIONS CONFIGURATION
    # ==========================================================
    @app_commands.command(
        name="restrict-vc",
        description="Configure access permissions for temporary VC creation."
    )
    @app_commands.describe(
        mode="Who is allowed to run the /open-vc command?",
        role_1="First role allowed to create voice channels.",
        role_2="Second role allowed to create voice channels (Optional).",
        role_3="Third role allowed to create voice channels (Optional).",
        role_4="Fourth role allowed to create voice channels (Optional)."
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Everyone (No Restrictions)", value="everyone"),
            app_commands.Choice(name="Administrators Only", value="admin"),
            app_commands.Choice(name="Allowed Roles List Only", value="role")
        ]
    )
    async def restrict_vc_command(
        self,
        interaction: discord.Interaction,
        mode: app_commands.Choice[str],
        role_1: discord.Role = None,
        role_2: discord.Role = None,
        role_3: discord.Role = None,
        role_4: discord.Role = None
    ):
        guild = interaction.guild
        if interaction.user.id != guild.owner_id and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Error: Only Administrators can configure voice restrictions.", ephemeral=True)

        if mode.value == "role" and not role_1:
            return await interaction.response.send_message("❌ Setup Error: You selected 'Allowed Roles List Only' but did not supply a role inside the `role_1` field.", ephemeral=True)

        collected_ids = []
        role_mentions = []
        for r in [role_1, role_2, role_3, role_4]:
            if r:
                collected_ids.append(str(r.id))
                role_mentions.append(r.mention)
        
        allowed_roles_str = ",".join(collected_ids)
        self.save_vc_config(guild.id, mode.value, allowed_roles_str)

        msg = f"✅ Success! `/open-vc` access has been configured to: **{mode.name}**"
        if role_mentions:
            msg += f"\n👥 **Allowed Roles:** {', '.join(role_mentions)}"
        
        await interaction.response.send_message(msg, ephemeral=True)

    # ==========================================================
    # HIGH-PERFORMANCE /OPEN-VC 
    # ==========================================================
    @app_commands.command(
        name="open-vc",
        description="Spawns a temporary ephemeral Voice Channel that deletes itself when empty."
    )
    @app_commands.describe(
        name="The name of your custom voice channel.",
        user_limit="The max number of members allowed in this VC (0 for unlimited, max 99).",
        description="Welcome description topic displayed in the broadcast notification card.",
        roles_allowed="Tag roles or enter names/IDs that are allowed to enter (supports multiple/infinite spacing)."
    )
    async def open_vc_command(
        self, 
        interaction: discord.Interaction, 
        name: str, 
        user_limit: int = 0,
        description: str = None,
        roles_allowed: str = None
    ):
        guild = interaction.guild
        await interaction.response.defer(ephemeral=True)

        config = self.get_vc_config(guild.id)
        restricted_mode = config["restricted_mode"]
        allowed_roles_str = config["allowed_role_ids"]

        if interaction.user.id != guild.owner_id and not interaction.user.guild_permissions.administrator:
            if restricted_mode == "admin":
                return await interaction.followup.send("❌ Permission Denied: This command is restricted to Server Administrators.", ephemeral=True)
            elif restricted_mode == "role":
                if not allowed_roles_str:
                    return await interaction.followup.send("❌ Permission Denied: No roles are allowed to create channels yet.", ephemeral=True)
                
                allowed_role_ids = [int(x) for x in allowed_roles_str.split(",") if x.strip().isdigit()]
                user_has_allowed_role = any(role.id in allowed_role_ids for role in interaction.user.roles)
                if not user_has_allowed_role:
                    return await interaction.followup.send("❌ Permission Denied: You do not possess an authorized role to generate dynamic voice rooms.", ephemeral=True)

        clean_limit = max(0, min(99, user_limit))

        # Dynamic Infinite Roles Extraction and Resolution
        allowed_roles = []
        if roles_allowed:
            # 1. Parse pinged role mentions: <@&ID>
            for r_id in re.findall(r'<@&(\d+)>', roles_allowed):
                resolved_role = guild.get_role(int(r_id))
                if resolved_role and resolved_role not in allowed_roles:
                    allowed_roles.append(resolved_role)
            
            # 2. Parse raw numeric snowflakes
            for r_id in re.findall(r'\b\d{17,21}\b', roles_allowed):
                resolved_role = guild.get_role(int(r_id))
                if resolved_role and resolved_role not in allowed_roles:
                    allowed_roles.append(resolved_role)

            # 3. Fallback name matching (case insensitive, ignoring pings)
            clean_names = re.sub(r'<@&\d+>', '', roles_allowed).strip()
            if clean_names:
                for role in guild.roles:
                    if role.is_default():
                        continue
                    # Match words within name
                    if re.search(r'\b' + re.escape(role.name) + r'\b', clean_names, re.IGNORECASE):
                        if role not in allowed_roles:
                            allowed_roles.append(role)

        try:
            # Initialize permission overwrites
            # Bot and Creator must always have Connect bypasses to prevent lockout
            overwrites = {
                guild.me: discord.PermissionOverwrite(connect=True, speak=True, mute_members=True, move_members=True, view_channel=True),
                interaction.user: discord.PermissionOverwrite(connect=True, speak=True, view_channel=True)
            }
            
            # If specific roles are configured, restrict everyone else from connecting
            if allowed_roles:
                overwrites[guild.default_role] = discord.PermissionOverwrite(connect=False)
                for role in allowed_roles:
                    overwrites[role] = discord.PermissionOverwrite(connect=True, view_channel=True)
            
            new_vc = await guild.create_voice_channel(
                name=name.strip(),
                user_limit=clean_limit,
                overwrites=overwrites,
                reason=f"Ephemeral VC requested by {interaction.user.name}"
            )
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute(
                'INSERT OR REPLACE INTO ephemeral_vcs VALUES (?, ?, ?, ?, ?)',
                (new_vc.id, guild.id, interaction.user.id, time.time(), 0)
            )
            conn.commit()
            conn.close()
            
            # Persistent Stat Increment Tracker for open-vc count
            self.increment_stat("total_opened_vcs")
            
            embed = discord.Embed(
                title="🔊 Ephemeral Voice Channel Opened!",
                description="A new dynamic room has been established.",
                color=discord.Color.gold()
            )
            embed.add_field(name="👑 Creator", value=interaction.user.mention, inline=True)
            embed.add_field(name="🏷️ Channel Name", value=f"**{new_vc.name}**", inline=True)
            embed.add_field(name="👥 Capacity Limit", value="Unlimited" if clean_limit == 0 else f"{clean_limit}", inline=True)
            
            if description:
                embed.add_field(name="📝 Channel Description", value=description, inline=False)
                
            if allowed_roles:
                role_mentions = [r.mention for r in allowed_roles]
                embed.add_field(name="🔒 Restricted Access Roles", value=", ".join(role_mentions), inline=False)
                
            embed.add_field(name="🔗 Quick Join", value=f"[Click Here to Join Room]({new_vc.jump_url})", inline=False)
            embed.set_footer(text="This channel will automatically self-destruct once empty.")
            
            if interaction.user.display_avatar:
                embed.set_thumbnail(url=interaction.user.display_avatar.url)

            await interaction.followup.send("✅ Voice channel opened successfully!", ephemeral=True)
            await interaction.channel.send(embed=embed)

        except discord.Forbidden:
            await interaction.followup.send("❌ Error: LobbyBot does not have permissions to manage server channels.", ephemeral=True)

    # ==========================================================
    # DYNAMIC USER LIMIT ADJUSTER (Prefix !limit Only)
    # ==========================================================
    async def adjust_vc_limit(self, guild, user, current_channel, new_limit: int):
        """Internal logic to change VC limit if sender is the creator or an admin."""
        if not current_channel or not isinstance(current_channel, discord.VoiceChannel):
            return "❌ Error: You must be inside your ephemeral voice channel to adjust its limit!"

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT creator_id FROM ephemeral_vcs WHERE channel_id = ?', (current_channel.id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return "❌ Error: This voice channel is not managed by LobbyBot."

        creator_id = row[0]
        is_admin = user.guild_permissions.administrator or user.id == guild.owner_id

        if user.id != creator_id and not is_admin:
            return "❌ Permission Denied: Only the creator of this channel or an Administrator can adjust the limit."

        clean_limit = max(0, min(99, new_limit))
        
        try:
            # Dynamically ensure bot retains absolute connect permission override (ignores any set limits like 1)
            await current_channel.set_permissions(guild.me, connect=True, speak=True)
            await current_channel.edit(user_limit=clean_limit)
            limit_text = "Unlimited" if clean_limit == 0 else f"{clean_limit} users"
            return f"✅ Success! **{current_channel.name}** user limit adjusted to **{limit_text}**."
        except discord.Forbidden:
            return "❌ Error: LobbyBot does not have permissions to edit this voice channel's settings."

    @commands.command(name="limit", help="Edits the maximum user limit of your active dynamic voice room.")
    async def limit_prefix(self, ctx: commands.Context, user_limit: int = None):
        """Prefix command: !limit [number]"""
        if user_limit is None:
            return await ctx.send("❌ Usage: `!limit <number>` (e.g. `!limit 5` or `!limit 0` for unlimited)")
        
        user_vc = ctx.author.voice.channel if ctx.author.voice else None
        response_msg = await self.adjust_vc_limit(ctx.guild, ctx.author, user_vc, user_limit)
        await ctx.send(response_msg)

    # ==========================================================
    # NEW SERVERS JOIN EVENT LISTENER
    # ==========================================================
    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """Fires when LobbyBot is added to a new server, logging it in our rolling 24h table."""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        now = time.time()
        cursor.execute('''
            INSERT OR REPLACE INTO server_daily_tracker (guild_id, joined_at)
            VALUES (?, ?)
        ''', (guild.id, now))
        conn.commit()
        conn.close()
        print(f"📥 LobbyBot added to new server: '{guild.name}' ({guild.id})! Tracked for daily growth stats.")

    # ==========================================================
    # COMPREHENSIVE UTILITY COMMANDS: /system-stats, /help, /changelogs
    # ==========================================================
    @app_commands.command(name="system-stats", description="Displays active latency, voice logs, and loaded metrics.")
    async def system_stats(self, interaction: discord.Interaction):
        uptime_seconds = int(time.time() - self.start_time)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        # 24/7 Rolling New Servers Tracker Update
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        now = time.time()
        
        # Purge records of new joins older than 24h (86400 seconds)
        cursor.execute('DELETE FROM server_daily_tracker WHERE joined_at < ?', (now - 86400,))
        conn.commit()
        
        # Get count of unique servers added within the last 24 hours
        cursor.execute('SELECT COUNT(*) FROM server_daily_tracker')
        daily_new_servers_count = cursor.fetchone()[0]
        conn.close()

        # Fetch stats
        total_opened_vcs = self.get_stat("total_opened_vcs")
        total_servers = len(self.bot.guilds)

        embed = discord.Embed(title="📊 LobbyBot Host Diagnostics", color=discord.Color.gold())
        embed.add_field(name="📶 Connection Latency", value=f"`{round(self.bot.latency * 1000)}ms`", inline=True)
        embed.add_field(name="⏱️ System Uptime", value=f"`{hours}h {minutes}m {seconds}s`", inline=True)
        embed.add_field(name="🌐 Total Servers", value=f"`{total_servers}` servers", inline=True)
        embed.add_field(name="🆕 New Servers (Daily 24h)", value=f"`+{daily_new_servers_count}` added", inline=True)
        embed.add_field(name="🔊 Total VCs Opened", value=f"`{total_opened_vcs}` channels", inline=True)
        embed.set_footer(text="LobbyBot • Active Diagnostics Core")
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="help", description="Explains exactly how to configure and use the bot's features.")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="❓ LobbyBot Help & Command Index",
            description="LobbyBot handles dynamic voice channels and automated voice channel activity leveling.\nHere is the full index of all commands currently active inside the bot:",
            color=discord.Color.gold()
        )
        
        # Dynamic Slash Commands Loader
        slash_commands_list = []
        for cog_name, cog in self.bot.cogs.items():
            for cmd in cog.get_app_commands():
                desc = cmd.description or "No description provided."
                slash_commands_list.append(f"🔊 **/{cmd.name}**\n└ *{desc}*")
                
        if slash_commands_list:
            embed.add_field(name="✨ Slash Commands (/)", value="\n".join(slash_commands_list), inline=False)
            
        # Dynamic Prefix Commands Loader
        prefix_commands_list = []
        for cog_name, cog in self.bot.cogs.items():
            for cmd in cog.get_commands():
                desc = cmd.help or cmd.description or "No description provided."
                aliases = f" (or `!{', !'.join(cmd.aliases)}`)" if cmd.aliases else ""
                prefix_commands_list.append(f"⚙️ **!{cmd.name}**{aliases}\n└ *{desc}*")
                
        if prefix_commands_list:
            embed.add_field(name="⚙️ Prefix Commands (!)", value="\n".join(prefix_commands_list), inline=False)
            
        embed.set_footer(text="LobbyBot • Auto-updating Command Core")
        if interaction.user.display_avatar:
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="changelogs", description="Lists the latest live updates for LobbyBot directly from configuration stream.")
    async def changelogs(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        target_channel = self.bot.get_channel(CHANGELOG_CHANNEL_ID)
        
        embed = discord.Embed(
            title="📋 LobbyBot Official Changelogs",
            color=discord.Color.gold()
        )
        
        if not target_channel:
            embed.description = "❌ No active changelogs are available at this time. (System source unreachable)"
            return await interaction.followup.send(embed=embed)

        try:
            latest_msg = None
            async for msg in target_channel.history(limit=1):
                latest_msg = msg
                
            if latest_msg and latest_msg.content:
                embed.description = latest_msg.content
                embed.set_footer(text=f"Last updated: {latest_msg.created_at.strftime('%Y-%m-%d %H:%M UTC')}")
            else:
                embed.description = "⚙️ No active changelogs are published. Delete history or configuration is clear."
        except Exception:
            embed.description = "⚙️ Changelogs are currently empty or unavailable."

        await interaction.followup.send(embed=embed)

    # ==========================================================
    # LISTENERS: VOICE STATE AND TRACKING INTEGRATIONS
    # ==========================================================
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel == after.channel:
            return

        if after.channel:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE ephemeral_vcs SET members_count = members_count + 1 WHERE channel_id = ?', 
                (after.channel.id,)
            )
            conn.commit()
            conn.close()

        if before.channel:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute(
                'SELECT creator_id, created_at, members_count FROM ephemeral_vcs WHERE channel_id = ?', 
                (before.channel.id,)
            )
            row = cursor.fetchone()
            
            # Delete if channel is empty and tracked in database (guarantees Admin VCs are never touched)
            if row and len(before.channel.members) == 0:
                creator_id, created_at, members_count = row
                duration_mins = round((time.time() - created_at) / 60, 2)
                
                log_chan = await self.resolve_log_channel(before.channel.guild)
                if log_chan:
                    log_embed = discord.Embed(
                        title="🧹 Ephemeral Voice Channel Closed",
                        description=f"A dynamic channel has expired and was safely deleted.",
                        color=discord.Color.red()
                    )
                    log_embed.add_field(name="🏷️ Name", value=f"`{before.channel.name}`", inline=True)
                    log_embed.add_field(name="👑 Creator", value=f"<@{creator_id}>", inline=True)
                    log_embed.add_field(name="⏳ Lifespan", value=f"`{duration_mins} minutes`", inline=True)
                    log_embed.add_field(name="👥 Total Joins", value=f"`{members_count} members`", inline=True)
                    log_embed.set_footer(text="LobbyBot • Session Logs Manager")
                    try:
                        await log_chan.send(embed=log_embed)
                    except Exception:
                        pass
                
                try:
                    await before.channel.delete(reason="LobbyBot: Dynamic session empty.")
                    print(f"🧹 Safely deleted expired dynamic channel '{before.channel.name}' from server view.")
                except Exception as e:
                    print(f"⚠️ Failed to delete expired channel {before.channel.id}: {e}")
                    
                cursor.execute('DELETE FROM ephemeral_vcs WHERE channel_id = ?', (before.channel.id,))
                
            conn.commit()
            conn.close()

async def setup(bot: commands.Bot):
    await bot.add_cog(LobbyBot(bot))

