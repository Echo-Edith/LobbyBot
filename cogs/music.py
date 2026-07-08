import discord
import wavelink
import asyncio
from discord.ext import commands

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.skip_votes = {}
        self.track_creators = {}
        self.track_creators_raw = {}
        bot.loop.create_task(self.connect_nodes())

    async def connect_nodes(self):
        """Tries multiple high-uptime servers one by one until one successfully connects."""
        await self.bot.wait_until_ready()
        
        # List of the best 4 free public music servers online right now
        servers = [
            {"uri": "http://lavalink.yandere.today:2333", "password": "yanderetoday"},
            {"uri": "http://lava.link:80", "password": "youshallnotpass"},
            {"uri": "http://ll.gsl.network:80", "password": "youshallnotpass"},
            {"uri": "http://lavalink.jirayu.xyz:2333", "password": "youshallnotpass"}
        ]
        
        connected = False
        for server_info in servers:
            node = wavelink.Node(
                uri=server_info["uri"],
                password=server_info["password"]
            )
            try:
                # Try to connect to this single node
                await wavelink.Pool.connect(nodes=[node], client=self.bot, cache_capacity=100)
                print(f"🟢 Connected successfully to: {server_info['uri']}")
                connected = True
                break  # Stop trying other servers once we are connected!
            except Exception as e:
                print(f"⚠️ Failed to connect to {server_info['uri']}: {e}. Trying fallback...")
        
        if not connected:
            print("❌ Critical: All fallback music servers are currently unreachable.")

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, node: wavelink.Node):
        print(f"📡 Node {node.identifier} is online and ready.")

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload):
        player = payload.player
        track = payload.track
        guild_id = player.guild.id
        self.skip_votes[guild_id] = set()

        creator = self.track_creators.get(track.id, "Unknown User")
        embed = discord.Embed(
            title="🔊 Now Playing",
            description=f"**[{track.title}]({track.uri})**",
            color=discord.Color.gold()
        )
        embed.add_field(name="👑 Creator", value=creator, inline=True)
        duration_mins, duration_secs = divmod(int(track.length // 1000), 60)
        embed.add_field(name="⏱️ Duration", value=f"{duration_mins}m {duration_secs}s", inline=True)
        embed.set_footer(text="LobbyBot Music • Empty rooms auto-cleanup")
        
        channel = player.home if hasattr(player, 'home') else None
        if channel:
            self.bot.loop.create_task(channel.send(embed=embed))

    @commands.command(name="mp", aliases=["play"])
    async def mp_command(self, ctx: commands.Context, *, query: str = None):
        """Prefix command: !mp [song name]"""
        if not query:
            return await ctx.send("❌ Please specify a song! Example: `!mp Starboy`")

        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("❌ You must be in a voice channel to use this command!")

        voice_channel = ctx.author.voice.channel
        player: wavelink.Player = ctx.voice_client or ctx.guild.voice_client

        if not player:
            try:
                # Bypass channel user limits to join
                overwrites = voice_channel.overwrites
                overwrites[ctx.guild.me] = discord.PermissionOverwrite(connect=True, speak=True)
                await voice_channel.edit(overwrites=overwrites)
                
                player = await voice_channel.connect(cls=wavelink.Player)
                player.home = ctx.channel
            except Exception as e:
                return await ctx.send(f"❌ Connection error: {e}")

        if not wavelink.Pool.nodes:
            return await ctx.send("❌ Music node is currently offline. Please wait 10 seconds and try again!")

        processing_msg = await ctx.send("🔍 *Searching and loading track...*")
        try:
            tracks = await wavelink.Playable.search(query)
            if not tracks:
                return await processing_msg.edit(content="❌ Could not find a matching track.")
        except Exception as e:
            return await processing_msg.edit(content=f"❌ Search failed: {e}")

        track = tracks[0]
        self.track_creators[track.id] = ctx.author.mention
        self.track_creators_raw[track.id] = ctx.author.id

        try:
            await processing_msg.delete()
        except:
            pass

        if not player.playing:
            await player.play(track)
        else:
            await player.queue.put(track)
            embed = discord.Embed(
                title="📝 Added to Queue",
                description=f"**[{track.title}]({track.uri})**",
                color=discord.Color.gold()
            )
            embed.add_field(name="👥 Position", value=f"`#{len(player.queue)}`", inline=True)
            await ctx.send(embed=embed)

    @commands.command(name="mq", aliases=["queue"])
    async def mq_command(self, ctx: commands.Context):
        """Prefix command: !mq"""
        player: wavelink.Player = ctx.voice_client or ctx.guild.voice_client
        if not player or not player.current:
            return await ctx.send("❌ Nothing is currently playing.")

        elapsed = int(player.position // 1000)
        total = int(player.current.length // 1000)
        progress = min(1.0, elapsed / total) if total else 0
        bars = 12
        filled = int(progress * bars)
        bar_display = "▬" * filled + "🔘" + "▬" * max(0, bars - filled - 1)

        embed = discord.Embed(title="📋 Server Play Queue", color=discord.Color.gold())
        embed.add_field(
            name="🎵 Now Playing",
            value=f"**[{player.current.title}]({player.current.uri})**\n`[{elapsed // 60}m {elapsed % 60}s]` {bar_display} `[{total // 60}m {total % 60}s]`",
            inline=False
        )

        queue_list = list(player.queue)
        if queue_list:
            upcoming = ""
            for idx, q_track in enumerate(queue_list[:5], 1):
                upcoming += f"`{idx}.` **[{q_track.title}]({q_track.uri})**\n"
            embed.add_field(name="📋 Upcoming", value=upcoming, inline=False)
        else:
            embed.add_field(name="📋 Upcoming", value="*Queue is empty!*", inline=False)

        await ctx.send(embed=embed)

    @commands.command(name="mskip", aliases=["skip"])
    async def skip_command(self, ctx: commands.Context):
        """Prefix command: !mskip"""
        player: wavelink.Player = ctx.voice_client or ctx.guild.voice_client
        if not player or not player.current:
            return await ctx.send("❌ Nothing is playing to skip.")

        listeners = [m for m in player.channel.members if not m.bot]
        total_listeners = len(listeners)

        requestor_id = self.track_creators_raw.get(player.current.id)
        if ctx.author.id == requestor_id or ctx.author.guild_permissions.administrator:
            await player.skip()
            return await ctx.send("⏭️ Track has been skipped.")

        guild_id = ctx.guild.id
        if guild_id not in self.skip_votes:
            self.skip_votes[guild_id] = set()

        if ctx.author.id in self.skip_votes[guild_id]:
            return await ctx.send("❌ You already voted to skip this song.")

        self.skip_votes[guild_id].add(ctx.author.id)
        votes = len(self.skip_votes[guild_id])
        needed = max(1, (total_listeners + 1) // 2)

        if votes >= needed:
            await player.skip()
            await ctx.send("⏭️ Vote pass! Skipping current track.")
        else:
            await ctx.send(f"🗳️ Vote registered: `{votes}/{needed}` (Need 50% of listeners to skip).")

    @commands.command(name="mstop", aliases=["stop"])
    async def stop_command(self, ctx: commands.Context):
        """Prefix command: !mstop"""
        player: wavelink.Player = ctx.voice_client or ctx.guild.voice_client
        if player:
            player.queue.clear()
            await player.disconnect()
            await ctx.send("⏹️ Music stopped and queue cleared.")
        else:
            await ctx.send("❌ The bot is not connected to any voice channels.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
