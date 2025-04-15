import asyncio
import discord
import io
import gtts
import discord.opus
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import humanize_list

class TTS(commands.Cog):
    """Text-to-Speech cog for Red-Discordbot"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9238457234, force_registration=True)
        
        default_guild = {
            "enabled": True,
            "language": "en",
            "slow_mode": False,
            "max_length": 200
        }
        
        self.config.register_guild(**default_guild)
        self.voice_states = {}

    @commands.group(name="ttsset")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def tts_settings(self, ctx):
        """Configure the TTS cog settings"""
        pass

    @tts_settings.command(name="toggle")
    async def toggle_tts(self, ctx):
        """Toggle TTS functionality for this server"""
        current = await self.config.guild(ctx.guild).enabled()
        await self.config.guild(ctx.guild).enabled.set(not current)
        status = "enabled" if not current else "disabled"
        await ctx.send(f"TTS has been {status} for this server.")

    @tts_settings.command(name="language")
    async def set_language(self, ctx, language_code: str):
        """Set the language for TTS (e.g., 'en', 'fr', 'es', 'de')"""
        # List of supported languages: https://gtts.readthedocs.io/en/latest/module.html#localized-accents
        try:
            # Testing if the language code is valid
            test_tts = gtts.gTTS("Test", lang=language_code)
            await self.config.guild(ctx.guild).language.set(language_code)
            await ctx.send(f"TTS language has been set to: {language_code}")
        except ValueError:
            await ctx.send("Invalid language code. Please provide a valid language code.")

    @tts_settings.command(name="slow")
    async def toggle_slow_mode(self, ctx):
        """Toggle slow speech mode"""
        current = await self.config.guild(ctx.guild).slow_mode()
        await self.config.guild(ctx.guild).slow_mode.set(not current)
        status = "enabled" if not current else "disabled"
        await ctx.send(f"Slow speech mode has been {status}.")

    @tts_settings.command(name="maxlength")
    async def set_max_length(self, ctx, length: int):
        """Set the maximum character length for TTS messages"""
        if length < 1 or length > 1000:
            return await ctx.send("Maximum length must be between 1 and 1000 characters.")
        await self.config.guild(ctx.guild).max_length.set(length)
        await ctx.send(f"Maximum TTS message length set to {length} characters.")

    @tts_settings.command(name="show")
    async def show_settings(self, ctx):
        """Show current TTS settings"""
        settings = await self.config.guild(ctx.guild).all()
        
        embed = discord.Embed(
            title="TTS Settings",
            color=await ctx.embed_color(),
            description="Current settings for the TTS cog"
        )
        
        embed.add_field(name="Enabled", value="Yes" if settings["enabled"] else "No", inline=True)
        embed.add_field(name="Language", value=settings["language"], inline=True)
        embed.add_field(name="Slow Mode", value="Yes" if settings["slow_mode"] else "No", inline=True)
        embed.add_field(name="Max Length", value=f"{settings['max_length']} characters", inline=True)
        
        await ctx.send(embed=embed)

    @commands.command(name="tts")
    @commands.guild_only()
    async def text_to_speech(self, ctx, *, text: str = None):
        """Convert text to speech and play it in your voice channel"""
        # Check if TTS is enabled in this guild
        if not await self.config.guild(ctx.guild).enabled():
            return await ctx.send("TTS is disabled in this server.")
        
        # Check if the user provided text
        if not text:
            return await ctx.send("Please provide some text for me to speak.")
        
        # Check if the text exceeds the maximum length
        max_length = await self.config.guild(ctx.guild).max_length()
        if len(text) > max_length:
            return await ctx.send(f"Your message exceeds the maximum length of {max_length} characters.")
        
        # Check if the user is in a voice channel
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("You need to be in a voice channel to use this command.")
        
        voice_channel = ctx.author.voice.channel
        
        # Get TTS settings
        lang = await self.config.guild(ctx.guild).language()
        slow = await self.config.guild(ctx.guild).slow_mode()
        
        # Join voice channel if not already connected
        if not ctx.guild.voice_client or ctx.guild.voice_client.channel != voice_channel:
            if ctx.guild.voice_client:
                await ctx.guild.voice_client.disconnect(force=True)
            try:
                await voice_channel.connect()
            except discord.ClientException:
                return await ctx.send("I couldn't connect to your voice channel. Please try again.")
        
        # Create TTS audio
        tts = gtts.gTTS(text=text, lang=lang, slow=slow)
        
        # Save TTS audio to a bytes buffer
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        
        # Play the audio
        voice_client = ctx.guild.voice_client
        
        # Create audio source
        audio_source = discord.FFmpegPCMAudio(fp, pipe=True)
        
        # Check if already playing, if so, wait until done
        if voice_client.is_playing():
            voice_client.stop()
        
        voice_client.play(audio_source)
        
        # Set up a task to disconnect after a period of inactivity
        if ctx.guild.id in self.voice_states:
            self.voice_states[ctx.guild.id].cancel()
        
        self.voice_states[ctx.guild.id] = asyncio.create_task(self._disconnect_after_inactivity(ctx.guild))
    
    async def _disconnect_after_inactivity(self, guild):
        """Disconnect from voice after 2 minutes of inactivity"""
        await asyncio.sleep(120)  # 2 minutes
        if guild.voice_client:
            await guild.voice_client.disconnect(force=True)
        if guild.id in self.voice_states:
            del self.voice_states[guild.id]

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        for task in self.voice_states.values():
            task.cancel()
        
        for guild_id, voice_client in list(self.bot.voice_clients):
            asyncio.create_task(voice_client.disconnect(force=True))

async def setup(bot):
    await bot.add_cog(TTS(bot))
