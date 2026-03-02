# screen -L -md python3 run.py --server=discord --max_requests_per_prompt=20

# PLAN
# ai should get its own credit card
# ai should be able to do any transaction
# need integration with zepto, dominos, amazon, netflix, amazon prime, bookmyshow
# can we use browserbase for integeration of these?
# implement memory: each important detail, which could be needed in future, should be stored in memory

# TODO: implement webfetch tool asap!
# TODO: model should summarise its history somewhere
# basically manage its own memory - so, we can drop super long conversations
# TODO: implement whatsapp tomorrow
# we also need to let safeclaw know how we talk

# tool_result can become super long sometimes and model goes out of max length often

# DONE
# twitter, linkedin
# it should be controlled by simple discord channel

import fire
from dotenv import load_dotenv
assert load_dotenv()
from tvgbot.agent import LocalAgent, DiscordAgent


def main(server: str = "local", max_requests_per_prompt: int = 4):
    assert server in {"local", "discord"}
    agent = DiscordAgent() if server == "discord" else LocalAgent()
    print("Available Tools:", [tool["name"] for tool in agent.tools])
    agent.start(max_requests_per_prompt=max_requests_per_prompt)


if __name__ == "__main__":
    fire.Fire(main)
