import os
import sqlite3
import datetime
import discord
from discord import app_commands
from discord.ext import commands
from keep_alive import keep_alive  # Imports the Render web server helper

# ==========================================================
# PERSISTENT STORAGE MANAGEMENT (SQLite)
# ==========================================================
DB_FILE = "tripwire_data.db"

def init_db():
    """Initializes a local database to remember settings across server restarts."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            guild_id INTEGER PRIMARY KEY,
            channel_id INTEGER,
            action TEXT,
            dummy_id INTEGER
        )
    ''')
    conn.commit()
    conn.close()

def save_guild_settings(guild_id, channel_id, action, dummy_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO settings (guild_id, channel_id, action, dummy_id)
        VALUES (?, ?, ?, ?)
    ''', (guild_id, channel_id, action, dummy_id))
    conn.commit()
    conn.close()

def get_guild_settings(guild_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT channel_id, action, dummy_id FROM settings WHERE guild_id = ?', (guild_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"channel_id": row[0], "action": row[1], "dummy_id": row[2]}
    return None

# Initialize local file database registry
init_db()

# ==========================================================
# CORE SECURITY ENGINE & COMMANDS
# ==========================================================
intents = discord.Intents.default()
intents.message_content = True  # Mandatory to read messages hitting the tripwire
intents.members = True          # Mandatory to kick/ban offending tokens

bot = commands.Bot(command_prefix="/", intents=intents)

@bot.event
async def on_ready():
    print(f"🛡️ Tripwire Core Deployment Successful: {bot.user}")
    try:
        # Syncs application commands to Discord's servers globally
        await bot.tree.sync()
        print("🔄 All security slash application interfaces synced.")
    except Exception as e:
        print(f"❌ Error syncing global command arrays: {e}")

@bot.tree.command(
    name="setup-tripwire",
    description="Deploys the Tripwire honey-pot network channel and locks security rules."
)
@app_commands.describe(
    action="The enforcement punishment executed when a spam token is trapped.",
    dummy_account_id="The literal user ID of your secret un-bot-marked monitoring user account."
)
@app_commands.choices(action=[
    app_commands.Choice(name="Ban Offender", value="ban"),
    app_commands.Choice(name="Kick Offender", value="kick")
])
@app_commands.checks.has_permissions(administrator=True)
async def setup_tripwire(interaction: discord.Interaction, action: app_commands.Choice[str], dummy_account_id: str):
    guild = interaction.guild
    
    # Defer response so Discord doesn't issue an automatic timeout error during channel creation
    await interaction.response.defer(ephemeral=True)

    # Validate that the dummy ID passed is actually a valid numerical format
    try:
        clean_dummy_id = int(dummy_account_id.strip())
    except ValueError:
        return await interaction.followup.send("❌ Formatting Error: The Dummy Account ID must be numbers only.", ephemeral=True)

    # 1. Clean up lingering previous tripwire installations
    for channel in guild.text_channels:
        if channel.name.lower() == "tripwire":
            try:
                await channel.delete(reason="Tripwire Setup Re-initialization")
            except discord.Forbidden:
                return await interaction.followup.send("❌ Permission Error: Bot role lacks 'Manage Channels' privilege.", ephemeral=True)

    # 2. Configure strict permissions (Everyone reads warning, nobody talks)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
    }

    # 3. Create the text honeypot target
    try:
        new_channel = await guild.create_text_channel(
            name="tripwire",
            overwrites=overwrites,
            reason="Tripwire Deployment Init"
        )
    except discord.Forbidden:
        return await interaction.followup.send("❌ Permission Error: Failed to generate system channels.", ephemeral=True)

    # 4. Commit settings safely to SQLite database file
    save_guild_settings(guild.id, new_channel.id, action.value, clean_dummy_id)

    # 5. Broadcast clear warning embed to protect real humans
    embed = discord.Embed(
        title="⚠️ TRIPWIRE SECURITY PROTOCOL ACTIVE",
        description="**CRITICAL NOTICE: DO NOT TYPE HERE OR DIRECT MESSAGE OUR DESIGNATED DUMMY SYSTEM USER.**",
        color=discord.Color.red(),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.add_field(name="🚨 System Mechanics", value="This environment is designed as a trap. Automated scrapers and mass-DM scripts will automatically trigger isolation countermeasures.", inline=False)
    embed.add_field(name="⚙️ Configured Matrix", value=f"**Counter-Measure:** `{action.name}`\n**Monitored Trap Target ID:** `{clean_dummy_id}`", inline=False)
    embed.set_footer(text="Tripwire Automation Matrix")
    
    await new_channel.send(embed=embed)
    await interaction.followup.send(f"✅ Tripwire successfully fortified at {new_channel.mention}!", ephemeral=True)


# ==========================================================
# INTERACTION DETECTOR AND AUTO-MODERATION ENGINE
# ==========================================================
@bot.event
async def on_message(message: discord.Message):
    # Security Bypass: Ignore other bots, webhook streams, and direct messages sent to this bot
    if message.author.bot or not message.guild:
        return

    # Check database to see if the current server has Tripwire configured
    config = get_guild_settings(message.guild.id)
    if not config:
        return

    offender = message.author
    
    # Bypass Protection: Never auto-moderate server admins or managers if they make a mistake
    if offender.guild_permissions.manage_messages or offender.guild_permissions.administrator:
        return

    triggered = False
    violation_reason = "Triggered automated Tripwire trap mechanics."

    # Gate A: Spammer attempts to post content inside the locked channel
    if message.channel.id == config["channel_id"]:
        triggered = True
        violation_reason = f"Security Breach: Unauthorized entry/message in protected honey-pot channel ({message.channel.name})."

    # Gate B: Spammer mentions or attempts to target the dummy account user ID
    elif config["dummy_id"] in [user.id for user in message.mentions]:
        triggered = True
        violation_reason = f"Security Breach: Mass-DM phishing script targeted monitored honey-pot dummy account ({config['dummy_id']})."

    # Action Execution Module
    if triggered:
        try:
            # Delete the offending link/message payload instantly
            await message.delete()
            
            if config["action"] == "ban":
                await message.guild.ban(offender, reason=violation_reason, delete_message_days=1)
                print(f"🔨 [SUCCESS] Banned malicious token {offender.name} ({offender.id}) from {message.guild.name}.")
            elif config["action"] == "kick":
                await message.guild.kick(offender, reason=violation_reason)
                print(f"🥾 [SUCCESS] Kicked suspicious token {offender.name} ({offender.id}) from {message.guild.name}.")
                
        except discord.Forbidden:
            print(f"❌ Role Hierarchy Error: Could not punish {offender.name}. Ensure Tripwire's role position is higher than the targets.")

# Global Error Catcher for Application Commands
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("❌ Access Denied: This utility requires Administrator privileges.", ephemeral=True)
    else:
        print(f"Unhandled system exception: {error}")

if __name__ == "__main__":
    # Start web thread to hook into Render Free Layer web server expectations
    keep_alive()
    # Establish persistent engine connection
    bot.run(os.getenv("DISCORD_TOKEN"))
