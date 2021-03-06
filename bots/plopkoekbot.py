"""
Provides a quotebot allowing users to add and traverse quotes.
"""

import logging
import string
from datetime import datetime
from operator import itemgetter

from tabulate import tabulate

from api import db
from api.decorators import command
from api.gateway import Bot
from api.utils import get_value, get_logger
from api.web import Channel, User

# from plots import plotly_chord

general_channel_id = get_value("main", "general_channel_id")
plopkoek_emote = "<:plop:236155120067411968>"
# plopkoek_emote = "<:lock:259731815651082251>"
bot_ids = ["243471854172504067", "243852628788903937"]


def init_db():
    """
    Initialize the plopkoek database with the PlopkoekTransfer table if no existing table is found.
    """
    conn = db.get_conn()
    # User table
    conn.execute(
        "CREATE TABLE IF NOT EXISTS PlopkoekTransfer("
        "user_from_id TEXT(64) NOT NULL,"
        "user_to_id TEXT(64) NOT NULL,"
        "channel_id TEXT(64) NOT NULL,"
        "message_id TEXT(64) NOT NULL,"
        "dt TIMESTAMP NOT NULL,"
        "FOREIGN KEY(user_from_id) REFERENCES User(user_id),"
        "FOREIGN KEY(user_to_id) REFERENCES User(user_id));"
    )
    conn.close()


def get_income(user_id, fmt):
    conn = db.get_conn()
    count = conn.execute(
        "SELECT COUNT(*) AS count FROM PlopkoekTransfer WHERE "
        "strftime(?, datetime(dt)) == strftime(?, 'now') AND "
        "user_to_id == ?;",
        (
            fmt,
            fmt,
            user_id,
        ),
    ).fetchone()
    conn.close()
    return count["count"]


def get_total_income(user_id):
    conn = db.get_conn()
    count = conn.execute(
        "SELECT COUNT(*) AS count FROM PlopkoekTransfer WHERE user_to_id == ?;",
        (user_id,),
    ).fetchone()["count"]
    conn.close()
    return count


def get_donations_left(user_id):
    conn = db.get_conn()
    count = conn.execute(
        "SELECT COUNT(*) As count FROM PlopkoekTransfer WHERE date(dt) == date('now') AND user_from_id==?;",
        (user_id,),
    ).fetchone()
    conn.close()
    return 5 - count["count"]


def remove_plopkoek(user_to_id, user_from_id, channel_id, message_id):
    conn = db.get_conn()
    count = conn.execute(
        "SELECT COUNT(*) AS count FROM PlopkoekTransfer "
        "WHERE user_to_id==? AND user_from_id==? AND channel_id=? AND message_id=?",
        (user_to_id, user_from_id, channel_id, message_id),
    ).fetchone()["count"]
    if count > 0:
        conn.execute(
            "DELETE FROM PlopkoekTransfer "
            "WHERE user_to_id==? AND user_from_id==? AND channel_id=? AND message_id=?",
            (user_to_id, user_from_id, channel_id, message_id),
        )
        conn.commit()

        try:
            dm = User.create_dm(recipient_id=user_to_id)
            content = "<@{}> heeft een plopkoek afgepakt :O  Je hebt er nu nog {} deze maand over.".format(
                user_from_id, get_income(user_to_id, "%Y-%m")
            )
            Channel.create_message(channel_id=dm.json()["id"], content=content)
        except KeyError:
            self.logger.critical("Could not send message to receiver")

        try:
            dm = User.create_dm(recipient_id=user_from_id)
            content = (
                "Je hebt een plopkoek die je aan <@{}> hebt gegeven teruggenomen. (Gij se evil bastard!) "
                "Je kan er vandaag nog {} uitgeven.".format(
                    user_to_id, get_donations_left(user_from_id)
                )
            )
            Channel.create_message(channel_id=dm.json()["id"], content=content)
        except KeyError:
            self.logger.critical("Could not send message to sender")
    conn.close()


def remove_plopkoek_reaction(event):
    if not event.emoji["id"]:
        return
    if event.emoji["id"] in plopkoek_emote:
        message = Channel.get_message(event.channel_id, event.message_id)
        receiver = message["author"]["id"]
        donator = event.user_id

        if receiver in bot_ids:
            username = message["author"]["username"]
            quote_content = message["content"]
            if username == "plopkoek" and " -" in quote_content:
                quote_content = "-".join(quote_content.split(" -")[:-1])
            for quotee, quotes in get_value("quotebot", "quotes").items():
                for quote in quotes:
                    if (
                        quote["quote"] == quote_content
                        and quotee.startswith("<@")
                        and quotee.endswith(">")
                    ):
                        receiver = quotee.strip("<@!>")
                        print("Removing quote")

        remove_plopkoek(receiver, donator, event.channel_id, event.message_id)


def can_donate(donator, receiver):
    if donator == receiver:
        return False

    return get_donations_left(donator) > 0


def get_month_ranking(month=None, year=None):
    if not month:
        month = str(datetime.utcnow().month)
    if not year:
        year = str(datetime.utcnow().year)
    if len(month) == 1:
        month = "0" + month

    conn = db.get_conn()
    received_data = conn.execute(
        "SELECT user_to_id, COUNT(user_to_id) AS received "
        "FROM PlopkoekTransfer "
        "WHERE strftime('%m', datetime(dt)) == ? AND "
        "strftime('%Y', datetime(dt)) == ? "
        "GROUP BY user_to_id",
        (month, year),
    ).fetchall()

    donated_data = conn.execute(
        "SELECT user_from_id, COUNT(user_from_id) AS donated "
        "FROM PlopkoekTransfer "
        "WHERE strftime('%m', datetime(dt)) == ? AND "
        "strftime('%Y', datetime(dt)) == ? "
        "GROUP BY user_from_id",
        (month, year),
    ).fetchall()
    conn.close()
    return __process_ranking_data(received_data, donated_data)


def get_alltime_ranking():
    conn = db.get_conn()
    received_data = conn.execute(
        "SELECT user_to_id, COUNT(user_to_id) AS received "
        "FROM PlopkoekTransfer "
        "GROUP BY user_to_id"
    ).fetchall()

    donated_data = conn.execute(
        "SELECT user_from_id, COUNT(user_from_id) AS donated "
        "FROM PlopkoekTransfer "
        "GROUP BY user_from_id"
    ).fetchall()
    conn.close()
    return __process_ranking_data(received_data, donated_data)


def __process_ranking_data(received_data, donated_data):
    dict_data = {}
    for row in received_data:
        uid = row["user_to_id"]
        try:
            username = User.get_user(uid)["username"]
        except KeyError:
            username = uid
        dict_data[uid] = {"received": row["received"], "user": username, "donated": 0}
    for row in donated_data:
        uid = row["user_from_id"]
        if uid not in dict_data:
            try:
                username = User.get_user(uid)["username"]
            except KeyError:
                username = uid
            dict_data[uid] = {"user": username, "received": 0}
        dict_data[uid]["donated"] = row["donated"]
    list_data = []
    for dd in sorted(
        list(dict_data.values()), key=itemgetter("received"), reverse=True
    ):
        list_data.append([dd["received"], dd["donated"], dd["user"]])
    return list_data


def filter_ascii_only(data):
    return [
        [d[0], d[1], "".join([c for c in d[2] if c in string.printable])] for d in data
    ]


class PlopkoekBot(Bot):
    def __init__(self, stream_log_level=logging.DEBUG, file_log_level=logging.INFO):
        super().__init__(
            "plopkoekbot",
            stream_log_level=stream_log_level,
            file_log_level=file_log_level,
        )
        init_db()

    @command("total", fmt="[user_id]")
    def show_total(self, event, args):
        user_id = event.author["id"]
        if args.user_id:
            user_id = args.user_id.strip("<@!>")
        message = "<@!{}> has so far earned {} plopkoeks this month.".format(
            user_id, get_income(user_id, "%Y-%m")
        )
        Channel.create_message(event.channel_id, message)

    @command("grandtotal", fmt="[user_id]")
    def show_grandtotal(self, event, args):
        user_id = event.author["id"]
        if args.user_id:
            user_id = args.user_id.strip("<@!>")
        message = "<@!{}> has so far earned {} plopkoeks in total!.".format(
            user_id, get_total_income(user_id)
        )
        Channel.create_message(event.channel_id, message)

    @command("leaders", fmt="[month] [year]")
    def show_leaders(self, event, args):
        data = get_month_ranking(args.month, args.year)
        if not data:
            Channel.create_message(event.channel_id, "No data for the given period :(")
        while data:
            table_data = filter_ascii_only(data[:10])
            message = tabulate(
                table_data,
                headers=["received", "donated", "user"],
                tablefmt="fancy_grid",
            )
            Channel.create_message(event.channel_id, f"```{message}```")
            data = data[10:]

    @command("grandleaders")
    def show_grandleaders(self, event, args):
        data = get_alltime_ranking()
        if not data:
            Channel.create_message(event.channel_id, "No data for the given period :(")
        while data:
            table_data = filter_ascii_only(data[:10])
            message = tabulate(
                table_data,
                headers=["received", "donated", "user"],
                tablefmt="fancy_grid",
            )
            Channel.create_message(event.channel_id, f"```{message}```")
            data = data[10:]

    def donate_plopkoek(self, event):
        if (
            plopkoek_emote in event.content
            and len(event.content.strip().split(" ")) == 2
        ):
            user = event.content.replace(plopkoek_emote, "").strip()
            if user.startswith("<@") and user.endswith(">"):
                self.add_plopkoek(
                    user.strip("<@!>"),
                    user_from_id=event.author["id"],
                    channel_id=event.channel_id,
                    message_id=event.id,
                )

    def donate_plopkoek_reaction(self, event):
        if not event.emoji["id"]:
            return
        if event.emoji["id"] in plopkoek_emote:
            message = Channel.get_message(event.channel_id, event.message_id)
            try:
                receiver = message["author"]["id"]
            except KeyError:
                get_logger("PlopkoekBot").exception(
                    "Could not parse message author: {}".format(message)
                )
                Channel.create_message(
                    event.channel_id,
                    "Something went wrong giving that plopkoek :( spam darragh to fix it",
                )
                return
            donator = event.user_id

            if receiver in bot_ids:
                username = message["author"]["username"]
                quote_content = message["content"]
                if username == "plopkoek" and " -" in quote_content:
                    quote_content = "-".join(quote_content.split(" -")[:-1])
                for quotee, quotes in get_value("quotebot", "quotes").items():
                    for quote in quotes:
                        if (
                            quote["quote"] == quote_content
                            and quotee.startswith("<@")
                            and quotee.endswith(">")
                        ):
                            receiver = quotee.strip("<@!>")

            self.add_plopkoek(receiver, donator, event.channel_id, event.message_id)

    def add_plopkoek(self, user_to_id, user_from_id, channel_id, message_id):
        if not can_donate(user_from_id, user_to_id):
            return

        now = datetime.now()

        conn = db.get_conn()
        conn.execute(
            "INSERT INTO PlopkoekTransfer(user_from_id, user_to_id, channel_id, message_id, dt) VALUES (?, ?, ?, ?, ?)",
            (user_from_id, user_to_id, channel_id, message_id, now),
        )
        conn.commit()
        conn.close()

        try:
            message = Channel.get_message(channel_id, message_id)
            user = User.get_user(user_to_id)
            embed = {
                "description": message["content"],
                "author": {
                    "name": user["username"],
                    "icon_url": User.get_avatar_url(user),
                },
            }
        except Exception as e:
            self.logger.exception(e)
            embed = {}

        try:
            dm = User.create_dm(recipient_id=user_to_id)
            content = "Je hebt een plopkoek van <@{}> gekregen!  Je hebt er nu {} deze maand verzameld. Goe bezig!".format(
                user_from_id, get_income(user_to_id, "%Y-%m")
            )
            Channel.create_message(
                channel_id=dm.json()["id"], content=content, embed=embed
            )
        except KeyError:
            self.logger.critical("Could not send message to plopkoek receiver")

        try:
            dm = User.create_dm(recipient_id=user_from_id)
            left = get_donations_left(user_from_id)
            if left == 0:
                content = "Je hebt een plopkoek aan <@{}> gegeven.  Da was uwe laatste plopkoek van vandaag, geefde gij ook zo gemakkelijk geld uit?".format(
                    user_to_id
                )
            else:
                content = "Je hebt een plopkoek aan <@{}> gegeven.  Je kan er vandaag nog {} uitgeven. Spenden die handel!".format(
                    user_to_id, left
                )
            Channel.create_message(
                channel_id=dm.json()["id"], content=content, embed=embed
            )
        except KeyError:
            self.logger.critical("Could not send message to plopkoek donator")

    # plotly_chord.p()

    def execute_event(self, event):
        super().execute_event(event)
        if event.of_t("MESSAGE_CREATE"):
            self.donate_plopkoek(event)
        elif event.of_t("MESSAGE_REACTION_ADD"):
            self.donate_plopkoek_reaction(event)
        elif event.of_t("MESSAGE_REACTION_REMOVE"):
            remove_plopkoek_reaction(event)
        # self.logger.critical(event._t)
