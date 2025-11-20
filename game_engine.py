import random
from typing import List, Dict, Any
from llm_interface import run_llm_query
from prompts import (
    BASE_GAME_CONTEXT,
    PERSONALITY_PROMPTS,
    QUESTION_GENERATION_PROMPT,
    ANSWER_GENERATION_PROMPT,
    VOTING_PROMPT,
)


class Agent:
    def __init__(self, name: str, personality_type: str):
        self.name = name
        self.personality_type = personality_type
        self.is_killer = False

    def __str__(self):
        return f"{self.name} ({self.personality_type})"


class GameEngine:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.agents = self._create_agents()
        self.killer = self._select_killer()
        self.conversation_history = []
        self.current_questioner_idx = 0

    def _create_agents(self) -> List[Agent]:
        """Create the 5 agents with different personality types"""
        personalities = [
            "openness",
            "conscientiousness",
            "extraversion",
            "agreeableness",
            "neuroticism",
        ]
        return [Agent(f"{p.capitalize()} Agent", p) for p in personalities]

    def _select_killer(self) -> Agent:
        """Randomly select one agent as the killer"""
        killer = random.choice(self.agents)
        killer.is_killer = True
        return killer

    def _format_conversation_history(self) -> str:
        """Format the conversation history for inclusion in prompts"""
        formatted_history = ""

        for idx, round_data in enumerate(self.conversation_history):
            formatted_history += f"[Round {idx + 1}]\n"
            formatted_history += (
                f'{round_data["questioner"]} asked: "{round_data["question"]}"\n'
            )

            for responder, response in round_data["answers"].items():
                formatted_history += f'{responder} answered: "{response}"\n'

            formatted_history += "\n"

        return formatted_history

    def run_round(self, round_number: int) -> Dict[str, Any]:
        """Run a single round of the game, including question and answers"""

        # Select this round's questioner
        questioner = self.agents[self.current_questioner_idx]
        self.current_questioner_idx = (self.current_questioner_idx + 1) % len(
            self.agents
        )

        # Generate the question
        question = self._generate_question(questioner, round_number)

        # Add a debug print
        # print(f"[{self.model_name}] Question generated: {question}")

        # Get answers from all other agents
        answers = {}
        for agent in self.agents:
            if agent != questioner:
                answer = self._generate_answer(
                    agent, questioner, question, round_number
                )
                # Add a debug print
                # print(f"Answer from {agent.name}: {answer}")
                answers[agent.name] = answer.strip()  # Ensure clean strings

        # Record this round in history
        round_data = {
            "round": round_number,
            "questioner": questioner.name,
            "question": question.strip(),  # Ensure clean strings
            "answers": answers,
        }

        self.conversation_history.append(round_data)
        return round_data

    def _generate_question(self, agent: Agent, round_number: int) -> str:
        """Generate a question from an agent based on their personality"""

        personality_prompt = PERSONALITY_PROMPTS[agent.personality_type]
        conversation_history = self._format_conversation_history()

        prompt_vars = {
            "base_context": BASE_GAME_CONTEXT,
            "personality_prompt": personality_prompt,
            "agent_name": agent.name,
            "personality_type": agent.personality_type,
            "current_round": round_number,
            "conversation_history": conversation_history,
        }

        question = run_llm_query(
            model=self.model_name,
            prompt_template=QUESTION_GENERATION_PROMPT,
            prompt_vars=prompt_vars,
        )

        return question.strip()

    def _generate_answer(
        self, agent: Agent, questioner: Agent, question: str, round_number: int
    ) -> str:
        """Generate an answer from an agent based on their personality"""

        personality_prompt = PERSONALITY_PROMPTS[agent.personality_type]
        conversation_history = self._format_conversation_history()
        killer_status = "the killer" if agent.is_killer else "not the killer"

        prompt_vars = {
            "base_context": BASE_GAME_CONTEXT,
            "personality_prompt": personality_prompt,
            "agent_name": agent.name,
            "personality_type": agent.personality_type,
            "current_round": round_number,
            "conversation_history": conversation_history,
            
            "questioner_name": questioner.name,
            "current_question": question,
            "killer_status": killer_status,
        }

        answer = run_llm_query(
            model=self.model_name,
            prompt_template=ANSWER_GENERATION_PROMPT,
            prompt_vars=prompt_vars,
        )

        return answer.strip()

    def conduct_voting(self) -> Dict[str, Dict[str, str]]:
        """Have each agent vote on who they think the killer is"""
        votes = {}

        for agent in self.agents:
            personality_prompt = PERSONALITY_PROMPTS[agent.personality_type]
            conversation_history = self._format_conversation_history()

            # Only valid agents (not self)
            valid_agents = [a.name for a in self.agents if a.name != agent.name]
            agent_names_bullets = "\n".join([f"  - {name}" for name in valid_agents])
            agent_names_str = ", ".join([f'"{name}"' for name in valid_agents])

            # Try up to 3 times to get a valid vote
            max_attempts = 3
            for attempt in range(max_attempts):
                # Add retry context to help guide the model better on retry attempts
                retry_guidance = ""
                previous_error = ""
                if attempt > 0:
                    retry_guidance = (
                        f"IMPORTANT: Previous response could not be used. "
                        f"You must format your response as valid JSON and vote for an agent that is not yourself. "
                        f"Valid agents to vote for (excluding yourself): "
                        f"{', '.join(valid_agents)}"
                        f" Previous error: {previous_error}"
                    )

                prompt_vars = {
                    "base_context": BASE_GAME_CONTEXT,
                    "personality_prompt": personality_prompt,
                    "agent_name": agent.name,
                    "personality_type": agent.personality_type,
                    "rounds_played": len(self.conversation_history),
                    "conversation_history": conversation_history,
                    
                    "agent_names": agent_names_str,
                    "agent_names_list": valid_agents,
                    "agent_names_bullets": agent_names_bullets,
                    "retry_guidance": retry_guidance,
                }

                try:
                    vote_response = run_llm_query(
                        model=self.model_name,
                        prompt_template=VOTING_PROMPT,
                        prompt_vars=prompt_vars,
                    )

                    # Try to extract JSON from the response
                    import json
                    import re

                    # Look for JSON pattern in the response
                    json_match = re.search(
                        r"```json\s*(.*?)\s*```", vote_response, re.DOTALL
                    )
                    if json_match:
                        json_str = json_match.group(1)
                    else:
                        # If not in code block, try to parse the whole response
                        json_str = vote_response.strip()

                    # Parse the JSON
                    vote_data = json.loads(json_str)

                    vote_target = vote_data.get("vote", "").strip()
                    reasoning = vote_data.get("reasoning", "").strip()

                    # Validate the vote target is an actual agent name
                    if vote_target not in valid_agents:
                        print(
                            f"[{self.model_name}] Invalid vote from {agent.name} (attempt {attempt + 1}): '{vote_target}' is not a valid agent"
                        )
                        raise ValueError(
                            f"Invalid vote target: {vote_target}. Must be one of {valid_agents}."
                        )
                    else:
                        # Valid vote, exit retry loop
                        break

                except Exception as e:
                    print(
                        f"[{self.model_name}] Error parsing vote JSON for {agent.name} (attempt {attempt + 1}): {e}"
                    )
                    previous_error = str(e)
                    if attempt < max_attempts - 1:
                        continue  # Try again with better guidance

                    # Last attempt failed, use random agent
                    valid_agents = [a.name for a in self.agents if a.name != agent.name]
                    vote_target = random.choice(valid_agents)
                    reasoning = f"[Error processing vote: {str(e)}. Random vote generated as fallback]"
                    print(
                        f"[{self.model_name}] Warning: {agent.name} vote couldn't be parsed, using random: {vote_target}"
                    )

            votes[agent.name] = {"vote": vote_target, "reasoning": reasoning}

        return votes
