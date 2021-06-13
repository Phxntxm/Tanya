import collections
import typing

import discord
from discord.ext import commands

if typing.TYPE_CHECKING:
    from custom_models import MafiaBot, Context


class Stats(commands.Cog):
    @commands.command("stats")
    async def stats(
        self,
        ctx: Context,
        user: typing.Optional[discord.User] = None,
        only_this_server=False,
    ):
        """
        Fetches stats for yourself, or for a specific user.
        You can put 'yes' after the user to fetch stats for only this server
        """
        if user is None:
            _user = ctx.author
        else:
            _user = user

        if only_this_server and not ctx.guild:
            return await ctx.reply(
                "You cannot get server stats in dms", mention_author=False
            )

        query = """
        SELECT
            games.id,
            players.user_id,
            roles.name,
            roles.alignment,
            players.win,
            players.die,
            killed.killer,
            killed.suicide,
            killed.lynch,
            kills.killed
        FROM
            players
        LEFT JOIN games
            ON games.id = players.game_id
        LEFT JOIN roles
            ON roles.id = players.role
        LEFT JOIN kills killed
            ON killed.killed = players.user_id AND killed.game_id = games.id
        LEFT JOIN kills
            ON kills.killer = players.user_id AND kills.game_id = games.id
        WHERE players.user_id = $1
        """

        if only_this_server:
            query += " AND guild_id = $2"
            args = (_user.id, ctx.guild.id)
        else:
            args = (_user.id,)

        async with ctx.acquire() as conn:
            player = await conn.fetch(query, *args)

        if not player:
            return await ctx.reply(f"No stats for {_user}", mention_author=False)

        games = set()
        wins = suicides = lynches = mafia = citizen = independent = kills = deaths = 0
        roles = collections.Counter()

        for row in player:
            games.add(row["id"])
            roles.update([row["name"]])

            if row["win"]:
                wins += 1
            if row["alignment"] == 1:
                citizen += 1
            if row["alignment"] == 2:
                independent += 1
            if row["alignment"] == 3:
                mafia += 1
            if row["killer"]:
                deaths += 1
            if row["killed"]:
                kills += 1
            if row["lynch"]:
                lynches += 1
            if row["suicide"]:
                suicides += 1

        top_role = roles.most_common(1)[0]
        apost = "'"  # stupid fstrings

        fmt = (
            f"{'You have' if _user == ctx.author else f'{_user} has'} played {len(games)} game{'s' if len(games) != 1 else ''}"
            f"{' in this server' if only_this_server else ''}, won {wins} game{'s' if wins != 1 else ''}, "
            f"killed {kills} {'people' if kills != 1 else 'person'}, died {deaths} time{'s' if deaths != 1 else ''}, committed suicide "
            f"{suicides} time{'s' if suicides != 1 else ''}, been lynched {lynches} time{'s' if lynches != 1 else ''} and been mafia "
            f"{mafia} time{'s' if mafia != 1 else ''}.\n\n{'Your' if _user == ctx.author else f'{_user.name}{apost}s'} most common role "
            f"{'here ' if only_this_server else ''}is {top_role[0]}, with {top_role[1]} game{'s' if top_role[1] != 1 else ''}."
        )
        await ctx.reply(fmt, mention_author=False)

    @commands.command("serverstats", aliases=["guildstats"])
    @commands.guild_only()
    async def guild_stats(self, ctx: Context):
        """
        Fetches stats for the current server. Cannot be used in dms.
        """

        async with ctx.acquire() as conn:
            query = """
            SELECT
                games.id,
                players.user_id,
                roles.alignment,
                players.win,
                players.die,
                kills.killer,
                kills.suicide,
                kills.lynch
            FROM
                players
            LEFT JOIN games
                ON games.id = players.game_id
            LEFT JOIN roles
                ON roles.id = players.role
            LEFT JOIN kills
                ON killed = players.user_id AND kills.game_id = games.id
            WHERE games.guild_id = $1
            """

            players = await conn.fetch(query, ctx.guild.id)

        games = set()
        suicide_count = kill_count = lynch_count = mafia_wins = ind_wins = cit_wins = 0

        for row in players:
            games.add(row["id"])
            if row["suicide"]:
                suicide_count += 1
            if row["killer"]:
                suicide_count += 1
            if row["lynch"]:
                lynch_count += 1
            if row["win"] and row["alignment"] == 3:
                mafia_wins += 1
            if row["win"] and row["alignment"] == 2:
                ind_wins += 1
            if row["win"] and row["alignment"] == 1:
                cit_wins += 1

        game_count = len(games)

        fmt = (
            f"This server has seen {game_count} game{'s' if game_count != 1 else ''}, "
            f"{suicide_count} suicide{'s' if suicide_count != 1 else ''}, "
            f"{kill_count} kill{'s' if kill_count != 1 else ''}, "
            f"{lynch_count} lynch{'es' if lynch_count != 1 else ''}, "
            f"{mafia_wins} win{'s' if mafia_wins != 1 else ''} by the mafia, "
            f"{ind_wins} win{'s' if ind_wins != 1 else ''} from independents, "
            f"and {cit_wins} win{'s' if cit_wins != 1 else ''} from civilians."
        )
        await ctx.reply(fmt, mention_author=False)


def setup(bot: "MafiaBot"):
    bot.add_cog(Stats())
