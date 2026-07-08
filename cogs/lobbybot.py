import sqlite3
import random
import discord
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

    # ==========================================================
    # STORAGE MANAGEMENT (SQLite)
    # ==========================================================
    def init_db(self):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        # Updates table layout to safely hold multiple role IDs as a split-string
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vc_config (
                guild_id INTEGER PRIMARY KEY,
                restricted_mode TEXT,
                allowed_role_ids TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ephemeral_vcs (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER
            )
        ''')
        conn.commit()
        conn.close()

    def save_vc_config(self, guild_id, restricted_mode, allowed_role_ids_str):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO vc_config (guild_id, restricted_mode, allowed_role_ids)
            VALUES (?, ?, ?)
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

    def add_ephemeral_vc(self, channel_id, guild_id):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO ephemeral_vcs (channel_id, guild_id) VALUES (?, ?)', (channel_id, guild_id))
        conn.commit()
        conn.close()

    def remove_ephemeral_vc(self, channel_id):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM ephemeral_vcs WHERE channel_id = ?', (channel_id,))
        conn.commit()
        conn.close()

    def get_all_ephemeral_vcs(self):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT channel_id, guild_id FROM ephemeral_vcs')
        rows = cursor.fetchall()
        conn.close()
        return rows

    # ==========================================================
    # DYNAMIC STATUS CYCLER (Includes your custom requested presence)
    # ==========================================================
    STATUS_LIST = [
        "Managing VC", "Apex Legends", "Valorant", "Minecraft", 
        "League of Legends", "Grand Theft Auto V", "Counter-Strike 2", 
        "GTA 6", "Call of Duty: Warzone", "Watching for ghost VC", "Roblox",
        "Managing Ephemeral VCs", "LobbyBot Online ✅", "Cleaning ghost channels..."
    ]

    @tasks.loop(seconds=20)
    async def cycle_status(self):
        """Randomly changes status activity to keep client layout dynamic."""
        await self.bot.wait_until_ready()
        status_phrase = random.choice(self.STATUS_LIST)
        
        # Standard custom presence format matching the preview
        await self.bot.change_presence(
            activity=discord.Activity(type=discord.ActivityType.playing, name=status_phrase)
        )

    # ==========================================================
    # MODIFIED /RESTRICT-VC (Supports multi-role permission config)
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

        # Build list of active provided role IDs
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
    # UPGRADED /OPEN-VC (Renders a beautiful Rich Embed UI notification)
    # ==========================================================
    @app_commands.command(
        name="open-vc",
        description="Spawns a temporary ephemeral Voice Channel that deletes itself when empty."
    )
    @app_commands.describe(
        name="The name of your custom voice channel.",
        user_limit="The max number of members allowed in this VC (0 for unlimited, max 99)."
    )
    async def open_vc_command(self, interaction: discord.Interaction, name: str, user_limit: int = 0):
        guild = interaction.guild
        await interaction.response.defer(ephemeral=True)

        config = self.get_vc_config(guild.id)
        restricted_mode = config["restricted_mode"]
        allowed_roles_str = config["allowed_role_ids"]

        # Permission check evaluation supporting multiple roles
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

        try:
            # Create voice channel
            new_vc = await guild.create_voice_channel(
                name=name.strip(),
                user_limit=clean_limit,
                reason=f"Ephemeral VC requested by {interaction.user.name}"
            )
            
            self.add_ephemeral_vc(new_vc.id, guild.id)
            
            # Formulate the Discord Embed Message
            embed = discord.Embed(
                title="🔊 Ephemeral Voice Channel Opened!",
                description="A new dynamic room has been established.",
                color=discord.Color.gold()
            )
            embed.add_field(name="👑 Creator", value=interaction.user.mention, inline=True)
            embed.add_field(name="🏷️ Channel Name", value=f"**{new_vc.name}**", inline=True)
            embed.add_field(name="👥 Capacity Limit", value="Unlimited" if clean_limit == 0 else f"{clean_limit} users", inline=True)
            embed.add_field(name="🔗 Quick Join", value=f"[Click Here to Join Room]({new_vc.jump_url})", inline=False)
            embed.set_footer(text="This channel will automatically self-destruct once empty.")
            embed.set_thumbnail(url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)

            # Confirm privately to the command caller, and send a beautiful public embed to the text channel
            await interaction.followup.send("✅ Voice channel opened successfully!", ephemeral=True)
            await interaction.channel.send(embed=embed)

        except discord.Forbidden:
            await interaction.followup.send("❌ Error: LobbyBot does not have permissions to manage server channels.", ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel == after.channel:
            return

        if before.channel:
            registered_vcs = [item[0] for item in self.get_all_ephemeral_vcs()]
            if before.channel.id in registered_vcs:
                if len(before.channel.members) == 0:
                    try:
                        await before.channel.delete(reason="LobbyBot: Ephemeral VC is empty.")
                        self.remove_ephemeral_vc(before.channel.id)
                    except discord.NotFound:
                        self.remove_ephemeral_vc(before.channel.id)
                    except discord.Forbidden:
                        print(f"❌ Permissions Error: LobbyBot failed to delete empty VC: {before.channel.id}")

async def setup(bot: commands.Bot):
    await bot.add_cog(LobbyBot(bot))
