"""
bonus_langchain_agent.py - the same agent built with LangChain + LangGraph.

Same tools, same Pydantic schemas, same confirmation gate and audit log.
The difference: LangGraph runs the tool loop for you. Compare it with agent.py
to see what the framework hides (parallel execution, the message plumbing,
confidence tracking and forced escalation are not here).

    python bonus_langchain_agent.py
"""

from dotenv import load_dotenv
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from guardrails import AuditLog, ConfirmationGate, cli_approver
from run_api import start_background
from tools import TOOLS, ApiClient, Context

load_dotenv()
CUSTOMER = "CUST-0002"
ctx = Context(customer_id=CUSTOMER, api=ApiClient(CUSTOMER, start_background(8000)))
gate = ConfirmationGate(cli_approver, AuditLog())


def wrap(tool):
    """Turn one of our tools into a LangChain StructuredTool. Pydantic validation comes free via args_schema."""
    def run(**kwargs):
        args = tool.args_model(**kwargs)
        if tool.kind == "write":                       # human-in-the-loop for refunds/cancels
            allowed, message = gate.authorise("LC-session", ctx, tool, args)
            if not allowed:
                return {"status": "NOT_EXECUTED", "message": message}
        result = tool.run(args, ctx)
        if tool.kind != "read":
            gate.audit.log("LC-session", CUSTOMER, tool.name, args.model_dump(mode="json"),
                           "HANDOFF" if tool.kind == "handoff" else "EXECUTED", ctx.approver_name or "agent",
                           "", result)
        return result
    return StructuredTool.from_function(func=run, name=tool.name, description=tool.description,
                                        args_schema=tool.args_model)


if __name__ == "__main__":
    agent = create_react_agent(ChatOpenAI(model="gpt-4o-mini", temperature=0.1),
                               tools=[wrap(t) for t in TOOLS.values()],
                               prompt="You are Nova, NovaShop's support agent. Customer ID " + CUSTOMER +
                                      ". Look things up with tools; check refund eligibility before refunding.")
    question = "My headphones from NS-10004 arrived broken. Can I get a refund?"
    result = agent.invoke({"messages": [("user", question)]}, config={"recursion_limit": 12})
    for m in result["messages"]:
        print(f"--- {type(m).__name__} ---\n{getattr(m, 'tool_calls', None) or m.content}\n")
