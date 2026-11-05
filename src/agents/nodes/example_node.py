from src.agents.state import AgentState


async def analyze_node(state: AgentState) -> dict:
    """Analyze query from user."""
    query = state.get("query", "")

    # TODO: Add real analysis logic (e.g., call LLM, search vector DB, etc.)
    analysis = f"Analysis: {query}"

    return {"analysis": analysis}


async def respond_node(state: AgentState) -> dict:
    """Generate final response from analysis."""
    analysis = state.get("analysis", "")
    error = state.get("error")

    if error:
        return {"response": f"Error: {error}"}

    # TODO: Add real response generation logic
    response = f"Result based on analysis: {analysis}"

    return {"response": response}
