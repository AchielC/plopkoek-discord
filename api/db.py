import sqlite3

from api.exceptions import NotCachedException


def get_conn():
    conn = sqlite3.connect("plopkoek.db")
    conn.row_factory = sqlite3.Row
    return conn


def create_basic_discord_cache():
    conn = get_conn()
    # User table
    conn.execute("CREATE TABLE IF NOT EXISTS User(user_id TEXT(64) PRIMARY KEY UNIQUE NOT NULL, name TEXT NOT NULL, avatar TEXT);")
    # Guild table
    conn.execute("CREATE TABLE IF NOT EXISTS Guild(guild_id TEXT(64) PRIMARY KEY UNIQUE NOT NULL, name TEXT NOT NULL);")
    # Channel table
    conn.execute(
        "CREATE TABLE IF NOT EXISTS Channel("
        "channel_id TEXT(64) PRIMARY KEY UNIQUE NOT NULL,"
        "type TEXT NOT NULL,"
        "is_private BOOLEAN NOT NULL,"
        "name TEXT,"
        "guild_id TEXT(64),"
        "user_id TEXT(64),"
        "FOREIGN KEY(guild_id) REFERENCES Guild(guild_id),"
        "FOREIGN KEY(user_id) REFERENCES User(user_id)"
        ");")
    # GuildMember table
    conn.execute(
        "CREATE TABLE IF NOT EXISTS GuildMember("
        "user_id TEXT(64) NOT NULL,"
        "guild_id TEXT(64) NOT NULL,"
        "nick TEXT,"
        "FOREIGN KEY(user_id) REFERENCES User(user_id),"
        "FOREIGN KEY(guild_id) REFERENCES Guild(guild_id)"
        ");"
    )
    conn.close()


def update_user(data):
    try:
        snowflake = data['id']
        name = data['username']
        avatar = data['avatar']
    except Exception as e:
        print(data)
        print(e)
        return

    conn = get_conn()
    try:
        user_data = get_user(snowflake)
    except NotCachedException:
        conn.execute("INSERT INTO User (user_id, name, avatar) VALUES (?, ?, ?)", (snowflake, name, avatar))
        conn.commit()
    else:
        # noinspection PyTypeChecker
        if user_data['username'] != name or user_data['avatar'] != avatar:
            conn.execute("UPDATE User SET name=?, avatar=? WHERE user_id=?", (name, avatar, snowflake))
            conn.commit()

    conn.close()


def get_user(user_id):
    conn = get_conn()
    user_data = conn.execute("SELECT user_id As id, name As username, avatar FROM User WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if not user_data:
        raise NotCachedException()
    return user_data


def update_member(data):
    guild_id = data['guild_id']
    user_id = data['user']['id']
    nick = data.get('nick', None)

    conn = get_conn()
    try:
        member_data = get_member(guild_id, user_id)
    except NotCachedException:
        conn.execute("INSERT INTO GuildMember (guild_id, user_id, nick) VALUES (?, ?, ?)", (guild_id, user_id, nick))
        conn.commit()
    else:
        # noinspection PyTypeChecker
        if member_data['nick'] != nick:
            conn.execute("UPDATE GuildMember SET nick=? WHERE guild_id=? AND user_id=?", (nick, guild_id, user_id))
            conn.commit()

    conn.close()


def get_member(guild_id, user_id):
    conn = get_conn()
    member_data = conn.execute("SELECT guild_id, user_id, nick FROM GuildMember WHERE guild_id=? AND user_id=?",
                               (guild_id, user_id,)).fetchone()
    conn.close()
    if not member_data:
        raise NotCachedException()
    return member_data


def update_guild(data):
    snowflake = data['id']
    name = data['name']
    conn = get_conn()
    try:
        guild_data = get_guild(snowflake)
    except NotCachedException:
        conn.execute("INSERT INTO Guild (guild_id, name) VALUES (?, ?)", (snowflake, name))
        conn.commit()
    else:
        # noinspection PyTypeChecker
        if guild_data['name'] != name:
            conn.execute("UPDATE Guild SET name=? WHERE guild_id=?", (name, snowflake))
            conn.commit()
    conn.close()

    if 'channels' in data:
        for channel in data['channels']:
            # This is missing during the GuildCreate event..
            if 'guild_id' not in channel:
                channel['guild_id'] = snowflake
            update_channel(channel)

    if 'members' in data:
        for member in data['members']:
            if 'guild_id' not in member:
                member['guild_id'] = snowflake
            update_member(member)


def get_guild(guild_id):
    conn = get_conn()
    guild_data = conn.execute("SELECT guild_id, name FROM Guild WHERE guild_id=?", (guild_id,)).fetchone()
    conn.close()
    if not guild_data:
        raise NotCachedException()
    return guild_data


def remove_guild(data):
    print("Guild remove not yet implemented")


def update_channel(data):
    snowflake = data['id']
    is_private = False  # data['is_private']
    type_ = data['type']
    guild_id = None
    user_id = None
    name = None
    if 'recipients' in data:
        for rec in data['recipients']:
            update_user(rec)
            user_id = rec['id']
    else:
        guild_id = data.get('guild_id', '')
        name = data['name']

    conn = get_conn()
    try:
        channel_data = get_channel(snowflake)
    except NotCachedException:
        conn.execute("INSERT INTO Channel (channel_id, name, is_private, type, guild_id, user_id) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (snowflake, name, is_private, type_, guild_id,  user_id))
        conn.commit()
    else:
        # noinspection PyTypeChecker
        if channel_data['name'] != name:
            conn.execute("UPDATE Channel SET name=? WHERE channel_id=?", (name, snowflake))
            conn.commit()
    conn.close()


def get_channel(channel_id):
    conn = get_conn()
    channel_data = conn.execute("SELECT channel_id, name FROM Channel WHERE channel_id=?", (channel_id,)).fetchone()
    conn.close()
    if not channel_data:
        raise NotCachedException()
    return channel_data


def remove_channel(data):
    print("Channel remove not yet implemented")


# noinspection PyTypeChecker
def get_userid(username, channel_id):
    conn = get_conn()
    guild_id = conn.execute("SELECT guild_id FROM Channel WHERE channel_id=?", (channel_id,)).fetchone()
    if not guild_id:
        return username
    # first get nickname
    user_id = conn.execute("SELECT user_id FROM GuildMember WHERE nick=? AND guild_id=?",
                           (username, guild_id['guild_id'])).fetchone()
    if user_id:
        return user_id['user_id']

    # No nickname set, thus look for username
    result = conn.execute("SELECT user_id FROM User WHERE name=? AND user_id IN"
                          "(SELECT user_id FROM GuildMember WHERE guild_id=?)",
                          (username, guild_id['guild_id'])).fetchone()
    conn.close()
    if not result:
        return username
    return result['user_id']
