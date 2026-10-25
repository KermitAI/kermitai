from .verifykick import VerifyKick

__red_end_user_data_statement__ = "This cog stores server settings only, with no per-user data."


async def setup(bot):
    await bot.add_cog(VerifyKick(bot))
