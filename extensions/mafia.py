import asyncio
from discord.ext import commands


def stop_check():
    def predicate(ctx):
        game = ctx.bot.get_cog("Mafia").games.get(ctx.guild.id)

        if game and (
            ctx.author.guild_permissions.manage_channels
            or ctx.author == game[1].ctx.author
        ):
            return True
        return False

    return commands.check(predicate)


class Mafia(commands.Cog):
    games = {}
    # Useful for restarting a game, or getting info on the last game
    previous_games = {}

    @commands.group(invoke_without_command=True)
    async def mafia(self, ctx):
        pass

    @mafia.command(name="start")
    @commands.guild_only()
    @commands.max_concurrency(1, per=commands.BucketType.guild)
    async def mafia_start(self, ctx):
        """Start a game of mafia. Note that currently only one game can run at a time
        per server, this limit may be upped in the future"""
        # This can happen if we're redoing a game
        game = ctx.bot.MafiaGame(ctx)
        # Store task so it can be cancelled later
        task = ctx.bot.loop.create_task(game.play())
        self.games[ctx.guild.id] = (task, game)
        try:
            await task
        except asyncio.TimeoutError:
            pass
        # Remove game once it's done
        self.previous_games[ctx.guild.id] = game
        del self.games[ctx.guild.id]

    @mafia.command(name="redo")
    @commands.guild_only()
    @commands.max_concurrency(1, per=commands.BucketType.guild)
    async def mafia_redo(self, ctx):
        """Starts another game with the same configuration as the last"""
        game = self.previous_games.get(ctx.guild.id)
        if game:
            task = ctx.bot.loop.create_task(game.redo())
            self.games[ctx.guild.id] = (task, game)
            await task
            # Remove game once it's done
            self.previous_games[ctx.guild.id] = game
            del self.games[ctx.guild.id]
        else:
            await ctx.send("No previous game detected")

    @mafia.command(name="cleanup")
    @commands.has_permissions(manage_channels=True)
    @commands.guild_only()
    async def mafia_cleanup(self, ctx):
        """Cleans up all mafia channels. This usually shouldn't be needed, unless something
        went wrong with the bot's auto cleanup which happens a minute after a game finishes"""
        for category in ctx.guild.categories:
            if category.name == "MAFIA GAME":
                for channel in category.channels:
                    await channel.delete()
                await category.delete()

        await ctx.send("\N{THUMBS UP SIGN}")

    @mafia.command(name="stop", aliases=["cancel"])
    @stop_check()
    @commands.guild_only()
    async def mafia_stop(self, ctx):
        """Stops an ongoing game of Mafia"""
        await ctx.send("\N{THUMBS UP SIGN}")

        game = self.games.get(ctx.guild.id)
        if game is not None:
            del self.games[ctx.guild.id]
            task, game = game
            task.cancel()
            await game.cleanup_channels()

    @mafia_start.error
    async def clean_mafia_games(self, ctx, error):
        game = self.games.get(ctx.guild.id)
        if game is not None:
            del self.games[ctx.guild.id]
            task, game = game
            task.cancel()
            await game.cleanup_channels()


def setup(bot):
    bot.add_cog(Mafia())
