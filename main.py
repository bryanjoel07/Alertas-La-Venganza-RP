"""Provision this bot's own resources before loading the copied workflows."""
import asyncio
import logging
import os
import runpy

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

if __name__ == '__main__':
    if not os.getenv('DISCORD_BOT_TOKEN'):
        raise SystemExit('Configura DISCORD_BOT_TOKEN en el servicio EssChino-Bot de Railway.')
    from studio_guard import install
    install()
    from store_bot import StoreBot
    StoreBot().run(os.environ['DISCORD_BOT_TOKEN'], log_handler=None)
