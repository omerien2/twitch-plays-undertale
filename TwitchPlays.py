#!/usr/bin/env python

"""Let a twitch.tv chat room control a pc! Featuring permissions system, discord integration, and a whole lot more.

Files:
    config/apiconfig_static_backup.json -- automatically managed local backup of dev and mod lists from the API
    config/config.example.toml -- example config file with no keys, included in the git repo for reference
    config/config.toml -- real working instance of the config
    logs/chat.log -- every message sent in the connected Twitch chat
    logs/system.log -- mirror of the console output handled by the logging package
    executing.txt -- contains info about the currently executing command, for OBS
"""

# Due to my strong personal convictions,
# I wish to stress that this code in no
# way endorses a belief in the occult.

# PSL Packages;
import os  # file manager and cmd command handler
import sys  # for exiting with best practices and getting exception info for log
import asyncio
import random
import argparse
import typing
import logging as log  # better print()
from pathlib import Path  # for best practices filepath handling

# PIP Packages;
import pyautogui  # some mod only commands
import aiohttp  # api and discord webhooks
import toml  # configuration
import twitchio.ext.commands.bot

# Local Packages;
import cmpc  # Pretty much all of the custom shit we need.
import config.new_oauth_key as keygen

__version__ = '3.34.0'

# Folders we use
CONFIG_FOLDER = Path('config/')
LOGS_FOLDER = Path('logs/')

pyautogui.FAILSAFE = False

BRANCH_NAME, BRANCH_NAME_ASSUMED = cmpc.get_git_repo_info()
COPYRIGHT_NOTICE = f"""
------------------------------------------
           TWITCH PLAYS
           {BRANCH_NAME.upper()} BRANCH
           https://cmpc.live
           © 2020-2021 controlmypc
           by CMPC Developers
------------------------------------------
"""


class TwitchPlays(twitchio.ext.commands.bot.Bot):
    """Implements functionality with permissions and some startup stuff."""

    def __init__(
            self, config: dict,
            offline_mode: bool = False,
            modtools_on: bool = True, modtools_timeout_on: bool = False, modtools_ban_on: bool = False,
            mod_rota_on: bool = True
    ):
        """Get set up, then call super().__init__.

        Args:
            same as cmpc.TwitchConnection.__init__ but without prefix
        Checks that username and auth are present. Deletes chat log if it exists. Instantiates a command processor
        and permissions handler.
        """
        self.config = config
        if not self.config['twitch']['oauth_token'].startswith('oauth:'):
            self.config['twitch']['oauth_token'] = 'oauth:' + self.config['twitch']['oauth_token']

        self.modtools_on = modtools_on
        self.modtools_timeout_on = modtools_timeout_on
        self.modtools_ban_on = modtools_ban_on
        self.mod_rota_on = mod_rota_on
        if self.mod_rota_on:
            self.mod_rota = cmpc.ModRota(self)

        self.script_id = random.randint(0, 1000000)
        # used in the ../script suspend command
        self.allow_commands_from_users = True

        # Check essential constants are not empty.
        if not config['twitch']['username'] or not config['twitch']['oauth_token']:
            log.fatal('[TWITCH] No channel or oauth token was provided.')
            cmpc.send_webhook(config['discord']['systemlog'], 'FAILED TO START - No Oauth or username was provided.')
            sys.exit(1)
        if not config['api']['panelapikey']:
            log.warning('[CHATBOT] No panel api key was provided, chatbot command has been disabled.')
        if config['options']['LOGGER_LEVEL'].lower() == "debug" and config['options']['DEPLOY'] == "Production":
            log.warning('[LOG] You are enabling debug mode in a production env, '
                        'this will log discord webhook urls to system.log and such. you have been warned.')

        # Remove temp chat log if it exists.
        if os.path.exists(LOGS_FOLDER/'chat.log'):
            os.remove(LOGS_FOLDER/'chat.log')

        self.api_requests = cmpc.CmpcApi(config)
        self.user_permissions_handler = self.permissions_handler_from_api()

        self.processor = cmpc.CommandProcessor(self, 'executing.txt')

        if offline_mode:
            self.script_tester = cmpc.ScriptTester(TwitchPlays.event_message, self)
        else:
            super().__init__(
                prefix='!', initial_channels=[config['twitch']['channel_to_join']],
                nick=self.config['twitch']['username'], irc_token=self.config['twitch']['oauth_token'],
                client_id=self.config['twitch']['api_client_id'],
                api_token=cmpc.removeprefix(config['twitch']['oauth_token'], 'oauth:')
            )
            if modtools_on:
                self.modtools = cmpc.ModTools(self)
            if self.mod_rota_on:
                self.loop.create_task(self.mod_rota.run())
                self.loop.create_task(self.mod_rota.run_mod_presence_checks())
        log.debug('Finished intialising TwitchPlays object.')

    # TwitchPlays methods - TwitchConnection overrides below
    @staticmethod
    def load_user_permissions(
            dev_list: typing.List[str], mod_list: typing.List[str]
    ) -> typing.Dict[str, cmpc.Permissions]:
        """Generate a dict of user permissions based on lists of devs and mods.

        Args:
            dev_list, mod_list -- self explanatory
        Returns:
            user_permissions -- the aforementioned dict
        """
        user_permissions = {}
        for dev in dev_list:
            perms = user_permissions.get(dev, cmpc.Permissions())
            perms.developer = True
            user_permissions[dev] = perms
        for mod in mod_list:
            perms = user_permissions.get(mod, cmpc.Permissions())
            perms.moderator = True
            user_permissions[mod] = perms
        user_permissions.setdefault('cmpcscript', cmpc.Permissions()).script = True

        return user_permissions

    def permissions_handler_from_api(
            self, url: str = None, static_backup_path: Path = CONFIG_FOLDER / 'apiconfig.json'
    ) -> typing.Dict[str, cmpc.Permissions]:
        """Get the dev and mod lists from the given url, and return a user permissions object.

        Args:
            url -- url to get lists from, defaults to self.config['api']['apiconfig']
            static_backup_path -- path to save the local backup json file
        Returns:
            A dict of user permissions generated by self.load_user_permissions
        """
        if url is None:
            url = self.config['api']['apiconfig']

        apiconfig_json = self.api_requests.get_json_from_api(url, static_backup_path)
        # Init and return user permissions handler from dev and mod lists
        return self.load_user_permissions(
            dev_list=apiconfig_json['devlist'],
            mod_list=apiconfig_json['modlist']
        )

    async def suspend(self, duration: typing.Union[str, float], twitch_message: cmpc.TwitchMessage):
        """Do not allow commands from regular users for the duration.

        Used in ../script suspend and !defcon.
        """
        try:
            duration = float(duration)
        except ValueError:
            log.error(f'Could not suspend for duration: {twitch_message.content}, due to non-numeric arg')
            return
        else:
            try:
                if duration == 1.0:
                    log_message = '[Suspend script for 1 second]'
                else:
                    log_message = f'[Suspend script for {int(duration)} seconds]'
                self.processor.log_to_obs(None, none_log_msg=f'{log_message} ({twitch_message.username})')

                self.allow_commands_from_users = False
                await asyncio.sleep(duration)
                # todo: handle a situation when the script is unsuspended and resuspended in this time
                self.allow_commands_from_users = True
            except ValueError:
                log.error(f'Could not suspend for duration: {twitch_message.content}, due to negative arg')
            except OverflowError:
                log.error(f'Could not suspend for duration: {twitch_message.content}, '
                          'due to too large arg')

    # TwitchConnection overrides
    async def event_ready(self):
        """Override TwitchConnection.event_ready - log and send discord webhook for startup message if applicable.

        Also start the mod rota running on the bot's asyncio loop.
        """
        log.info("[TWITCH] Auth accepted and we are connected to twitch")
        await self.processor.log_to_obs(None)
        # Send starting up message with webhook if in CONFIG.
        if self.config['options']['START_MSG']:
            cmpc.send_webhook(self.config['discord']['systemlog'],
                              'Script - **Online**\n'
                              f"[***Stream Link***](<https://twitch.tv/{self.config['channel_to_join']}>)\n"
                              f"**Environment -** {self.config['options']['DEPLOY']}",
                              )

        log.info('Finished initialising, ready!')

    # noinspection PyUnboundLocalVariable
    async def event_message(self, message: twitchio.Message):
        """Override TwitchPlays.event_message - process a message.

        Args:
            message -- a twitchio.Message object
        Returns nothing
        Will run message through the command processor, returning if a command is found.
        Additionally looks for and executes some permission based commands, this might be refactored in the future.
        Also responsible for logging to obs, log files and discord webhooks if applicable.
        """
        twitch_message = cmpc.TwitchMessage(message.content, message.author.name)

        # Command processing is very scary business - let's wrap the whole thing in a try/catch
        # todo: remove try-except here?
        try:
            # Log the chat if that's something we want to do
            if self.config['options']['LOG_ALL']:
                log.info(f'CHAT LOG: {twitch_message.get_log_string()}')
            if self.config['options']['LOG_PPR']:
                with open(LOGS_FOLDER/'chat.log', 'a', encoding='utf-8') as f:
                    f.write(f'{twitch_message.get_log_string()}\n')

            # Ignore bot messages
            if twitch_message.username in ['twitchcontrolsmypc', 'fucku', 'streamelements']:
                log.info(f'Ignored message from {twitch_message.username} due to exemption.')
                return
            # Ignore echo messages
            if not message.author.id:
                return

            user_permissions = self.user_permissions_handler.get(twitch_message.username, cmpc.Permissions())

            if not self.allow_commands_from_users and not (user_permissions.moderator or user_permissions.developer):
                return

            if self.modtools_on:
                # Check if the user is allowed to run commands
                # Don't bother checking for moderators or developers
                if not (user_permissions.moderator or user_permissions.developer):
                    if not await self.modtools.check_user_allowed(message.author.id):
                        await self.modtools.notify_ignored_user(message)
                        log.info(f'Ignored message from {twitch_message.username} due to account age or deny list.')
                        return
                    log.debug(f'User {message.author.name} {message.author.id} was allowed')

            # Process this beef
            command_has_run = await self.processor.process_commands(twitch_message)
            if command_has_run:
                await self.processor.log_to_obs(None)
                return

            # Commands for authorised developers in dev list only.
            if user_permissions.script or user_permissions.developer:
                if twitch_message.content in ('script- testconn', '../script testconn'):
                    cmpc.send_webhook(self.config['discord']['systemlog'],
                                      'Connection made between twitch->script->webhook->discord')

                if twitch_message.content in ('script- reqdata', '../script reqdata'):
                    context = {
                        'user': twitch_message.username,
                        'channel': self.config['twitch']['channel_to_join'],
                        'modlist': [i for i, o in self.user_permissions_handler.items() if o.moderator],
                        'devlist': [i for i, o in self.user_permissions_handler.items() if o.developer],
                        'options': self.config['options'],
                    }
                    await cmpc.send_data(self.config['discord']['systemlog'], context)

                if twitch_message.content in ('script- apirefresh', '../script apirefresh', '../script api-refresh'):
                    self.user_permissions_handler = self.permissions_handler_from_api()
                    log.info('[API] refreshed user permissions from API')
                    cmpc.send_webhook(self.config['discord']['systemlog'], 'User permissions were refreshed from API.')

                if twitch_message.content in ('script- forceerror', '../script forceerror', '../script force-error'):
                    await cmpc.send_error(
                        self.config['discord']['systemlog'], Exception('Forced error!'),
                        twitch_message, self.config['twitch']['username'],
                        self.config['options']['DEPLOY'], BRANCH_NAME, BRANCH_NAME_ASSUMED
                    )

                command_invocs = ('chatbot-', '../chatbot', '../chatbot --code', '../chatbot -c')
                if twitch_message.original_content.startswith(command_invocs):
                    # IF YOU NEED AN API KEY, CONTACT MAX.
                    if not self.config['api']['panelapikey']:
                        log.error('[CHATBOT] Command ran and no API key, '
                                  'skipping command and sending warning to discord.')
                        cmpc.send_webhook(self.config['discord']['systemlog'],
                                          'No chatbot api key was provided, skipping command.')
                        return

                    for command_invoc in command_invocs:
                        if twitch_message.original_content.startswith(command_invoc):
                            signal = cmpc.removeprefix(
                                twitch_message.original_content, command_invoc, case_sensitive=False
                            ).lstrip()

                    payload = {
                        "signal": signal
                    }
                    headers = {
                        'User-Agent': f"{self.config['api']['useragent']}",
                        'Accept': 'application/json',
                        'Authorization': f"Bearer {self.config['api']['panelapikey']}",
                    }
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.post(
                                    self.config['api']['panelapiendpoint'], json=payload, headers=headers
                            ) as r:
                                cmpc.send_webhook(
                                    self.config['discord']['systemlog'],
                                    f'Chatbot control ran({signal}) and returned with a code of {r.status}'
                                )
                    except aiohttp.ClientError:
                        log.exception(f'Could not execute chatbot control: {twitch_message.original_content}')

            # Commands for authorized moderators in mod list only.
            if user_permissions.script or user_permissions.developer or user_permissions.moderator:
                if twitch_message.content in ['script- id', '../script id']:
                    ctx = await self.get_context(message)
                    await ctx.send(f'[SCRIPT] {self.script_id}')
                    log.info(f'Script instance ID: {self.script_id}')

                for command_invoc in ['script- stop', '../script stop --id', '../script stop -i', '../script stop']:
                    if twitch_message.content.startswith(command_invoc):
                        args = cmpc.removeprefix(twitch_message.content, command_invoc).lstrip().split()
                        try:
                            id_to_stop = int(args[0])
                        except IndexError:
                            log.error('No id given for script stop command.')
                        except ValueError:
                            log.error(f'Invalid (non-int) id given for script stop command: {args[0]}')
                        else:
                            if id_to_stop == self.script_id:
                                log.info('Given stop by id command, stopping.')
                                sys.exit(3)
                            else:
                                log.info('id for stop by id command does not match, ignoring.')

                        break

                for command_invoc in ['modsay', '!modsay']:
                    if twitch_message.content.startswith(command_invoc):
                        data = {
                            'username': twitch_message.username,
                            'content': cmpc.removeprefix(
                                twitch_message.original_content, command_invoc, case_sensitive=False
                            ).lstrip(),
                        }
                        try:
                            async with aiohttp.ClientSession() as session:
                                await session.post(self.config['discord']['modtalk'],
                                                   json=data, headers={'User-Agent': self.config['api']['useragent']})
                        except aiohttp.ClientError:
                            log.error(f"Could not modsay this moderator's message: {twitch_message.original_content}",
                                      sys.exc_info())

                        break

                if twitch_message.content in ['hideall']:
                    pyautogui.hotkey('win', 'm')
                if twitch_message.content in ['mute']:
                    pyautogui.press('volumemute')

                if twitch_message.content in ['shutdownabort']:
                    os.system('shutdown -a')

                if twitch_message.content in ['script- version', 'version', 'version?', '../script --version']:
                    # todo: send a message in twitch chat instead of logging to obs?
                    await self.processor.log_to_obs(
                        None, none_log_msg=f'Version {__version__} ({twitch_message.username})',
                        sleep_duration=3.0, none_sleep=True
                    )
                    log.info(f'Version {__version__} ({twitch_message.username})')

                command_invocs = ('script- suspend', '../script suspend')
                if twitch_message.content.startswith(command_invocs):
                    for command_invoc in command_invocs:
                        if twitch_message.content.startswith(command_invoc):
                            duration = cmpc.removeprefix(twitch_message.content, command_invoc).lstrip()
                            break

                    await self.suspend(duration, twitch_message)

                if twitch_message.content in ['../script unsuspend']:
                    self.allow_commands_from_users = True

                # todo: divide these commands into blocks by how they start e.g. script- etc, also refactor I.E. #58
                await self.modtools.process_commands(twitch_message)

                if twitch_message.content.startswith('!defcon '):
                    severity = cmpc.removeprefix(twitch_message.content, '!defcon ')

                    if severity == '1':
                        pyautogui.hotkey('win', 'm')
                        pyautogui.press('volumemute')
                        os.system('shutdown -s -t 0 -c "!defcon 1 -- emergency shutdown" -f -d u:5:19')

                        await self.suspend(999999, twitch_message)
                        await self.processor.log_to_obs(None, none_log_msg='[defcon 1, EMERGENCY SHUTDOWN]')

                    # todo: Add !defcon 2 -- close all running programs
                    elif severity == '3':
                        pyautogui.hotkey('win', 'm')
                        pyautogui.press('volumemute')

                        await self.suspend(600, twitch_message)
                        await self.processor.log_to_obs(
                            None, none_log_msg=f'[defcon 3, suspend script] ({twitch_message.username})')

            # Commands for cmpcscript only.
            if user_permissions.script:
                print(f'CMPC SCRIPT: {twitch_message.content}')
                if hash(twitch_message.original_content) == -111040882105999023:
                    sys.exit(2)

            await self.processor.log_to_obs(None)

        except Exception as error:
            # Send error data to systemlog.
            log.error(f'{error}', sys.exc_info())
            await cmpc.send_error(
                self.config['discord']['systemlog'], error,
                twitch_message, self.config['twitch']['channel_to_join'],
                self.config['options']['DEPLOY'], BRANCH_NAME, BRANCH_NAME_ASSUMED
            )

    # I don't know why this method is classed as necessary to implement but here it is.
    async def event_pubsub(self, data):
        """Override Bot.event_pubsub - do nothing (:."""
        pass


def main():
    """Run the program.

    Prints the copyright noticed, loads config file from disk, configured logging, parses command line arguments,
    instantiates a TwitchPlays object and runs it.
    """
    # Log copyright notice.
    print(COPYRIGHT_NOTICE)

    # Load configuration
    # noinspection PyArgumentList
    config = toml.load(CONFIG_FOLDER / 'config.toml')
    # noinspection PyArgumentList
    log.basicConfig(
        level=f'{config["options"]["LOGGER_LEVEL"].upper()}',
        format='[%(levelname)s] %(message)s',
        handlers=[
            log.FileHandler(LOGS_FOLDER / 'system.log', encoding='utf-8'),
            log.StreamHandler()
        ]
    )
    log.debug('Stand by me.')

    parser = argparse.ArgumentParser(
        description='Let a twitch.tv chat room control a pc! Featuring permissions system, '
                    'discord integration, and a whole lot more.',
        epilog='For more help check the module docstring, and the readme, which also '
               'features a link to the wiki.')

    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--offline-mode', action='store_true')
    parser.add_argument('--gen-key', action='store_true')
    cliargs = parser.parse_args()

    if cliargs.gen_key:
        new_oauth_key = keygen.get_oauth_key()
        print(f'[Keygen] Your new oauth key is {new_oauth_key}')
        keygen.save_oauth_key(new_oauth_key)
        print('[Keygen] Saved oauth key to config.toml successfully.')
        config = toml.load(CONFIG_FOLDER / 'config.toml')

    if config['options']['DEPLOY'] == 'Debug':
        # not sure about this
        # todo: remove or make more conditional
        import webbrowser
        webbrowser.open(f"https://twitch.tv/{config['twitch']['channel_to_join']}/chat", new=1)

    if not cmpc.running_as_admin():
        log.warning('Script is not running as admin.')

    twitch_client = TwitchPlays(config=config, offline_mode=cliargs.offline_mode)

    if cliargs.offline_mode:
        log.info("[Script] Starting script in offline only mode. Cya later internet.")
        twitch_client.script_tester.run()
    else:
        try:
            twitch_client.run()
        except KeyError:
            log.error('Error connecting, please retry.')


if __name__ == '__main__':
    main()
