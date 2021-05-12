from discord.ext import commands


class Mafia(commands.Cog):
    games = {}
    # Useful for restarting a game, or getting info on the last game
    previous_games = {}
    debug_game = None

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
        await task
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

    @mafia.command(name="stop")
    @commands.has_permissions(manage_channels=True)
    @commands.guild_only()
    async def mafia_stop(self, ctx):
        """Stops an ongoing game of Mafia"""
        game = self.games.get(ctx.guild.id)
        if game is not None:
            del self.games[ctx.guild.id]
            task, game = game
            task.cancel()
            await game.cleanup_channels()

        await ctx.message.add_reaction("\N{THUMBS UP SIGN}")

    @mafia.group(name="debug", invoke_without_command=True)
    @commands.is_owner()
    @commands.guild_only()
    @commands.max_concurrency(1, per=commands.BucketType.guild)
    async def mafia_debug(self, ctx):
        """Sets up a game with 5 players, all the author. Allows you to pick roles still"""
        amount_of_specials = [(k, 0) for k in ctx.bot.__special_roles__]
        menu = ctx.bot.MafiaMenu(source=ctx.bot.MafiaPages(amount_of_specials, ctx))

        menu.amount_of_players = 5
        menu.amount_of_mafia = 1
        await menu.start(ctx, wait=True)
        game = ctx.bot.MafiaGame(ctx)

        game._config = ctx.bot.MafiaGameConfig(
            menu.amount_of_mafia,
            menu.amount_of_citizens,
            [
                role
                for (role, amt) in amount_of_specials
                for i in range(amt)
                if role.is_mafia
            ],
            [
                role
                for (role, amt) in amount_of_specials
                for i in range(amt)
                if role.is_citizen
            ],
            ctx,
        )
        game._members = [
            ctx.author,
            ctx.author,
            ctx.author,
            ctx.author,
            ctx.author,
        ]
        task = ctx.bot.loop.create_task(game.start())
        self.debug_task = (task, game)
        await task

    @mafia_debug.command(name="stop")
    @commands.is_owner()
    @commands.guild_only()
    @commands.max_concurrency(1, per=commands.BucketType.guild)
    async def mafia_stop_debug(self, ctx):
        """Stops the debug game of Mafia"""
        if self.debug_task is not None:
            task, game = self.debug_task
            task.cancel()
            await game.cleanup_channels()

        await ctx.message.add_reaction("\N{THUMBS UP SIGN}")

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
