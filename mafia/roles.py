from __future__ import annotations

import abc
import collections
import random
import typing

import discord
from interactions import Vote
from interactions.select import SelectView, DisguiserSelect, player_select
from utils import Alignment, AttackType, DefenseType
from utils.misc import get_mafia_player

if typing.TYPE_CHECKING:
    from custom_models import MafiaBot

    from mafia import MafiaGame, Player

__all__ = (
    "Role",
    "role_mapping",
    "initialize_db",
)


class Role(abc.ABC):
    # The ID that will be used to identify roles for config
    id: int = -1
    # Needed to check win condition for mafia during day, before they kill
    can_kill_mafia_at_night: bool = False
    # This boolean determines if their win condition only applies
    # on other win/loss conditions. As in, they win alongside whatever
    # else happens. This implies that this should only be determined at the
    # END of the game
    win_is_multi: bool = False
    # The amount that can be used per game
    limit: int = 0
    # The attack and defense this role can have
    attack_type: AttackType = AttackType.none
    defense_type: DefenseType = DefenseType.none

    # Messages sent based on different statuses
    save_message: str = "You were protected by an attack!"
    attack_message: str = ""
    suicide_message: str = ""

    alignment: typing.Optional[Alignment] = None

    is_godfather: bool = False
    cleaned: bool = False

    channel: discord.TextChannel

    description = ""
    short_description = ""

    async def night_task(self, game: MafiaGame, player: Player) -> None:
        return

    async def post_night_task(self, game: MafiaGame, player: Player) -> None:
        return

    async def day_task(self, game: MafiaGame, player: Player) -> None:
        return

    def win_condition(self, game: MafiaGame, player: Player) -> bool:
        raise NotImplementedError()

    def startup_channel_message(self, game: MafiaGame, player: Player) -> str:
        return f"Your role is {self}\n{self.description}."

    def __str__(self) -> str:
        return self.__class__.__name__ if not self.cleaned else "Cleaned"


class Citizen(Role):
    def win_condition(self, game: MafiaGame, player: Player):
        return game.total_mafia == 0


class Doctor(Citizen):
    async def night_task(self, game: MafiaGame, player: Player):
        # Get everyone alive that isn't ourselves
        msg = "Please select the player you would like to save tonight"
        choices = game.alive_players
        choices.remove(player)
        target = await player_select(
            player,
            game,
            msg,
            choices,
            timeout=game._config.night_length,
        )
        if target is not None:
            target = get_mafia_player(game, target)
            await player.send_message(
                content=f"\U0001f3e5 You are protecting {target.member.name} tonight"
            )


class Sheriff(Citizen):
    can_kill_mafia_at_night = True

    async def night_task(self, game: MafiaGame, player: Player):
        # Get everyone alive that isn't ourselves
        msg = "If you would like to shoot someone tonight, select them"
        choices = game.alive_players
        choices.remove(player)
        target = await player_select(
            player,
            game,
            msg,
            choices,
            timeout=game._config.night_length,
        )
        if target is not None:
            target = get_mafia_player(game, target)

            # Handle what happens if their choice is right/wrong
            if target.role.alignment is Alignment.citizen or (
                target.disguised_as
                and target.disguised_as.role.alignment is Alignment.citizen
            ):
                player.kill(player)
                target.kill(player)
            else:
                target.kill(player)
            await player.send_message(
                content=f"\U0001f52b {target.member.name} is getting killed tonight!"
            )


class Jailor(Citizen):
    is_jailor: bool = True
    jails: int = 3
    target: typing.Optional[Player] = None

    async def day_task(self, game: MafiaGame, player: Player):
        if self.jails <= 0:
            return
        msg = "If you would like to jail someone tonight, select them"
        choices = game.alive_players
        choices.remove(player)
        target = await player_select(
            player,
            game,
            msg,
            choices,
            timeout=game._config.night_length,
        )
        if target is not None:
            target = get_mafia_player(game, target)

            target.night_role_blocked = True
            target.jail(player)
            self.target = target

            self.jails -= 1
            await player.send_message(
                content=f"\U0001f46e {target.member.name} has been jailed. During the night "
                "anything you say in here will be sent there, and vice versa. "
                "If you say just `Execute` they will be executed"
            )

    async def night_task(self, game: MafiaGame, player: Player):
        if target := self.target:

            # Allow target access to jailed channel
            await game.jailed.set_permissions(target.member, read_messages=True)

            await game.jailed.send(
                content=f"{target.member.mention} You've been jailed! Messages from here on will be from/to the Jailor:"
                "-------------------------------------------"
            )

            # Handle the swapping of messages from the jailed player
            def check(m):
                # If the jailor is the one talking in his channel
                if m.channel == game.jailor and m.author == player.member:
                    if m.content.lower() == "execute":
                        target.kill(player)
                        game.ctx.create_task(
                            game.jailed.send("The Jailor has executed you!")
                        )
                        return True
                    else:
                        game.ctx.create_task(game.jailed.send(f"Jailor: {m.content}"))
                # If the jailed is the one talking in the jail channel
                elif m.channel == game.jailed and m.author == target.member:
                    game.ctx.create_task(
                        game.jailor.send(f"{target.member.name}: {m.content}")
                    )

                return False

            await game.ctx.bot.wait_for("message", check=check)

    async def post_night_task(self, game: MafiaGame, player: Player) -> None:
        if target := self.target:
            self.target = None
            await game.jailed.set_permissions(target.member, overwrite=None)
            await game.jailed.purge(limit=None)


class PI(Citizen):
    async def night_task(self, game: MafiaGame, player: Player):
        choices = game.alive_players
        choices.remove(player)

        msg = "Choose the people you would like to investigate"
        choices = await SelectView(
            msg, choices, player.interaction, min_selection=2, max_selection=2
        ).start()

        player1, player2 = choices
        player1 = get_mafia_player(game, player1)
        player2 = get_mafia_player(game, player2)

        # Now compare the two people
        if (
            player1.role.alignment is Alignment.citizen
            and player2.role.alignment is Alignment.citizen
        ) or (
            player1.role.alignment is Alignment.mafia
            and player2.role.alignment is Alignment.mafia
        ):
            await player.send_message(
                content=f"{player1.member.mention} and {player2.member.mention} have the same alignment"
            )
        else:
            await player.send_message(
                content=f"{player1.member.mention} and {player2.member.mention} do not have the same alignment"
            )


class Lookout(Citizen):
    watching: typing.Optional[Player] = None

    async def night_task(self, game: MafiaGame, player: Player):
        msg = "Provide the player you want to watch tonight, at the end of the night I will let you know who visited them"
        choices = game.alive_players
        choices.remove(player)
        target = await player_select(
            player, game, msg, choices, timeout=game._config.night_length
        )
        if target is not None:
            self.watching = get_mafia_player(game, target)
            await player.send_message(
                content=f"\U0001f440 You'll be watching {self.watching.member.name} tonight"
            )

    async def post_night_task(self, game: MafiaGame, player: Player):
        if self.watching is None:
            return

        visitors = self.watching.visited_by

        if visitors:
            fmt = "\n".join(p.member.name for p in visitors)
            msg = f"{self.watching.member.name} was visited by:\n{fmt}"
            await player.send_message(content=msg)
        else:
            await player.send_message(
                content=f"{self.watching.member.name} was not visited by anyone"
            )

        self.watching = None


class Mafia(Role):
    def win_condition(self, game: MafiaGame, player: Player):
        if game.is_day:
            # If any citizen can kill during the night, then we cannot guarantee
            # a win
            if any(p.can_kill_mafia_at_night for p in game.players if not p.dead):
                return False
            else:
                return game.total_mafia >= game.total_alive / 2
        else:
            return game.total_mafia > game.total_alive / 2


class Janitor(Mafia):
    cleans: int = 3
    limit = 1

    async def night_task(self, game: MafiaGame, player: Player):
        if self.cleans <= 0:
            return

        msg = "Provide the player you want to clean tonight"
        choices = game.alive_players
        choices.remove(player)

        target = await player_select(
            player, game, msg, choices, timeout=game._config.night_length
        )
        if target is not None:
            player = get_mafia_player(game, target)
            player.clean(player)
            await player.send_message(
                content=f"\U0001f9f9 There won't be a sign of {player.member.name} left tonight"
            )
            self.cleans -= 1


class Disguiser(Mafia):
    async def night_task(self, game: MafiaGame, player: Player):
        # Get mafia and non-mafia
        mafia = [
            p.member.name
            for p in game.players
            if not p.dead and p.role.alignment is Alignment.mafia
        ]
        non_mafia = [
            p.member.name
            for p in game.players
            if not p.dead and p.role.alignment is not Alignment.mafia
        ]

        view = DisguiserSelect(
            "Choose the member to disguise, and who to disguise them as",
            mafia,
            non_mafia,
            game.inter_mapping[player.member.id],
        )
        if target := await view.start():
            player1, player2 = target
            player1 = get_mafia_player(game, player1)
            player2 = get_mafia_player(game, player2)

            if not player1.jailed and not player2.jailed:
                player1.disguise(player2, player)
            await player.send_message(
                content=f"\U0001f575\U0000fe0f {player1.member.name} has been disguised as {player2.member.name}"
            )


class Independent(Role):
    pass


class Survivor(Independent):
    vests: int = 4
    win_is_multi = True

    def win_condition(self, game: MafiaGame, player: Player) -> bool:
        return not player.dead

    async def night_task(self, game: MafiaGame, player: Player):
        if self.vests <= 0:
            return
        msg = f"Do you want to protect yourself tonight? {self.vests} vests remaining"

        view = Vote(
            msg,
            allowed=[player.member],
            # Just to ensure no race conditions happen,
            # only allow changing up to 5 seconds before night ends
            timeout=game._config.night_length - 5,
        )
        await player.send_message(
            msg=msg,
            view=Vote,
        )
        await view.wait()
        votes = collections.Counter(view.votes.values())
        result = votes.get("yes", 0) > 0

        if result:
            self.vests -= 1
            player.protected_by = player

            await player.send_message(
                content="\U0001f9ba You're protecting yourself tonight"
            )


class Jester(Independent):
    limit = 1

    def win_condition(self, game: MafiaGame, player: Player):
        return player.lynched or (
            player.dead
            and player.attacked_by
            and player.attacked_by.role.alignment is not Alignment.mafia
        )


class Executioner(Independent):
    limit = 1

    async def night_task(self, game: MafiaGame, player: Player) -> None:
        # We have permanent basic defense, according to ToS
        player.protected_by = player

    def startup_channel_message(self, game: MafiaGame, player: Player):
        possibilities = [
            p for p in game.players if p.role.alignment is Alignment.citizen
        ]

        if possibilities:
            self.target = random.choice(possibilities)
            self.target.executionor_target = player
            self.description += f". Your target is {self.target.member.mention}"
            return super().startup_channel_message(game, player)
        else:
            player.role = role_mapping["Jester"]()
            self.description = "There are no citizens this game, you've become a Jester! Your goal is to get lynched"
            return super().startup_channel_message(game, player)

    def win_condition(self, game: MafiaGame, player: Player):
        return self.target.lynched


class Arsonist(Independent):
    async def night_task(self, game: MafiaGame, player: Player):
        # We have permanent basic defense, according to ToS
        player.protected_by = player

        doused = [p for p in game.players if p.doused and not p.dead]
        doused_msg = "\n".join(p.member.name for p in doused)
        undoused = [p.member.name for p in game.players if not p.doused and not p.dead]
        msg = (
            f"Doused targets:\n\n{doused_msg}\n\nChoose a target to douse, "
            "if you choose yourself you will ignite all doused targets"
        )

        target = await player_select(
            player, game, msg, undoused, timeout=game._config.night_length
        )

        if target is not None:
            player = get_mafia_player(game, target)

            # Ignite
            if player == player:
                for player in doused:
                    player.kill(player)
                await player.send_message(content="\U0001f525 They'll all burn")
            else:
                player.doused = True
                player.visit(player)
                await player.send_message(
                    content=f"\U0001f6e2\U0000fe0f {player.member.name} has been doused"
                )

    def win_condition(self, game: MafiaGame, player: Player) -> bool:
        return game.total_alive == 1 and not player.dead


__special_mafia__ = (Janitor, Disguiser)
__special_citizens__ = (Doctor, Sheriff, PI, Jailor, Lookout)
__special_independents__ = (Jester, Executioner, Arsonist, Survivor)

role_mapping = {"Mafia": Mafia, "Citizen": Citizen}
role_mapping.update(**{c.__name__: c for c in __special_mafia__})
role_mapping.update(**{c.__name__: c for c in __special_citizens__})
role_mapping.update(**{c.__name__: c for c in __special_independents__})


async def initialize_db(bot: MafiaBot):
    async with bot.db.acquire() as conn:
        query = "SELECT * FROM roles"
        data = await conn.fetch(query)

    for row in data:
        role = role_mapping[row["name"]]

        role.id = row["id"]
        role.description = row["description"]
        role.short_description = row["blurb"]
        role.save_message = row["save_message"]
        role.attack_message = row["attack_message"]
        role.suicide_message = row["suicide_message"]
        role.alignment = Alignment(row["alignment"])
        role.attack_type = AttackType(row["attack_level"])
        role.defense_type = DefenseType(row["defense_level"])

    if not all(x.id is not None for x in role_mapping.values()):
        raise RuntimeError(
            f"Missing role information in the database for roles {', '.join(x.__name__ for x in role_mapping.values() if x.id is None)}"
        )
