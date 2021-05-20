from __future__ import annotations

import typing
from concurrent.futures import ThreadPoolExecutor
import io

import discord
from PIL import Image, ImageDraw, ImageFont

if typing.TYPE_CHECKING:
    from .game import MafiaGame
    from . import players

alpha = None
pool = ThreadPoolExecutor(5, thread_name_prefix="img-worker-")
font_28days_title = ImageFont.truetype("./resources/28 Days Later.ttf", size=256)
font_28days_subtitle = ImageFont.truetype("./resources/28 Days Later.ttf", size=64)
font_28days = ImageFont.truetype("./resources/28 Days Later.ttf", size=64)
font_vermillion = ImageFont.truetype("./resources/Vermillion.ttf", size=34)
death_marker = Image.open("./resources/death-marker.png", formats=("png",)).resize((96, 96))

def add_corners(im, rad):
    if im.size != (128, 128):
        im = im.resize((128, 128))

    global alpha
    if not alpha: # cache the alpha layer
        circle = Image.new('L', (rad * 2, rad * 2), 0)
        draw = ImageDraw.Draw(circle)
        draw.ellipse((0, 0, rad * 2, rad * 2), fill=255)
        alpha = Image.new('L', im.size, 255)
        alpha.paste(circle.crop((0, 0, rad, rad)), (0, 0))
        alpha.paste(circle.crop((0, rad, rad, rad * 2)), (0, im.size[0] - rad))
        alpha.paste(circle.crop((rad, 0, rad * 2, rad)), (128 - rad, 0))
        alpha.paste(circle.crop((rad, rad, rad * 2, rad * 2)), (im.size[0] - rad, im.size[0] - rad))

    im.putalpha(alpha)
    return im.resize((96,96))

async def round_avatar(member: discord.Member, rad=64) -> Image:
    pfp = io.BytesIO()
    await member.avatar_url_as(format="png", size=128).save(pfp)
    pfp.seek(0)
    return add_corners(Image.open(pfp, formats=("png",)), rad)

async def create_day_image(game: MafiaGame, deaths: typing.List[players.Player]) -> io.BytesIO:
    return await game.ctx.bot.loop.run_in_executor(pool, _sync_make_day_image, game, deaths)

async def create_night_image(game: MafiaGame) -> io.BytesIO:
    pass

def _sync_make_night_image(game: MafiaGame) -> io.BytesIO:
    base: Image.Image = Image.open("./resources/background-night.png", formats=("png",))
    base = base.resize((1920, 1080))

def _sync_make_day_image(game: MafiaGame, deaths: typing.List[players.Player]) -> io.BytesIO:
    base: Image.Image = Image.open("./resources/background-day.png", formats=("png",))
    base = base.resize((1920, 1080)).convert("RGBA")
    raster = ImageDraw.Draw(base)
    alive = list(filter(lambda player: not player.dead, game.players))
    dead = list(filter(lambda player: player.dead and player not in deaths, game.players))
    _w, _h = raster.textsize(f"Day {game._day}", font=font_28days_title)
    raster.text(((1920-_w)/2, 30), f"Day {game._day}", font=font_28days_title, fill="black") # noqa
    raster.text((30, 260), f"Alive Players", font=font_28days_subtitle,) # noqa
    spe = 105
    col_width = 400
    row = 0
    col = 0

    def paste_avatar(p, fill, do_x, show_role):
        nonlocal col, row
        avy = p.avatar
        x = (30 + (col * col_width), int(330 + (spe * row)), 30 + avy.size[0] + (col * col_width),
             int(330 + (spe * row) + avy.size[1]))
        print(x, avy.mode, base.mode, base.getbbox(), avy.getbbox())
        base.paste(avy, x, mask=avy)
        if do_x:
            base.paste(death_marker, x, mask=death_marker)
        nick = f"{f'{p.member.nick} ' if p.member.nick else ''}{f'({p.member.name})' if p.member.nick else p.member.name}"
        if len(nick) >= 17:
            nick = nick[:17] + "..."
        if show_role:
            nick += f"\n\t{p.role.__class__.__name__}"
            t = (x[2] + 20, int(330 + (spe * row)))
        else:
            _, _h = raster.textsize(nick, font=font_vermillion)
            t = (x[2] + 20, int(330 + (spe * row) + (_h / 2)))

        raster.text(t, nick, font=font_vermillion, fill=fill)
        row += 1
        if row >= 7:
            row = 0
            col += 1

    if deaths:
        for p in deaths:
            if col >= 1 and 3 > row > 0:
                fill = "black"
            else:
                fill = "white"
            paste_avatar(p, fill, True, True)

    for p in alive:
        if col >= 1 and 3 > row > 0:
            fill = "black"
        else:
            fill = "white"
        paste_avatar(p, fill, False, False)

    if dead:
        if row:
            col += 1
            row = 0

        raster.text((30+(col*col_width), 260), f"Dead Players", font=font_28days_subtitle, fill="black")  # noqa
        for p in dead:
            if (col >= 1 and row == 2) or (col == 3 and (row == 0 or row == 2)):
                fill = "black"
            else:
                fill = "white"
            paste_avatar(p, fill, True, True)

    buf = io.BytesIO()
    base.save(buf, format="png")
    buf.seek(0)
    base.close()
    return buf


def setup(bot):
    bot.create_day_image = create_day_image
    bot.create_night_image = create_night_image

def teardown(bot):
    del bot.create_day_image
    del bot.create_night_image
