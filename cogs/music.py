```python
import os
import asyncio
import discord
import random
from discord.ext import commands

# Check if spotipy is installed
try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
    HAS_SPOTIPY = True
except ImportError:
    HAS_SPOTIPY = False

# Check if yt-dlp is installed
try:
    import yt_dlp
    HAS_YTDL = True
except ImportError:
    HAS_YTDL = False

# yt-dlp configurations for streaming raw audio
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',  # bind to ipv4
}

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queues = {}  # {guild_id: [songs]}
        self.spotify = None
        self.init_spotify()

    def init_spotify(self):
        """Attempts to initialize Spotipy using environment keys."""
        if not HAS_SPOTIPY:
            return
        
        client_id = os.getenv("SPOTIFY_CLIENT_ID")
        client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        
        if client_id and client_secret:
            try:
                auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
                self.spotify = spotipy.Spotify(auth_manager=auth_manager)
                print("🟢 Spotify API Connection Initialized Successfully.")
            except Exception as e:
                print(f"⚠️ Spotify API failed to authenticate: {e}")

    async def get_audio_url(self, search_query: str):
        """Uses yt-dlp to extract high quality play streams."""
        if not HAS_YTDL:
            raise RuntimeError("yt-dlp is not installed in requirements.txt!")

        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(ytdl_format_options) as ydl:
            # Performs a direct YouTube audio search
            data = await loop.run_in_executor(
                None, 
                lambda: ydl.extract_info(f"ytsearch:{search_query}", download=False)
            )
            
            if 'entries' in data and len(data['entries']) > 0:
                video = data['entries'][0]
                return {
                    'url': video['url'],
                    'title': video['title'],
                    'duration': video.get('duration', 0)
                }
            return None

    def get_spotify_track_info(self, query: str):
        """Converts query or link to Spotify metadata track name."""
        if not self.spotify:
            return query  # Fallback directly to search query if Spotify is unconfigured

        try:
            if "spotify.com/track/" in query:
                track_id = query.split("track/")[1].split("?")[0]
                track = self.spotify.track(track_id)
                return f"{track['name']} {track['artists'][0]['name']}"
            elif "spotify.com/playlist/" in query:
                # Optional playlist support (extracts first track name as preview)
                playlist_id = query.split("playlist/")[1].split("?")[0]
                results = self.spotify.playlist_tracks(playlist_id, limit=1)
                if results['items']:
                    track = results['items'][0]['track']
                    return f"{track['name']} {track['artists'][0]['name']}"
            else:
                # Search Spotify to get the official title and artist format
                results = self.spotify.search(q=query, limit=1, type='track')
                if results['tracks']['items']:
                    track = results['tracks']['items'][0]
                    return f"{track['name']} {track['artists'][0]['name']}"
        except Exception as e:
            print(f"⚠️ Spotify Metadata parsing error: {e}")
        
        return query  # Fallback to query if anything breaks

    def play_next(self, ctx):
        """Handles processing the song queue consecutively."""
        guild_id = ctx.guild.id
        if guild_id not in self.queues or not self.queues[guild_id]:
            return

        # Pop the next song
        song = self.queues[guild_id].pop(0)
        vc = ctx.voice_client

        if not vc or not vc.is_connected():
            return

        try:
            # Play stream
            audio_source = discord.FFmpegPCMAudio(song['url'], **ffmpeg_options)
            vc.play(
                discord.PCMVolumeTransformer(audio_source), 
                after=lambda e: self.bot.loop.call_soon_threadsafe(self.play_next, ctx)
            )
            
            # Send notification
            embed = discord.Embed(
                title="🎵 Now Playing",
                description=f"**[{song['title']}]({song['url']})**",
                color=discord.Color.gold()
            )
            embed.set_footer(text="LobbyBot Music Core")
            self.bot.loop.create_task(ctx.send(embed=embed))
        except Exception as e:
            print(f"⚠️ Playback exception: {e}")
            self.play_next(ctx)

    @commands.command(name="mp")
    async def mp_command(self, ctx: commands.Context, *, query: str = None):
        """Prefix-based music playing engine: !mp [song name]"""
        if not query:
            return await ctx.send("❌ Error: Please specify a song name or link!\nExample: `!mp Starboy The Weeknd`")

        # Validate Dependencies before attempting connections
        if not HAS_YTDL or not HAS_SPOTIPY:
            return await ctx.send(
                "⚠️ **Environment Notice:** Music streaming features require `yt-dlp` and `spotipy` inside your `requirements.txt`.\n"
                "Please run `pip install yt-dlp spotipy pynacl` to install dependencies."
            )

        # Ensure author is inside a voice channel
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("❌ You must be connected to a voice channel to play music!")

        voice_channel = ctx.author.voice.channel

        # Handle joining/shifting voice channels safely
        vc = ctx.voice_client
        if not vc:
            try:
                vc = await voice_channel.connect()
            except Exception as e:
                return await ctx.send(f"❌ Failed to connect to Voice Channel: {e}")
        elif vc.channel != voice_channel:
            await vc.move_to(voice_channel)

        processing_msg = await ctx.send("🔍 *Searching and processing audio...*")

        # 1. Convert to Spotify Metadata if available
        search_term = self.get_spotify_track_info(query)

        # 2. Get YouTube streaming source URL
        try:
            track_data = await self.get_audio_url(search_term)
            if not track_data:
                return await processing_msg.edit(content="❌ Could not find a matching audio track on YouTube.")
        except Exception as e:
            return await processing_msg.edit(content=f"❌ Audio stream extraction error: {e}")

        # 3. Add to Server Queue
        guild_id = ctx.guild.id
        if guild_id not in self.queues:
            self.queues[guild_id] = []
        
        self.queues[guild_id].append(track_data)

        # If not playing already, start immediately
        if not vc.is_playing():
            await processing_msg.delete()
            self.play_next(ctx)
        else:
            embed = discord.Embed(
                title="📝 Song Queued",
                description=f"Added **{track_data['title']}** to the play queue.",
                color=discord.Color.gold()
            )
            embed.set_footer(text=f"Queue Position: #{len(self.queues[guild_id])}")
            await processing_msg.delete()
            await ctx.send(embed=embed)

    @commands.command(name="skip")
    async def skip_command(self, ctx: commands.Context):
        """Prefix command: !skip"""
        vc = ctx.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await ctx.send("⏭️ Skipped current song.")
        else:
            await ctx.send("❌ Nothing is currently playing.")

    @commands.command(name="stop")
    async def stop_command(self, ctx: commands.Context):
        """Prefix command: !stop"""
        vc = ctx.voice_client
        if vc:
            guild_id = ctx.guild.id
            if guild_id in self.queues:
                self.queues[guild_id].clear()
            vc.stop()
            await vc.disconnect()
            await ctx.send("⏹️ Music stopped and disconnected from voice channel.")
        else:
            await ctx.send("❌ I am not connected to a voice channel.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))

```
