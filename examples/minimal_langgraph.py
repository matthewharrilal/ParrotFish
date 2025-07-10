# Minimal LangGraph example
# This script creates a trivial graph and executes it to verify LangGraph is working.

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

# Define a minimal state schema using TypedDict
class State(TypedDict):
    message: str

def start_node(state: State):
    print("DAG started!")
    return {"message": "Hello from START"}

def end_node(state: State):
    print(f"DAG ended! Message was: {state['message']}")
    return state

# Build the state graph
builder = StateGraph(State)
builder.add_node("start", start_node)
builder.add_node("end", end_node)
builder.add_edge(START, "start")
builder.add_edge("start", "end")
builder.add_edge("end", END)
graph = builder.compile()

# Run the graph with an initial state
graph.invoke({"message": ""})
