import discord
import random


class Player:
    is_mafia: bool = False
    is_citizen: bool = False
    is_independent: bool = False
    is_godfather: bool = False
    channel: discord.TextChannel = None
    # Dead is for someone who has been dead
    dead: bool = False
    # Use the player that killed them to allow checking properly
    killed_by = None
    lynched: bool = False
    saved_for_tonight = False
    # Needed to check win condition for mafia during day, before they kill
    can_kill_mafia_at_night = False
    # The amount that can be used per game
    limit = 0

    def __init__(self, discord_member: discord.Member):
        self.member = discord_member

    def __str__(self):
        return self.__class__.__name__

    def win_condition(self, game):
        return False

    def startup_channel_message(self, game):
        return f"Your role is {self}\n{self.description}."

    def set_channel(self, channel: discord.TextChannel):
        self.channel = channel

    def save(self):
        self.saved_for_tonight = True

    def kill(self, by):
        self.killed_by = by

    async def lock_channel(self):
        if self.channel:
            await self.channel.set_permissions(
                self.channel.guild.default_role,
                read_messages=False,
                send_messages=False,
            )

    async def unlock_channel(self):
        if self.channel:
            await self.channel.set_permissions(
                self.channel.guild.default_role, read_messages=False, send_messages=True
            )

    async def day_task(self, game):
        pass

    async def night_task(self, game):
        pass


class Citizen(Player):
    is_citizen = True
    description = "Your win condition is lynching all mafia, you do not have a special role during the night"

    def win_condition(self, game):
        return game.total_mafia == 0


class Doctor(Citizen):
    description = (
        "Your win condition is lynching all mafia, during the night you "
        "can choose one person to save. They cannot be killed during that night"
    )

    async def night_task(self, game):
        # Get everyone alive that isn't ourselves
        choices = "\n".join(
            [p.member.name for p in game.players if p != self and not p.dead]
        )
        await self.channel.send(
            "Please provide the name of one player you would like to save from being killed tonight. Choices are:"
            f"\n{choices}"
        )
        msg = await game.ctx.bot.wait_for(
            "message", check=game.ctx.bot.private_channel_check(game, self)
        )
        player = game.ctx.bot.get_mafia_player(msg.content)
        player.save()
        await self.channel.send("\N{THUMBS UP SIGN}")


class Sheriff(Citizen):
    description = (
        "Your win condition is lynching all mafia. During the night you can choose one person to shoot. "
        "If they are mafia, they will die... however if they are a citizen, you die instead"
    )
    can_kill_mafia_at_night = True

    async def night_task(self, game):
        # Get everyone alive that isn't ourselves
        choices = "\n".join(
            [p.member.name for p in game.players if p != self and not p.dead]
        )
        await self.channel.send(
            "If you would like to shoot someone tonight, provide just their name. Choices are:"
            f"\n{choices}"
        )

        msg = await game.ctx.bot.wait_for(
            "message", check=game.ctx.bot.private_channel_check(game, self)
        )
        player = game.ctx.bot.get_mafia_player(msg.content)

        # Handle what happens if their choice is right/wrong
        if player.is_citizen:
            self.kill(self)
        else:
            player.kill(self)
        await self.channel.send("\N{THUMBS UP SIGN}")


class PI(Citizen):
    description = (
        "Your win condition is lynching all Mafia. Every night you can provide "
        "2 people, and see if their alignment is the same"
    )

    async def night_task(self, game):
        # Get everyone alive
        choices = "\n".join([p.member.name for p in game.players if not p.dead])
        # F strings dumb, so get the output for f string here
        await self.channel.send(
            "Provide two people, in separate messages, to check if their alignment is the same. Choices are:"
            f"\n{choices}"
        )

        msg1 = await game.ctx.bot.wait_for(
            "message", check=game.ctx.bot.private_channel_check(game, self, True)
        )
        await msg1.add_reaction("\N{THUMBS UP SIGN}")
        msg2 = await game.ctx.bot.wait_for(
            "message", check=game.ctx.bot.private_channel_check(game, self, True)
        )
        player1 = game.ctx.bot.get_mafia_player(msg1.content)
        player2 = game.ctx.bot.get_mafia_player(msg2.content)

        # If we're here then the message happened twice, meaning we have two people
        if (
            (player1.is_citizen and player2.is_citizen)
            or (player1.is_mafia and player2.is_mafia)
            or (player1.is_independent and player2.is_independent)
        ):
            await self.channel.send(
                f"{player1.member.display_name} and {player2.member.display_name} have the same alignment"
            )
        else:
            await self.channel.send(
                f"{player1.member.display_name} and {player2.member.display_name} do not have the same alignment"
            )


class Mafia(Player):
    is_mafia = True
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


class Godfather(Mafia):
    pass


class Independent(Player):
    is_independent = True


class Jester(Independent):
    limit = 1

    description = "Your win condition is getting lynched or killed by the innocent"

    def win_condition(self, game):
        return self.lynched or (
            self.dead and self.killed_by and not self.killed_by.is_mafia
        )


# Sidelined for now, I don't get this role. Seems dumb if their target is mafia
class Executioner(Independent):
    limit = 1
    target = None
    description = "Your win condition is getting a certain player lynched"

    def startup_channel_message(self, game):
        self.target = random.choice(game.players)
        self.description += f". Your target is {self.target.member.display_name}"
        return super().startup_channel_message(game)

    def win_condition(self, game):
        return self.target.lynched


__special_mafia__ = ()
__special_citizens__ = (Doctor, Sheriff, PI)
__special_independents__ = (Jester,)

__special_roles__ = __special_mafia__ + __special_citizens__ + __special_independents__


def setup(bot):
    bot.__special_citizens__ = __special_citizens__
    bot.__special_mafia__ = __special_mafia__
    bot.__special_independents__ = __special_independents__
    bot.__special_roles__ = __special_roles__
    # Need the default mafia and citizen role too
    bot.mafia_role = Mafia
    bot.citizen_role = Citizen


def teardown(bot):
    del bot.__special_citizens__
    del bot.__special_mafia__
    del bot.__special_roles__
    del bot.__special_independents__
