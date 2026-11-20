from .marriage import Marriage

__red_end_user_data_statement__ = (
    "This cog stores member IDs, marriages, proposals, gift records, and preferences."
)


async def setup(bot):
    await bot.add_cog(Marriage(bot))
