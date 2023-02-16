import asyncio

import nextcord
from nextcord import SlashOption
from nextcord.ext import commands

from time import sleep
from chatgpt_wrapper import ChatGPT
from threading import Thread
import configparser
from speechkit import Session, SpeechSynthesis

# It's important to pass guild_ids explicitly while developing your bot because
# commands can take up to an hour to roll out when guild_ids is not passed. Once
# you deploy your bot to production, you can remove guild_ids to add your
# commands globally.
#
# You can find your guild ID by right clicking on the name of your server inside
# Discord and clicking "Copy ID".

DEV_GUILD_ID = 856999207583612938 # Replace with your guild ID
guild_ids = [DEV_GUILD_ID]

Api_key = '' #api ключ яндекса
catalog_id = ""

bot = commands.Bot()
config = configparser.ConfigParser()
session = Session.from_api_key(Api_key, catalog_id)
synthesizeAudio = SpeechSynthesis(session)

guild_to_voice_client = dict()

def _context_to_voice_channel(ctx):
    return ctx.user.voice.channel if ctx.user.voice else None


async def _get_or_create_voice_client(ctx):
    if ctx.guild.id in guild_to_voice_client:
        voice_client = guild_to_voice_client[ctx.guild.id]
    else:
        print(ctx.guild.id)
        voice_channel = _context_to_voice_channel(ctx)
        if voice_channel is None:
            voice_client = None
        else:
            voice_client = await voice_channel.connect()
            guild_to_voice_client[ctx.guild.id] = voice_client
    return (voice_client)

@bot.slash_command(
    name="join",
    guild_ids=guild_ids,
)
async def join_vc(ctx: nextcord.Interaction):  #для присоединения к каналу
    voice_client = await _get_or_create_voice_client(ctx)
    if voice_client is None:
        await ctx.response.send_message(
            "You're not in a voice channel. Join a voice channel to invite the bot!",
            ephemeral=True,
        )
    elif ctx.user.voice and voice_client.channel.id != ctx.user.voice.channel.id:
        old_channel_name = voice_client.channel.name
        await voice_client.disconnect()
        voice_client = await ctx.user.voice.channel.connect()
        new_channel_name = voice_client.channel.name
        guild_to_voice_client[ctx.guild.id] = voice_client
        await ctx.response.send_message(
            f"Switched from #{old_channel_name} to #{new_channel_name}!"
        )
    else:
        await ctx.response.send_message("Connected to voice channel!")
        guild_to_voice_client[ctx.guild.id] = voice_client


@bot.slash_command(name="kick", guild_ids=guild_ids)
async def kick_vc(ctx: nextcord.Interaction): #для отключения от канала
    if ctx.guild.id in guild_to_voice_client:
        voice_client = guild_to_voice_client.pop(ctx.guild.id)
        await voice_client.disconnect()
        await ctx.response.send_message("Disconnected from voice channel")
    else:
        await ctx.response.send_message(
            "Bot is not connected to a voice channel. Nothing to kick.", ephemeral=True
        )

@bot.slash_command(
    name="ask",
    guild_ids=guild_ids,
)
async def speak_vc(     #получения зпроса, отправка в ChatGPT, и озвучивание
    ctx: nextcord.Interaction,
    msg: str = SlashOption(
        name="msg", description="Рrompt for voiceGPT", required=True
    ),
):
    voice_client = await _get_or_create_voice_client(ctx)
    if voice_client:
        config.read('gptTemp.ini')
        await asyncio.sleep(0.5)
        config['chatGPT']['allow'] = 'yes' #разрешить ChatGPT обработать запрос
        config['chatGPT']['ask'] = msg     #сообщение для ChatGPT
        with open('gptTemp.ini', 'w') as configfile:    # save
                config.write(configfile)

        botMsg = await ctx.response.send_message("Processing...",)

        config.read('gptTemp.ini')
        while config["chatGPT"]["allow"] == 'yes': #проигрывать звук пока идёт обработка
            if not voice_client.is_playing():
                source = await nextcord.FFmpegOpusAudio.from_probe("loading.mp3", method="fallback")
                voice_client.play(source, after=None)
                await asyncio.sleep(0.5)
                config.read('gptTemp.ini') #обновление конфига

        voice_client.stop()
        response = config.get("chatGPT", "response") #ответ ChatGpt

        await botMsg.edit(content="", embed=nextcord.Embed(title=f'{ctx.user}: {msg}', description= f"**VoiceGPT**: {response}")) #изменить сообщение в дс

        synthesizeAudio.synthesize(         #сгенерировать голос
        'out.mp3', text=response,
        voice=config["chatGPT"]["voice"], format='oggopus', sampleRateHertz='16000' #голос меняется в конфиге (https://cloud.yandex.ru/docs/speechkit/tts/voices)
        )
        
        source = await nextcord.FFmpegOpusAudio.from_probe("out.mp3", method="fallback")
        voice_client.play(source, after=None)       #воспроизвести голос
        while voice_client.is_playing():
            await asyncio.sleep(0.5)
        
    else: # проверка находится ли user в гс канале
        await ctx.response.send_message(
            "You're not in a voice channel. Join a voice channel to invite the bot!",
            ephemeral=True,
        )

@bot.slash_command(
    name="retry",
    guild_ids=guild_ids,
)
async def retry(ctx: nextcord.Interaction):  #повтор ответа от ChatGpt
    voice_client = await _get_or_create_voice_client(ctx)
    if voice_client:
        config.read('gptTemp.ini')
        response = config.get("chatGPT", "response")
        await ctx.response.send_message(f"last response: ",embed=nextcord.Embed(description=response))
        source = await nextcord.FFmpegOpusAudio.from_probe("out.mp3", method="fallback") #проигрывание прошлого запроса
        voice_client.play(source, after=None)
        while voice_client.is_playing():
            await asyncio.sleep(0.5)


# Do the same thing for /vc-kick and the rest of the commands...

# Run the bot
DISCORD_TOKEN = "<token>" #токен бота (https://discord.com/developers/applications/)

def gptMain(): #получение данных от ChatGPT в отдельном потоке
    gpt = ChatGPT()
    while True:
        try:
            config.read('gptTemp.ini') #загрузка конфига
            sleep(0.15)
            if config["chatGPT"]["allow"] == 'yes':
                config["chatGPT"]["response"] = gpt.ask(config.get("chatGPT", "ask")) # запрос к ChatGPT
                config['chatGPT']['allow'] = 'no'
                with open('gptTemp.ini', 'w') as configfile:    # save
                    config.write(configfile)
        except:
            print('tread1 error')
                
if __name__ == "__main__":
    
    loop = asyncio.get_event_loop()
    try:
        tread1 = Thread(target=gptMain) # запуск потока
        tread1.start()
        print('started tread')
        loop.run_until_complete(bot.start(DISCORD_TOKEN)) # запуск бота
    except KeyboardInterrupt:
        loop.run_until_complete(bot.close())
    finally:
        loop.close()
