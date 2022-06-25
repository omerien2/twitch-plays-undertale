[More documentation in the central wiki.](https://gitlab.com/controlmypc/docs/-/wikis/documentation/Script)

(This is a fork of https://gitlab.com/cmpcsg/TwitchPlays. The history of the repo is still here, although every profile link has been replaced by the github URL.)
(This is basically their stuff but with some commands deleted.)

# TwitchPlays

The script that allows controlling of ~~a pc~~ Undertale remotely through a Twitch chat. Started as an overhaul update to DougDoug TwitchPlays script.


# NOTICE: Under the license, you must disclose the source of this code in all usages. 

# Installation:

  (Note: It is recommended that you know how to use the Terminal of your OS and that you have basic knowledge of the Git CLI.)

  1) In order to run you must download a 3.X.X version of Python (https://www.python.org/downloads/). The script is normally run on python version `3.8` - `3.9`. The current recommended python version [runtime.txt](https://gitlab.com/controlmypc/TwitchPlays/-/blob/main/runtime.txt) using the [heroku style](https://devcenter.heroku.com/articles/python-runtimes).

  2) To install you can either do one of 2 things.
  - Clone using Git
  - Download the Zip file

  3) After downloading open a terminal of your choice, and run these commands to install the script's dependencies (using a [virtualenv](https://docs.python.org/3/tutorial/venv.html) or other virtual environment can be a good idea)::

  * `python -m pip install --upgrade pip wheel`
  * `python -m pip install -r requirements.txt`

  4)  Create `config/config.toml` based on `config/config.example.toml` with your Twitch username, oauth key, and other info and settings. (you can generate a blank config.toml with `config/create_empty_config.py` and get a Twitch oauth token with `new_oauth_key.py`).

  5) Run `TwitchPlays.py` using `python TwitchPlays.py` - You can do this as a command on most environments as `TwitchPlays`.

## "I don't have all this fancy stuff (Discord webhooks, API for moderator lists, etc.), what can I do?"

- No API ) If you don't have a Webserver or CDN hosting your config, you can modify `TwitchPlays.py (Line 137)` to use a static user list. Leaving out config values is a wanted feature and may be added in the future

Example static user list.
```
{
  "devlist" : [
    "developers here"
  ],
  "modlist" : [
    "moderators here"
  ]
}

```

- No Webhooks: If you don't know how to make a discord webhook, there are plenty of guides online. Without a webhook most commands do absolutely nothing. If you would like to send webhooks to a different service (I.E: Slack), you can modify some of the webhook code (`./cmpc/utils.py` handles most webhooks.). You can use 1 webhook for the entire script, but it is not recommended.

# What's New highlight:

Close individual instances if multiple are running by accident, using the new `../script id` and `../script stop <id>` commands.

For more, see the [changelog](https://github.com/omerien/twitch-plays-undertale/blob/main/CHANGELOG.md).
