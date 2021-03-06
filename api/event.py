import sys

from enum import IntEnum

import logging

from api.db import (
    update_user,
    update_guild,
    update_channel,
    remove_guild,
    remove_channel,
)
from api.utils import get_logger, set_value

module = sys.modules[__name__]


def __to_classname(event_name: str):
    return "".join(part.capitalize() for part in event_name.split("_"))


def get_event(json_data) -> "Event":
    if json_data["op"] == 0 and hasattr(module, __to_classname(json_data["t"])):
        return getattr(module, __to_classname(json_data["t"]))(json_data)
    return Event(json_data)


class GatewayOP(IntEnum):
    DISPATCH = 0
    HEARTBEAT = 1
    IDENTIFY = 2
    STATUS_UPDATE = 3
    VOICE_STATE_UPDATE = 4
    VOICE_SERVER_PING = 5
    RESUME = 6
    RECONNECT = 7
    REQUEST_GUILD_MEMBERS = 8
    INVALID_SESSION = 9
    HELLO = 10
    HEARTBEAT_ACK = 11


class Event:
    def __init__(self, data):
        self._s = data["s"]
        self._t = data["t"]
        self._op = data["op"]
        self.raw_data = data

        try:
            for var in data["d"]:
                setattr(self, var, data["d"][var])
        except:
            pass

        self.is_dispatch = self.of(GatewayOP.DISPATCH)

        set_value("main", "last_sequence_id", data["s"] if data["s"] is not None else 0)

    @property
    def sequence(self):
        return self._s

    def of(self, op_code):
        return self._op == op_code

    def of_t(self, type_):
        return self._t == type_

    def __repr__(self):
        return "Event({})".format(self._t)


class Ready(Event):
    def __init__(self, data):
        super().__init__(data)
        update_user(self.user)
        for channel in self.private_channels:
            update_channel(channel)
        # unavailable guilds aren't interesting, just wait for the GuildCreate events
        set_value("main", "last_session_id", self.session_id)


class Resumed(Event):
    pass


class ChannelCreate(Event):
    def __init__(self, data):
        super().__init__(data)
        # TODO FIX
        # if self.is_private and "id" in self.recipient:
        #    update_user(self.recipient)
        update_channel(data["d"])


class ChannelUpdate(Event):
    def __init__(self, data):
        super().__init__(data)
        update_channel(data["d"])


class ChannelDelete(Event):
    def __init__(self, data):
        super().__init__(data)
        if self.is_private and "id" in self.recipient:
            update_user(self.recipient)
        remove_channel(self.id)


class GuildCreate(Event):
    def __init__(self, data):
        super().__init__(data)
        update_guild(data["d"])


class GuildUpdate(Event):
    def __init__(self, data):
        super().__init__(data)
        update_guild(data["d"])


class GuildDelete(Event):
    def __init__(self, data):
        super().__init__(data)
        remove_guild(data["d"])


class MessageCreate(Event):
    def __init__(self, data):
        super().__init__(data)
        if "webhook_id" not in data["d"]:
            update_user(self.author)
