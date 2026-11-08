from .addembed import AddEmbed

__red_end_user_data_statement__ = "Stores embed message/channel IDs, button settings and allowed role IDs. Contributions and member mentions are published only in Discord messages; staff can remove those messages in Discord."


async def setup(bot):
    await bot.add_cog(AddEmbed(bot))
