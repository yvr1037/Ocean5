import streamlit as st
import json
import uuid
from datetime import datetime
import os
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

from game_engine import GameEngine
from llm_interface import get_available_models
from utils import save_game_results

# Load environment variables
load_dotenv()


def apply_shared_styles():
    """Apply shared CSS styles for cards and UI elements"""
    st.markdown(
        """
    <style>
    /* Shared card styles */
    .styled-card {
        border-radius: 8px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        padding: 15px;
        margin-bottom: 10px;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        display: flex;
        flex-direction: column;
    }
    
    /* Agent card specific styles */
    .agent-card {
        height: 120px;
    }
    
    /* Text styling classes */
    .card-title {
        font-size: 16px;
        font-weight: 600;
        margin: 0;
        padding: 0;
    }
    .card-subtitle {
        font-size: 13px;
        font-style: italic;
        margin-top: 4px;
        margin-bottom: 8px;
    }
    .card-status {
        font-size: 14px;
        font-weight: 500;
        margin-top: auto;
        padding-top: 5px;
    }
    .highlighted-badge {
        display: inline-block;
        padding: 3px 8px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
        margin-top: 5px;
    }
    
    /* Vote card specific styles */
    .vote-card {
        text-align: center;
        transition: transform 0.2s ease;
    }
    .vote-card:hover {
        transform: translateY(-2px);
    }
    .vote-count {
        font-size: 24px;
        font-weight: 700;
        margin: 8px 0;
    }
    .detailed-vote {
        padding: 12px;
    }
    .vote-reasoning {
        font-size: 14px;
        font-style: italic;
        margin-top: 8px;
        padding: 8px;
        border-radius: 6px;
        background-color: rgba(0,0,0,0.03);
    }
    </style>
    """,
        unsafe_allow_html=True,
    )


# Page configuration
st.set_page_config(page_title="Detective Game Simulation", layout="wide")
apply_shared_styles()


# Define agent colors
AGENT_COLORS = {
    "Openness Agent": "#3366CC",  # Blue
    "Conscientiousness Agent": "#DC3912",  # Red
    "Extraversion Agent": "#FF9900",  # Orange
    "Agreeableness Agent": "#109618",  # Green
    "Neuroticism Agent": "#990099",  # Purple
}

# Initialize session state variables
if "game_initialized" not in st.session_state:
    st.session_state.game_initialized = False
    st.session_state.game_id = None
    st.session_state.current_round = 0
    st.session_state.game_complete = False
    st.session_state.game_log = []
    st.session_state.votes = {}
    st.session_state.game_outcome = None
    st.session_state.current_questioner = None
    st.session_state.round_in_progress = False
    st.session_state.next_action = "round"  # can be "round" or "voting"


def initialize_new_game(model_name):
    """Initialize a new game session"""
    st.session_state.game_id = str(uuid.uuid4())
    st.session_state.model_name = model_name
    st.session_state.game_engine = GameEngine(model_name)
    st.session_state.game_initialized = True
    st.session_state.current_round = 1
    st.session_state.game_complete = False
    st.session_state.game_log = []
    st.session_state.votes = {}
    st.session_state.game_outcome = None
    st.session_state.round_in_progress = False
    st.session_state.current_questioner = None
    st.session_state.next_action = "round"
    st.session_state.voting_conducted = False

    # Trigger immediate rerun to start the first round
    # st.experimental_rerun()
    st.rerun()


def run_game_round():
    """Run a single round of the game"""
    if st.session_state.round_in_progress:
        return

    st.session_state.round_in_progress = True
    game_engine = st.session_state.game_engine

    # Set current questioner based on round
    questioner_idx = (st.session_state.current_round - 1) % len(game_engine.agents)
    st.session_state.current_questioner = game_engine.agents[questioner_idx].name

    progress_placeholder = st.empty()
    progress_placeholder.info(f"Running round {st.session_state.current_round}...")

    try:
        with ThreadPoolExecutor() as executor:
            future = executor.submit(game_engine.run_round, st.session_state.current_round)
            round_results = future.result()

        st.session_state.game_log.append(round_results)
        st.session_state.current_round += 1
        st.session_state.voting_conducted = False

        # Check if voting should occur after every 3 rounds
        if (st.session_state.current_round - 1) % 3 == 0:
            st.session_state.next_action = "voting"
        else:
            st.session_state.next_action = "round"

    except Exception as e:
        st.error(f"Error in game round: {str(e)}")

    finally:
        progress_placeholder.empty()
        st.session_state.round_in_progress = False
        # st.experimental_rerun()
        st.rerun()


def conduct_voting():
    """Conduct the voting phase after every 3 rounds until majority consensus"""
    if st.session_state.round_in_progress:
        return

    st.session_state.round_in_progress = True
    game_engine = st.session_state.game_engine
    progress_placeholder = st.empty()
    progress_placeholder.info("Conducting voting phase...")

    try:
        with ThreadPoolExecutor() as executor:
            future = executor.submit(game_engine.conduct_voting)
            votes = future.result()

        st.session_state.votes = votes
        st.session_state.voting_conducted = True

        # Count votes
        vote_counts = {}
        for voter, vote_info in votes.items():
            target = vote_info["vote"]
            vote_counts[target] = vote_counts.get(target, 0) + 1
        st.session_state.vote_counts = vote_counts

        # Check for majority (3+ votes for any agent)
        majority_agent = None
        for agent, count in vote_counts.items():
            if count >= 3:
                majority_agent = agent
                break

        # Store voting results in outcome
        st.session_state.game_outcome = {
            "majority_found": majority_agent is not None,
            "majority_agent": majority_agent,
            "vote_distribution": vote_counts,
            "rounds_played": st.session_state.current_round - 1,
            "correctly_identified": majority_agent == game_engine.killer.name if majority_agent else False,
        }

        # Save results after each voting
        results = {
            "game_id": st.session_state.game_id,
            "model": st.session_state.model_name,
            "actual_killer": game_engine.killer.name,
            "rounds": st.session_state.game_log,
            "votes": votes,
            "outcome": st.session_state.game_outcome,
        }
        save_game_results(results)

        # End game if majority found or max rounds reached
        if majority_agent or st.session_state.current_round > 20:
            st.session_state.game_complete = True
        else:
            st.session_state.next_action = "round"

    except Exception as e:
        st.error(f"Error in voting phase: {str(e)}")

    finally:
        progress_placeholder.empty()
        st.session_state.round_in_progress = False
        # st.experimental_rerun()
        st.rerun()




# UI Layout
st.title("Detective Game Simulation")

# Model selection
available_models = get_available_models()
selected_model = st.selectbox("Select Language Model", available_models)

# Game controls
col1, col2 = st.columns([1, 3])
with col1:
    if not st.session_state.game_initialized:
        if st.button("Start New Game"):
            initialize_new_game(selected_model)
    else:
        if not st.session_state.game_complete:
            st.write("Game automatically progressing...")
            if st.button("Skip to Next Step"):
                if st.session_state.next_action == "voting":
                    conduct_voting()
                else:
                    run_game_round()
        else: 
            if st.button("Start New Game"):
                initialize_new_game(selected_model)

# Game state display
if st.session_state.game_initialized:
    with col2:
        st.write(f"Game ID: {st.session_state.game_id}")
        st.write(f"Current Round: {max(0, st.session_state.current_round - 1)}")
        st.write(f"Model: {st.session_state.model_name}")

        if st.session_state.game_complete:
            killer = st.session_state.game_engine.killer.name
            if st.session_state.game_outcome["correctly_identified"]:
                st.success(f"The killer ({killer}) was successfully identified!")
            else:
                st.error(f"The killer ({killer}) was not identified.")

            st.write(f"Vote Distribution: {st.session_state.game_outcome['vote_distribution']}")
           

