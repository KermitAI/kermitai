from .birthday import Birthday

__red_end_user_data_statement__ = (
    "Stores each member's birthday month and day, Discord user ID, and last announcement "
    "date per server. Members can delete their data with the birthday forget command."
)


async def setup(bot):
    await bot.add_cog(Birthday(bot))
