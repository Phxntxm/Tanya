from __future__ import annotations

import abc
import asyncio
import random
import typing
from enum import Enum

import discord


if typing.TYPE_CHECKING:
    from mafia import MafiaGame, Player
    from utils.custom_bot import MafiaBot

__all__ = (
    "AttackType",
    "DefenseType",
    "Role",
    "Doctor",
    "Sheriff",
    "Jailor",
    "PI",
    "Lookout",
    "Mafia",
    "Janitor",
    "Disguiser",
    "Independent",
    "Survivor",
    "Jester",
    "Executioner",
    "Arsonist",
    "role_mapping",
)


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
    attack_type: typing.Optional[AttackType] = None
    defense_type: typing.Optional[DefenseType] = None

    # Messages sent based on different statuses
    save_message: str = "You were protected by an attack!"
    attack_message: str = ""
    suicide_message: str = ""

    is_godfather: bool = False
    is_citizen: bool = False
    is_mafia: bool = False
    is_independent: bool = False

    channel: typing.Optional[discord.TextChannel] = None

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
        return self.__class__.__name__


class Citizen(Role):
    is_citizen = True
    short_description = "Stay alive and lynch all mafia"
    description = "Your win condition is lynching all mafia, you do not have a special role during the night"

    def win_condition(self, game: MafiaGame, player: Player):
        return game.total_mafia == 0


class Doctor(Citizen):
    defense_type = DefenseType.powerful
    short_description = "Save one person each night"
    description = (
        "During the night you can choose one person to save. "
        "They cannot be killed by a basic attack during that night"
    )
    save_message = "You were healed by the doctor!"

    async def night_task(self, game: MafiaGame, player: Player):
        # Get everyone alive that isn't ourselves
        msg = (
            "Please provide **the number next to** the name of one player "
            "you would like to save from being killed tonight"
        )
        target = await player.wait_for_player(game, msg)
        target.protect(player)
        await player.channel.send(
            f"\U0001f3e5 You are protecting {target.member.name} tonight"
        )


class Sheriff(Citizen):
    attack_type = AttackType.basic
    short_description = "Try to shoot one bad person during the night"
    description = (
        "During the night you can choose one person to shoot. "
        "If they are mafia, they will die... however if they are a citizen, you die instead"
    )
    can_kill_mafia_at_night = True
    attack_message = "{killed.member.name} ({killed}) has been shot by the sherrif!"
    suicide_message = "{killed.member.name} ({killed}) regretted what they've done, and shot themselves"

    async def night_task(self, game: MafiaGame, player: Player):
        # Get everyone alive that isn't ourselves
        msg = "If you would like to shoot someone tonight, provide just **the number next to** their name"
        target = await player.wait_for_player(game, msg)

        # Handle what happens if their choice is right/wrong
        if target.is_citizen or (
            target.disguised_as and target.disguised_as.is_citizen
        ):
            player.kill(player)
            target.kill(player)
        else:
            target.kill(player)
        await player.channel.send(
            f"\U0001f52b {target.member.name} is getting killed tonight!"
        )


class Jailor(Citizen):
    is_jailor: bool = True
    jails: int = 3
    target: typing.Optional[Player] = None
    attack_type = AttackType.unstoppable
    defense_type = DefenseType.powerful
    short_description = "Jail someone to talk to them during the night"
    description = (
        "Each day you can choose to jail one person, during that night they "
        "will be placed in a jail channel, everything you say in this channel will be sent "
        "to the jail, allowing you to converse with them without revealing your identity\n\n"
        "**You only have 3 jails total, use them wisely**"
    )
    attack_message = "{killed.member.name} ({killed}) has been executed by the Jailor!"
    save_message = "Someone tried to attack you last night, but you were jailed!"

    async def day_task(self, game: MafiaGame, player: Player):
        if self.jails <= 0:
            return
        msg = "If you would like to jail someone tonight, provide just **the number next to** their name"
        target = await player.wait_for_player(game, msg)
        target.night_role_blocked = True
        target.jail(player)
        self.target = target

        self.jails -= 1
        await player.channel.send(
            f"\U0001f46e {target.member.name} has been jailed. During the night "
            "anything you say in here will be sent there, and vice versa. "
            "If you say just `Execute` they will be executed"
        )

    async def night_task(self, game: MafiaGame, player: Player):
        if target := self.target:
            self.target = None
            await target.channel.send(
                f"{target.member.mention} You've been jailed! Messages from here on will be from/to the Jailor:"
                "-------------------------------------------"
            )

            # Handle the swapping of messages from the jailed player
            def check(m):
                # If the jailor is the one talking in his channel
                if m.channel == player.channel and m.author == player.member:
                    if m.content.lower() == "execute":
                        target.kill(player)
                        game.ctx.create_task(
                            target.channel.send("The Jailor has executed you!")
                        )
                        return True
                    else:
                        game.ctx.create_task(
                            target.channel.send(f"Jailor: {m.content}")
                        )
                # If the jailed is the one talking in the jail channel
                elif m.channel == target.channel and m.author == target.member:
                    game.ctx.create_task(
                        player.channel.send(f"{target.member.name}: {m.content}")
                    )

                return False

            await game.ctx.bot.wait_for("message", check=check)


class PI(Citizen):
    short_description = "Investigate the alliances of members"
    description = (
        "Every night you can investigate "
        "2 people, and see if their alignment is the same"
    )

    async def night_task(self, game: MafiaGame, player: Player):
        # Get everyone alive
        choices = [p.member.name for p in game.players if not p.dead and p != self]
        msg = "Choose **the number next to** the first person you want to investigate"
        player1 = await player.wait_for_player(game, msg, choices=choices)
        choices.remove(player1.member.name)

        while True:
            msg = "Choose **the number next to** the second person you want to investigate"
            player2 = await player.wait_for_player(game, msg, choices=choices)
            if player2 == player1:
                await player.channel.send("You can't choose the same person twice")
            else:
                break

        # Now compare the two people
        if (player1.is_citizen and player2.is_citizen) or (
            player1.is_mafia and player2.is_mafia
        ):
            await player.channel.send(
                f"{player1.member.mention} and {player2.member.mention} have the same alignment"
            )
        else:
            await player.channel.send(
                f"{player1.member.mention} and {player2.member.mention} do not have the same alignment"
            )


class Lookout(Citizen):
    watching: typing.Optional[Player] = None
    short_description = "Watch someone each night to see who visits them"
    description = (
        "Your job is to watch carefully, every night you can watch one person "
        "and will see who has visited them"
    )

    async def night_task(self, game: MafiaGame, player: Player):
        msg = "Provide **the number next to** the player you want to watch tonight, at the end of the night I will let you know who visited them"
        self.watching = await player.wait_for_player(game, msg)
        await player.channel.send(
            f"\U0001f440 You'll be watching {self.watching.member.name} tonight"
        )

    async def post_night_task(self, game: MafiaGame, player: Player):
        if self.watching is None:
            return

        visitors = self.watching.visited_by

        if visitors:
            fmt = "\n".join(p.member.name for p in visitors)
            msg = f"{self.watching.member.name} was visited by:\n{fmt}"
            await player.channel.send(msg)
        else:
            await player.channel.send(
                f"{self.watching.member.name} was not visited by anyone"
            )

        self.watching = None


class Mafia(Role):
    is_mafia = True
    attack_type = AttackType.basic
    description = (
        "Your win condition is to have majority of townsfolk be mafia. "
        "During the night you and your mafia buddies must agree upon 1 person to kill that night"
    )
    attack_message = "{killed.member.name} ({killed}) has been killed by the mafia!"

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
    description = (
        "Your job is to clean, clean, clean. "
        "Choose a member to clean up after during the night... if they do for ANY reason "
        "their dead body will be cleaned up, and the town will not be notified of the death. "
        "You will also receive information about what role that player was"
    )
    short_description = "Clean up any mess left by other mafia members"

    async def night_task(self, game: MafiaGame, player: Player):
        if self.cleans <= 0:
            return

        msg = "Provide **the number next to** the player you want to clean tonight"
        player = await player.wait_for_player(game, msg)
        player.clean(player)
        await player.channel.send(
            f"\U0001f9f9 There won't be a sign of {player.member.name} left tonight"
        )
        self.cleans -= 1


class Disguiser(Mafia):
    short_description = "Disguise a mafia member as a non-mafia member"
    description = (
        "Your job is to help disguise your mafia buddies, each night choose one "
        "mafia member and one non mafia member. The mafia member will be disguised as the non mafia member"
    )

    async def night_task(self, game: MafiaGame, player: Player):
        # Get mafia and non-mafia
        mafia = [p.member.name for p in game.players if not p.dead and p.is_mafia]
        non_mafia = [
            p.member.name for p in game.players if not p.dead and not p.is_mafia
        ]
        msg = "Choose **the number next to** the mafia member you want to disguise"
        player1 = await player.wait_for_player(game, msg, choices=mafia)

        msg = f"Choose **the number next to** the non-mafia member you want to disguise {player1.member.name} as"
        player2 = await player.wait_for_player(game, msg, choices=non_mafia)

        if not player1.jailed and not player2.jailed:
            player1.disguise(player2, player)
        await player.channel.send(
            f"\U0001f575\U0000fe0f {player1.member.name} has been disguised as {player2.member.name}"
        )


class Independent(Role):
    is_independent = True


class Survivor(Independent):
    vests: int = 4
    win_is_multi = True
    defense_type = DefenseType.basic
    short_description = "Survive!"
    description = (
        "You must survive, each night you have the choice to use a bulletproof "
        "vest which will save you from a basic attack. You only have 4 vests"
    )
    save_message = "Your vest saved you!"

    def win_condition(self, game: MafiaGame, player: Player) -> bool:
        return not player.dead

    async def night_task(self, game: MafiaGame, player: Player):
        if self.vests <= 0:
            return

        msg = await player.channel.send(
            "Click the reaction if you want to protect yourself tonight "
            f"(You have {self.vests} vests remaining)"
        )
        await msg.add_reaction("\N{THUMBS UP SIGN}")

        def check(p):
            return (
                p.message_id == msg.id
                and p.user_id == player.member.id
                and str(p.emoji) == "\N{THUMBS UP SIGN}"
            )

        await game.ctx.bot.wait_for("raw_reaction_add", check=check)
        self.vests -= 1
        player.protected_by = player

        await player.channel.send("\U0001f9ba You're protecting yourself tonight")


class Jester(Independent):
    limit = 1
    short_description = "Your goal is to be killed by the town"
    description = "Your win condition is getting lynched or killed by the innocent"

    def win_condition(self, game: MafiaGame, player: Player):
        return player.lynched or (
            player.dead and player.attacked_by and not player.attacked_by.is_mafia
        )


class Executioner(Independent):
    limit = 1
    defense_type = DefenseType.basic
    short_description = "Your goal is to get your target lynched"
    description = (
        "Your win condition is getting a certain player lynched. If they "
        "die without getting lynched, you become a Jester. Your goal is to then get "
        "lynched yourself"
    )
    save_message = "You were attacked, but your defense is too strong!"

    async def night_task(self, game: MafiaGame, player: Player) -> None:
        # We have permanent basic defense, according to ToS
        player.protected_by = player

    def startup_channel_message(self, game: MafiaGame, player: Player):
        self.target = random.choice([p for p in game.players if p.is_citizen])
        self.target.executionor_target = player
        self.description += f". Your target is {self.target.member.mention}"
        return super().startup_channel_message(game, player)

    def win_condition(self, game: MafiaGame, player: Player):
        return self.target.lynched


class Arsonist(Independent):
    attack_type = AttackType.unstoppable
    defense_type = DefenseType.basic
    short_description = "Burn them all"
    description = (
        "Your job is simple, douse everyone in fuel and ignite them. You "
        "win if everyone has been ignited and you are the last person left"
    )
    attack_message = (
        "{killed.member.name} ({killed}) has been set ablaze by the Arsonist!"
    )
    save_message = "You were attacked, but your defense is too strong!"

    async def night_task(self, game: MafiaGame, player: Player):
        # We have permanent basic defense, according to ToS
        player.protected_by = player

        doused = [p for p in game.players if p.doused and not p.dead]
        doused_msg = "\n".join(p.member.name for p in doused)
        undoused = [p.member.name for p in game.players if not p.doused and not p.dead]
        msg = (
            f"Doused targets:\n\n{doused_msg}\n\n"
            "Choose **the number next to** a target to douse, "
            "if you choose yourself you will ignite all doused targets"
        )

        player = await player.wait_for_player(
            game, msg, only_others=False, choices=undoused
        )

        # Ignite
        if player == player:
            for player in doused:
                player.kill(player)
            await player.channel.send(f"\U0001f525 They'll all burn")
        else:
            player.doused = True
            player.visit(player)
            await player.channel.send(
                f"\U0001f6e2\U0000fe0f {player.member.name} has been doused"
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
        query = "SELECT id, name, alignment, attack_level, defence_level FROM roles"
        data = await conn.fetch(query)

    for x in data:
        r = role_mapping[x["name"]]
        r.id = x["id"]
        if x["alignment"] == 1:
            r.is_citizen = True
        elif x["alignment"] == 2:
            r.is_independent = True
        else:
            r.is_mafia = True

        r.attack_type = AttackType(x["attack_level"])
        r.defense_type = DefenseType(x["defence_level"])

    if not all(x.id is not None for x in role_mapping.values()):
        async with bot.db.acquire() as conn:
            for x in role_mapping.values():
                if x.id is None:
                    x.id = await conn.fetchval(
                        "INSERT INTO roles (name, alignment, attack_level, defence_level) VALUES ($1, $2, $3, $4) RETURNING id",
                        x.name,
                        1 if x.is_citizen else (2 if x.is_independent else 3),
                    )

        return
        raise RuntimeError(
            f"Missing role information in the database for roles {', '.join(x.__name__ for x in role_mapping.values() if x.id is None)}"
        )
