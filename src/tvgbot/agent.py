import asyncio
import json
from copy import deepcopy
from datetime import datetime

from anthropic import Anthropic

from .discord import DiscordClient
from .tools import TOOL_REGISTRY
from .utils import convert_messages_to_string, parse_assistant

# TODO: check if gmail returns the date in email?
# tell gmail that it has access to top 10 emails only? so, need to design query accordingly
#

SYSTEM_PROMPT = f"""
You are the Executive Assistant of Vasudev Gupta.

Your responsibility is to take actions on his behalf across communication platforms, including:
- Managing his Twitter and LinkedIn accounts.
- Listening to and replying to messages on WhatsApp and Gmail.

Core Responsibilities:

1. Communication Management
   - Read, interpret, and respond to messages professionally.
   - Maintain Vasudev’s tone: concise, thoughtful, and strategic.
   - Prioritize clarity and relationship-building in every interaction.

2. Continuous Learning
   - For every person you interact with on WhatsApp or Gmail:
     • Learn relevant details about them (role, company, context, interests, intent).
     • Track past conversations and context.
     • Most importantly: Document all learnings in memory for future reference.

3. Smart Information Retrieval
   - If asked about something you are unsure of, do NOT immediately say you don’t know.
   - First check sources in this order:
       1. Gmail
       2. Twitter
       3. LinkedIn
   - Stop as soon as sufficient information is found.
   - Always prioritize the most recent information first.

   Example:
   - If asked: "Did I get a reply from <person-name>?"
     → First check the latest Gmail replies from that person.
     → If not found, then check other platforms as needed.

4. Tool Execution Handling
   - If you receive: "tool execution was skipped as user didn't approve the tool" as a tool_result:
       • Understand that execution was skipped for now.
       • Save that tool action in a backlog for future execution.
       • Inform the user:
         "Tool execution was skipped as requested. I’ve saved it in the backlog and will execute it whenever you ask again."

5. Behavioral Rules
   - Act proactively but responsibly.
   - Maintain confidentiality at all times.
   - Never hallucinate facts — verify using available platforms first.
   - Be structured, organized, and execution-focused.

Today's date is {datetime.now().strftime("%-d %B %Y")}.
""".strip()


# TODO: add support for open-router as well - we want to understand how cogito model does here
# this way we will understand where our models stands compared to claude on real world tasks with our harness
class LocalAgent:
    def __init__(
        self,
        model: str = "claude-sonnet-4-5",
        max_tokens: int = 16_384,
        enable_thinking: bool = False,
        thinking_budget: int = 14_336,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.enable_thinking = enable_thinking
        self.thinking_budget = thinking_budget

        self.tools = [tool.schema for tool in TOOL_REGISTRY.values()]
        self.system_prompt = SYSTEM_PROMPT

        self.client = Anthropic()

    def request_model(self, messages):
        thinking = (
            {"type": "enabled", "budget_tokens": self.thinking_budget}
            if self.enable_thinking
            else {"type": "disabled"}
        )
        response = self.client.messages.create(
            model=self.model,
            messages=messages,
            tools=self.tools,
            system=self.system_prompt,
            max_tokens=self.max_tokens,
            thinking=thinking,
        )
        content = [part.model_dump() for part in response.content]
        return {"role": "assistant", "content": content}

    def get_tool_calls(self, response):
        return [
            {
                "tool_call_id": part["id"],
                "name": part["name"],
                "arguments": part["input"],
            }
            for part in response["content"]
            if part["type"] == "tool_use"
        ]

    async def request_user_approval(self, prompt, **kwargs):
        return input(prompt)

    async def __call__(self, input_messages, max_requests=10, **kwargs):
        response = self.request_model(input_messages)
        output_messages = [response]

        tool_calls = self.get_tool_calls(response)
        num_requests = 1
        while len(tool_calls) > 0:
            if num_requests >= max_requests:
                break

            tool_results = []
            for tool_call in tool_calls:
                name, arguments = tool_call["name"], tool_call["arguments"]
                tool = TOOL_REGISTRY[name]
                if tool.requires_approval:
                    prompt = f'Please type "approve" to approve\n```\n{tool.__name__}(**{json.dumps(arguments, indent=2)})\n```'
                    user_response = await self.request_user_approval(prompt, **kwargs)
                    tool_result = (
                        tool(**arguments)
                        if user_response.lower() == "approve"
                        else "Skipped tool execution as user DID NOT approve."
                    )
                else:
                    tool_result = tool(**arguments)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_call["tool_call_id"],
                        "content": tool_result,
                    }
                )
            output_messages += [{"role": "user", "content": tool_results}]
            response = self.request_model(input_messages + output_messages)
            output_messages += [response]

            tool_calls = self.get_tool_calls(response)
            num_requests += 1

        return output_messages

    def start(self, max_requests_per_prompt=4):
        messages = []
        while True:
            prompt = input("--- User ---\n")
            messages += [{"role": "user", "content": prompt}]
            try:
                output_messages = asyncio.run(
                    self(messages, max_requests=max_requests_per_prompt)
                )
            except KeyboardInterrupt:
                break
            except Exception as exception:
                print(f"--- Failed with exception ---\n{exception}")
                messages.pop()
                continue
            messages += output_messages
            print("--- Assistant ---\n", parse_assistant(messages[-1]["content"]))
        return messages


# TODO: we should call anthropic api async
# TODO: we should do stream mode?
# TODO: discord thread can be supported nicely?
# TODO: maybe reasoning should be sent back within a file?
class DiscordAgent(LocalAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.discord_client = DiscordClient()

    async def request_user_approval(self, prompt, **kwargs):
        await self.discord_client.send_message(prompt, kwargs["channel_id"])
        response = await self.discord_client.receive_message()
        return response["content"]

    def start(self, max_requests_per_prompt=4):
        asyncio.run(self.start_discord(max_requests_per_prompt=max_requests_per_prompt))

    # TODO: if text is super long - make threads automatically
    # TODO: post internal reasoning in thread of question?
    # TODO: move as much discord to DiscordClient class
    # TODO: implement reminder - tvgbot should save reminders somewhere
    async def start_discord(self, max_requests_per_prompt=4):
        await self.discord_client.start()
        messages = []
        while True:
            message = await self.discord_client.receive_message()
            content, channel_id = message["content"], message["channel_id"]
            messages += [{"role": "user", "content": content}]

            output_messages = await self(
                messages,
                max_requests=max_requests_per_prompt,
                channel_id=channel_id,
            )

            # try:
            #     output_messages = await self(
            #         messages,
            #         max_requests=max_requests_per_prompt,
            #         channel_id=channel_id,
            #     )
            # except KeyboardInterrupt:
            #     break
            # except Exception as exception:
            #     await self.discord_client.send_message(
            #         f"--- Failed with exception ---\n{exception}", channel_id
            #     )
            #     messages.pop()
            #     continue

            messages += output_messages
            content = parse_assistant(messages[-1]["content"])
            await self.discord_client.send_message(content, channel_id)

            internal_reasoning = self.get_internal_reasoning(output_messages)
            await self.discord_client.send_message(
                internal_reasoning,
                channel_id,
                self.discord_client.bot_last_message["message_id"],
            )

    # stream reasoning - message by message - ideally in thread
    def get_internal_reasoning(self, messages):
        reasoning = convert_messages_to_string(messages)
        if len(reasoning) > 1024:
            reasoning = "... " + reasoning[-1024:]
        return reasoning
