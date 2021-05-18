from __future__ import annotations

import abc
import asyncio
import random
import typing
from enum import Enum

import discord

if typing.TYPE_CHECKING:
    from extensions.game import MafiaGame
    from extensions.players import Player


class AttackType(Enum):
    basic = 1
    powerful = 2
    unstoppable = 3

    def __gt__(self, other: DefenseType):
        return self.value > other.value

    def __lt__(self, other: DefenseType):
        return self.value < other.value

    def __ge__(self, other: DefenseType):
        return self.value >= other.value

    def __le__(self, other: DefenseType):
        return self.value <= other.value


class DefenseType(Enum):
    basic = 1
    powerful = 2
    unstoppable = 3

    def __gt__(self, other: AttackType):
        return self.value > other.value

    def __lt__(self, other: AttackType):
        return self.value < other.value

    def __ge__(self, other: AttackType):
        return self.value >= other.value

    def __le__(self, other: AttackType):
        return self.value <= other.value


class Role(abc.ABC):
    def __init__(self, member: discord.Member):
        self.member = member

    # The ID that will be used to identify roles for config
    id: int = None
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
    attack_type: AttackType = None
    defense_type: DefenseType = None

    is_godfather: bool = False

    async def night_task(self, game: MafiaGame) -> None:
        return

    async def post_night_task(self, game: MafiaGame) -> None:
        return

    async def day_task(self, game: MafiaGame) -> None:
        return

    def win_condition(self, game: MafiaGame) -> bool:
        raise NotImplementedError()

    def startup_channel_message(self, game: MafiaGame) -> str:
        return f"Your role is {self.role}\n{self.description}."

    def __str__(self) -> str:
        return self.__class__.__name__


class Citizen(Role):
    id = 0
    is_citizen = True
    short_description = "Stay alive and lynch all mafia"
    description = "Your win condition is lynching all mafia, you do not have a special role during the night"

    def win_condition(self, game):
        return game.total_mafia == 0


class Doctor(Citizen):
    id = 1
    defense_type = DefenseType.powerful
    short_description = "Save one person each night"
    description = (
        "During the night you can choose one person to save. "
        "They cannot be killed by a basic attack during that night"
    )

    async def night_task(self, game: MafiaGame):
        # Get everyone alive that isn't ourselves
        msg = "Please provide the name of one player you would like to save from being killed tonight"
        player = await self.wait_for_player(game, msg)
        player.protect(self)
        await self.channel.send("\N{THUMBS UP SIGN}")


class Sheriff(Citizen):
    id = 2
    attack_type = AttackType.basic
    short_description = "Try to shoot one bad person during the night"
    description = (
        "During the night you can choose one person to shoot. "
        "If they are mafia, they will die... however if they are a citizen, you die instead"
    )
    can_kill_mafia_at_night = True

    async def night_task(self, game):
        # Get everyone alive that isn't ourselves
        msg = "If you would like to shoot someone tonight, provide just their name"
        player = await self.wait_for_player(game, msg)

        # Handle what happens if their choice is right/wrong
        if player.is_citizen or (
            player.disguised_as and player.disguised_as.is_citizen
        ):
            self.kill(self)
        else:
            player.kill(self)
        await self.channel.send("\N{THUMBS UP SIGN}")


class Jailor(Citizen):
    id = 3
    is_jailor: bool = True
    jails: int = 3
    jailed: Player = None
    attack_type = AttackType.unstoppable
    defense_type = DefenseType.powerful
    short_description = "Jail someone to talk to them during the night"
    description = (
        "Each night you can choose to jail one person, during that night they "
        "will be placed in a jail channel, everything you say in this channel will be sent "
        "to the jail, allowing you to converse with them without revealing your identity\n\n"
        "**You only have 3 jails total, use them wisely**"
    )

    async def day_task(self, game: MafiaGame):
        if self.jails <= 0:
            return
        msg = "If you would like to jail someone tonight, provide just their name"
        player = await self.wait_for_player(game, msg)
        player.night_role_blocked = True
        player.jail(self)
        self.jailed = player

        self.jails -= 1
        await self.channel.send(
            f"{player.member.name} has been jailed. During the night "
            "anything you say in here will be sent there, and vice versa. "
            "If you say just `Execute` they will be executed"
        )

    async def night_task(self, game: MafiaGame):
        if self.jailed:
            await game.jail.set_permissions(self.jailed.member, read_messages=True)
            # Make sure to start the unjailing process
            game.ctx.create_task(self.unjail(game))

            # Handle the swapping of messages from the jailed player
            def check(m):
                # If the jailor is the one talking in his channel
                if m.channel == self.channel and m.author == self.member:
                    if m.content == "Execute":
                        self.jailed.kill(self)
                        game.ctx.create_task(
                            game.jail.set_permissions(
                                self.jailed.member, send_messages=False
                            )
                        )
                        game.ctx.create_task(
                            game.jail.send("The Jailor has executed you!")
                        )
                        return True
                    else:
                        game.ctx.create_task(game.jail_webhook.send(m.content))
                # If the jailed is the one talking in the jail channel
                elif m.channel == game.jail and m.author == self.jailed:
                    game.ctx.create_task(
                        self.channel.send(f"{self.jailed.member.name}: {m.content}")
                    )

                return False

            await game.ctx.bot.wait_for("message", check=check)

    async def unjail(self, game: MafiaGame):
        member = self.jailed.member
        await asyncio.sleep(game._config.night_length)
        self.jailed = None
        await game.jail.set_permissions(member, read_messages=False)


class PI(Citizen):
    id = 4
    short_description = "Investigate the alliances of members"
    description = (
        "Every night you can investigate "
        "2 people, and see if their alignment is the same"
    )

    async def night_task(self, game):
        # Get everyone alive
        choices = [p.member.name for p in game.players if not p.dead and p != self]
        msg = "Who is the first person you want to investigate"
        player1 = await self.wait_for_player(game, msg, choices=choices)
        choices.remove(player1.member.name)

        while True:
            msg = "Who is the second person you want to investigate"
            player2 = await self.wait_for_player(game, msg, choices=choices)
            if player2 == player1:
                await self.channel.send("You can't choose the same person twice")
            else:
                break

        # Now compare the two people
        if (player1.is_citizen and player2.is_citizen) or (
            player1.is_mafia and player2.is_mafia
        ):
            await self.channel.send(
                f"{player1.member.mention} and {player2.member.mention} have the same alignment"
            )
        else:
            await self.channel.send(
                f"{player1.member.mention} and {player2.member.mention} do not have the same alignment"
            )


class Lookout(Citizen):
    id = 5
    watching: Player = None
    short_description = "Watch someone each night to see who visits them"
    description = (
        "Your job is to watch carefully, every night you can watch one person "
        "and will see who has visited them"
    )

    async def night_task(self, game: MafiaGame):
        msg = "Provide the player you want to watch tonight, at the end of the night I will let you know who visited them"
        self.watching = await self.wait_for_player(game, msg)
        await self.channel.send("\N{THUMBS UP SIGN}")

    async def post_night_task(self, game: MafiaGame):
        if self.watching is None:
            return

        visitors = self.watching.visited_by

        if visitors:
            fmt = "\n".join(p.member.name for p in visitors)
            msg = f"{self.watching.member.name} was visited by:\n{fmt}"
            await self.channel.send(msg)
        else:
            await self.channel.send(
                f"{self.watching.member.name} was not visited by anyone"
            )

        self.watching = None


class Mafia(Role):
    id = 75
    is_mafia = True
    attack_type = AttackType.basic
    description = (
        "Your win condition is to have majority of townsfolk be mafia. "
        "During the night you and your mafia buddies must agree upon 1 person to kill that night"
    )

    def win_condition(self, game):
        if game.is_day:
            # If any citizen can kill during the night, then we cannot guarantee
            # a win
            if any(
                player.can_kill_mafia_at_night
                for player in game.players
                if not player.dead
            ):
                return False
            else:
                return game.total_mafia >= game.total_alive / 2
        else:
            return game.total_mafia > game.total_alive / 2


class Janitor(Mafia):
    id = 76
    cleans: int = 3
    limit = 1
    description = (
        "Your job is to clean, clean, clean. "
        "Choose a member to clean up after during the night... if they do for ANY reason "
        "their dead body will be cleaned up, and the town will not be notified of the death. "
        "You will also receive information about what role that player was"
    )
    short_description = "Clean up any mess left by other mafia members"

    async def night_task(self, game: MafiaGame):
        if self.cleans <= 3:
            return

        msg = "Provide the player you want to clean tonight"
        player = await self.wait_for_player(game, msg)
        player.clean(self)
        await self.channel.send("\N{THUMBS UP SIGN}")
        self.cleans -= 1


class Disguiser(Mafia):
    id = 77
    short_description = "Disguise a mafia member as a non-mafia member"
    description = (
        "Your job is to help disguise your mafia buddies, each night choose one "
        "mafia member and one non mafia member. The mafia member will be disguised as the non mafia member"
    )

    async def night_task(self, game):
        # Get mafia and non-mafia
        mafia = [p.member.name for p in game.players if not p.dead and p.is_mafia]
        non_mafia = [
            p.member.name for p in game.players if not p.dead and not p.is_mafia
        ]
        msg = "Choose the mafia member you want to disguise"
        player1 = await self.wait_for_player(game, msg, choices=mafia)

        msg = (
            f"Choose the non-mafia member you want to disguise {player1.member.name} as"
        )
        player2 = await self.wait_for_player(game, msg, choices=non_mafia)

        if not player1.jailed and not player2.jailed:
            player1.disguise(player2, self)
        await self.channel.send("\N{THUMBS UP SIGN}")


class Independent(Role):
    is_independent = True


class Survivor(Independent):
    id = 150
    vests: int = 4
    win_is_multi = True
    defense_type = DefenseType.basic
    short_description = "Survive!"
    description = (
        "You must survive, each night you have the choice to use a bulletproof "
        "vest which will save you from a basic attack. You only have 4 vests"
    )

    def win_condition(self, game: MafiaGame) -> bool:
        return not self.dead

    async def night_task(self, game: MafiaGame):
        if self.vests <= 0:
            return

        msg = await self.channel.send(
            "Click the reaction if you want to protect yourself tonight "
            f"(You have {self.vests} vests remaining)"
        )
        await msg.add_reaction("\N{THUMBS UP SIGN}")

        def check(p):
            return (
                p.message_id == msg.id
                and p.user_id == self.member.id
                and str(p.emoji) == "\N{THUMBS UP SIGN}"
            )

        await game.ctx.bot.wait_for("raw_reaction_add", check=check)
        self.vests -= 1
        self.protected_by = self


class Jester(Independent):
    id = 151
    limit = 1
    short_description = "Your goal is to be killed by the town"
    description = "Your win condition is getting lynched or killed by the innocent"

    def win_condition(self, game):
        return self.lynched or (
            self.dead and self.killed_by and not self.killed_by.is_mafia
        )


class Executioner(Independent):
    id = 152
    limit = 1
    target = None
    short_description = "Your goal is to get your target lynched"
    description = (
        "Your win condition is getting a certain player lynched. If they "
        "die without getting lynched, you become a Jester. Your goal is to then get "
        "lynched yourself"
    )

    def startup_channel_message(self, game: MafiaGame):
        self.target = random.choice([p for p in game.players if p.is_citizen])
        self.target.executionor_target = self.player
        self.description += f". Your target is {self.target.member.mention}"
        return super().startup_channel_message(game)

    def win_condition(self, game: MafiaGame):
        return (
            # If target is lynched
            self.target.lynched
            # If target is dead by not lynching, and WE'RE lynched
            or (self.target.dead and not self.target.lynched and self.lynched)
            # If we were killed by someone who isn't mafia
            or (self.dead and self.killed_by and not self.killed_by.is_mafia)
        )


class Arsonist(Independent):
    id = 153
    attack_type = AttackType.unstoppable
    defense_type = DefenseType.basic
    short_description = "Burn them all"
    description = (
        "Your job is simple, douse everyone in fuel and ignite them. You "
        "win if everyone has been ignited and you are the last person left"
    )

    def __init__(self, discord_member: discord.Member):
        super().__init__(discord_member)

    async def night_task(self, game: MafiaGame):
        # We have permanent basic defense, according to ToS
        self.protected_by = self

        doused = [p for p in game.players if p.doused and not p.dead]
        doused_msg = "\n".join(p.member.name for p in doused)
        undoused = [p.member.name for p in game.players if not p.doused and not p.dead]
        msg = f"Doused targets:\n\n{doused_msg}\n\nChoose a target to douse, if you choose yourself you will ignite all doused targets"

        player = await self.wait_for_player(
            game, msg, only_others=False, choices=undoused
        )

        # Ignite
        if player == self:
            for player in doused:
                player.kill(self)
        else:
            player.doused = True
            player.visit(self)

        await self.channel.send("\N{THUMBS UP SIGN}")

    def win_condition(self, game: MafiaGame) -> bool:
        return game.total_alive == 1 and not self.dead


__special_mafia__ = (Janitor, Disguiser)
__special_citizens__ = (Doctor, Sheriff, PI, Jailor, Lookout)
__special_independents__ = (Jester, Executioner, Arsonist, Survivor)


def setup(bot):
    bot.role_mapping = {"Mafia": Mafia, "Citizen": Citizen}
    bot.role_mapping.update(**{c.__name__: c for c in __special_mafia__})
    bot.role_mapping.update(**{c.__name__: c for c in __special_citizens__})
    bot.role_mapping.update(**{c.__name__: c for c in __special_independents__})


def teardown(bot):
    del bot.role_mapping
