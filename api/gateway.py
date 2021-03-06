"""
Provides RTM (Real Time Messaging) utilities.
The RtmHandler handles the connection and provides a method to act on events.
The RtmHandler also initiates a logger.
The Bot class implements this handler and adds help support.
"""
import json
import logging
import os
import threading
import time
from datetime import datetime

import websocket

from api import parser
from api.event import get_event, GatewayOP
from api.meta import CommandRegisterType
from api.utils import get_log_path, get_value, API_VERSION, activate_cache
from api.web import Gateway, Channel


class RtmHandler:
    """
    Handles the RealTimeMessaging protocol.
    Use ``run`` to start the connection (by default this is done in a seperate thread).
    Overwrite ``execute_event`` to handle incoming events.
    """

    def __init__(self, stream_log_level=logging.WARNING, file_log_level=logging.INFO):
        self.__socket = None
        self._rtm_start = None
        self.run_thread = None
        self.heartbeat_interval = 0
        self.heartbeat_last = datetime.min
        self.last_seq = None

        self.bots = []

        # Activate caching
        activate_cache()

        # setup logger
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.DEBUG)
        # Only add the handlers if they are not added yet. (prevents double handlers when re-instantiating)
        if not self.logger.hasHandlers():
            self.__setup_log_handlers(file_log_level, stream_log_level)

    def __setup_log_handlers(self, file_log_level, stream_log_level):
        """
        Setup the log handlers.
        This includes a file logger which logs to the config directory and a stream logger to log to console.
        """
        formatter = logging.Formatter(
            "%(threadName)s: %(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        # add file logger
        path = get_log_path(self.__class__.__name__)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fh = logging.FileHandler(path)
        fh.setLevel(file_log_level)
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)
        # add stream logger
        sh = logging.StreamHandler()
        sh.setLevel(stream_log_level)
        sh.setFormatter(formatter)
        self.logger.addHandler(sh)

    def __init_websocket(self):
        """
        Initiate the websocket to the rtm host and fill local data structures with slack data.
        If the websocket url could not be retrieved an exception will be thrown.
        """
        self.logger.debug("Initializing websocket")
        url = Gateway.get_url()
        ws = websocket.create_connection(
            "{}/?v={}&encoding=json".format(url, API_VERSION)
        )
        ws.sock.settimeout(3)

        hello = json.loads(ws.recv())
        if hello["op"] == 10:
            self.heartbeat_interval = hello["d"]["heartbeat_interval"]
        else:
            raise Exception("Did not receive hello? Got: {}".format(hello))

        # first try resuming
        self.__send_resume(ws)
        ready = json.loads(ws.recv())
        # if ready['op'] == 0 and ready['t'] == 'READY':
        #    self.logger.critical("Resuming..")
        #    get_event(ready)
        if ready["op"] == 9 and not ready["d"]:
            self.logger.critical("Failed to resume, starting up blank")
            # if resuming failed identify
            self.__send_identify(ws)

            ready = json.loads(ws.recv())
            if ready["op"] == 0 and ready["t"] == "READY":
                get_event(ready)  # Parse the ready event
            else:
                raise Exception("Did not receive ready? Got: {}".format(hello))
        else:
            self.logger.critical("Resuming..")
            self.logger.critical(ready)
        # else:
        #    self.logger.critical("Failed to resume.")
        #    self.logger.critical(ready)
        #    raise Exception("RIP")

        self.__socket = ws
        self.logger.debug("Initialized websocket")

    def __read_socket(self):
        """
        Read data from the websocket.
        """
        while True:
            try:
                event = json.loads(self.__socket.recv())
                self.logger.critical("OP:{} T:{}".format(event["op"], event["t"]))
                yield get_event(event)
            except Exception as e:
                if not isinstance(e, (websocket.WebSocketTimeoutException)):
                    self.logger.exception("Read socket exception")
                return

    def __send_resume(self, ws):
        ws.send(
            json.dumps(
                {
                    "op": 6,
                    "d": {
                        "token": get_value("main", "discord-token"),
                        "session_id": get_value("main", "last_session_id"),
                        "seq": get_value("main", "last_sequence_id"),
                    },
                }
            )
        )

    def __send_identify(self, ws):
        ws.send(
            json.dumps(
                {
                    "op": 2,
                    "d": {
                        "token": get_value("main", "discord-token"),
                        "properties": {
                            "$os": "linux",
                            "$browser": "plopkoek-bot",
                            "$device": "plopkoek-bot",
                        },
                        "compress": False,
                        "large_threshold": 50,
                        "shard": [0, 1],
                        "presence": {
                            "game": {"name": "Plopkoek Factory", "type": 0},
                            "status": "online",
                            "afk": False,
                        },
                    },
                }
            )
        )

    def run(self, threaded=True):
        """
        Start the connection and begin receiving events from the socket.
        If `threaded` is True, this method will be run in a seperate thread.
        """
        if threaded:
            self.run_thread = threading.Thread(
                target=self.run, args=(self, False), daemon=True
            )
            self.run_thread.start()
        else:
            self.logger.info("Started running")
            while True:
                try:
                    self.__run(self)
                except (
                    TimeoutError,
                    websocket.WebSocketConnectionClosedException,
                    websocket.WebSocketTimeoutException,
                    ConnectionResetError,
                    BrokenPipeError,
                ) as e:
                    self.logger.warning("ws_init timed out, restarting in 10")
                    self.logger.error(e)
                    time.sleep(10)
                except KeyboardInterrupt:
                    return

    def __run(self, parent):
        """
        Start the connection and begin receiving events from the socket.
        THIS METHOD SHOULD BE INVOKED BY ``run`` IF YOU WANT TO RUN THIS THREADED.
        The `threaded` param will only be used to restart the connection in case of time out or connection error.
        """
        self.__init_websocket()
        while True:
            try:
                # self.logger.critical(self.__socket)
                if (
                    datetime.now() - self.heartbeat_last
                ).total_seconds() >= self.heartbeat_interval // 1000:
                    self.__socket.send(json.dumps({"op": 1, "d": self.last_seq}))
                for event in self.__read_socket():
                    if event.is_dispatch:
                        self.last_seq = event.sequence
                        parent.execute_event(event)
                    elif event.of(GatewayOP.HEARTBEAT_ACK):
                        self.heartbeat_last = datetime.now()
            except (
                TimeoutError,
                websocket.WebSocketConnectionClosedException,
                websocket.WebSocketTimeoutException,
                ConnectionResetError,
                BrokenPipeError,
            ) as e:
                parent.logger.warning("Run timed out, restarting in 10 seconds.")
                parent.logger.error(e)
                time.sleep(10)
                return
            except ValueError as e:
                parent.logger.warning(e)

    def start_bot(self, bot: "Bot"):
        self.bots.append(bot)

    def execute_event(self, event):
        """
        The ``run`` method will call this method everytime a new slack event happens.
        The given event is a dictionary containing the data of the specific event.
        Overwrite this method if you want to act on an event.
        """
        self.logger.info("executing: " + event._t)
        for bot in self.bots:
            bot.execute_event(event)


class Bot(metaclass=CommandRegisterType):
    """
    An extension of the RtmHandler class that provides automatic help support based on help files.
    If no help files are found for the bot, a default help message will appear.
    """

    command_register = {}

    def __init__(
        self,
        botname,
        icon_url=None,
        stream_log_level=logging.WARNING,
        file_log_level=logging.INFO,
    ):
        self.botname = botname
        self.icon_url = icon_url

        # setup logger
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.DEBUG)
        # Only add the handlers if they are not added yet. (prevents double handlers when re-instantiating)
        if not self.logger.hasHandlers():
            self.__setup_log_handlers(file_log_level, stream_log_level)

        self.logger.info("Finished init")

    def __setup_log_handlers(self, file_log_level, stream_log_level):
        """
        Setup the log handlers.
        This includes a file logger which logs to the config directory and a stream logger to log to console.
        """
        formatter = logging.Formatter(
            "%(threadName)s: %(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        # add file logger
        path = get_log_path(self.__class__.__name__)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fh = logging.FileHandler(path)
        fh.setLevel(file_log_level)
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)
        # add stream logger
        sh = logging.StreamHandler()
        sh.setLevel(stream_log_level)
        sh.setFormatter(formatter)
        self.logger.addHandler(sh)

    def has_command(self, command):
        if self.__class__.__qualname__ in Bot.command_register:
            return command in Bot.command_register[self.__class__.__qualname__]
        return False

    def is_bot_command(self, event):
        """
        Returns true if the given string is a command for this specific bot.
        A botcommand looks like `!botname`.
        """
        try:
            text = event.content
        except AttributeError:
            return False
        if text is None:
            return False
        if text.lower().startswith(
            "!{} ".format(self.botname.lower())
        ) or text.lower() == "!{}".format(self.botname.lower()):
            return True
        return False

    def execute_event(self, event):
        """
        The ``run`` method will call this method everytime a new slack event happens.
        The given event is a dictionary containing the data of the specific event.
        Overwrite this method if you want to act on an event and be sure to call super() if you want to use the
        provided help support.
        """
        if event.of_t("MESSAGE_CREATE"):
            if self.is_bot_command(event):
                commands = []
                if len(event.content) > len(self.botname) + 1:
                    commands = event.content.split(" ")[1:]
                self.execute_bot_event(event, commands)

    def execute_bot_event(self, event, commands):
        """
        Is equal to the ``execute_event`` method except that the event is guaranteed to be a MessageEvent containing
        a botcommand.
        The command will contain the command string or will ne None if no further command was given.
        """

        def start_command(command):
            cmd, fmt = Bot.command_register[self.__class__.__qualname__][command]
            try:
                prefix = len(self.botname) + 2  # bot token + botname + space
                if command != "*":
                    prefix += len(command) + 1
                format_type = parser.apply_format(fmt, event.content[prefix:])
            except AttributeError as e:
                Channel.create_message(event.channel_id, str(e))
                # self.show_help(event.channel_id, command)
            else:
                cmd(self, event, format_type)

        if len(commands) == 0 or commands[0] == "help":
            if len(commands) <= 1:
                help_command = "__self__"
            else:
                help_command = commands[1]
            self.show_help(event.channel_id, help_command)
        elif self.has_command(commands[0]):
            start_command(commands[0])
        elif self.has_command("*"):
            start_command("*")

    def show_help(self, channel_id, command="__self__"):
        try:
            help_messages = get_value("help", self.botname)
        except KeyError:
            Channel.create_message(channel_id, "I don't provide help. :kappa:")
            return

        if command in help_messages:
            Channel.create_message(channel_id, help_messages[command])
            other_commands = "Commands with help:"
            for help_command in help_messages:
                if help_command == "__self__":
                    continue
                other_commands += ", {}".format(help_command)
            Channel.create_message(channel_id, other_commands)
        else:
            Channel.create_message(
                channel_id, "help for {} is not available.".format(command)
            )
