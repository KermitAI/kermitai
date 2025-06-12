from redbot.core.bot import Red
from .rolecloner import rolecloner

async def setup(bot: Red):
    bot.add_cog(rolecloner(bot))