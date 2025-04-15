from redbot.core.bot import Red
from .tts import TTS

async def setup(bot: Red):
    await bot.add_cog(TTS(bot))
