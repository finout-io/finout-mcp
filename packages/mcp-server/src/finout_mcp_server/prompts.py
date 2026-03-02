"""MCP prompt template definitions."""


async def list_prompts() -> list[dict]:
    """List available prompt templates"""
    return [
        {
            "name": "monthly_cost_review",
            "description": "Comprehensive monthly cost review and analysis",
            "arguments": [],
        },
        {
            "name": "find_waste",
            "description": "Identify cost optimization opportunities",
            "arguments": [],
        },
        {
            "name": "investigate_spike",
            "description": "Investigate a cost spike or anomaly",
            "arguments": [
                {
                    "name": "service",
                    "description": "Cloud service to investigate (optional)",
                    "required": False,
                }
            ],
        },
    ]


async def get_prompt(name: str, arguments: dict | None = None) -> dict:
    """Get a prompt template"""

    if name == "monthly_cost_review":
        return {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Please provide a comprehensive monthly cost review:\n\n"
                        "1. Use query_costs for this_month and last_month\n"
                        "2. Use compare_costs to show the trend\n"
                        "3. Check for any anomalies\n"
                        "4. Identify the top 5 cost drivers\n"
                        "5. Suggest any optimization opportunities\n\n"
                        "Present the findings in a clear, executive-friendly format."
                    ),
                }
            ]
        }

    elif name == "find_waste":
        return {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Analyze our cloud infrastructure for cost optimization opportunities:\n\n"
                        "1. Check get_waste_recommendations for idle resources\n"
                        "2. Look for rightsizing opportunities\n"
                        "3. Calculate total potential savings\n"
                        "4. Prioritize the top 10 recommendations by savings amount\n"
                        "5. Estimate annual impact if all recommendations are implemented\n\n"
                        "Present a prioritized action plan."
                    ),
                }
            ]
        }

    elif name == "investigate_spike":
        service = arguments.get("service") if arguments else None
        service_filter = f" for {service}" if service else ""

        return {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Investigate recent cost spikes{service_filter}:\n\n"
                        "1. Get anomalies for the last 7 days\n"
                        "2. For each anomaly, compare costs to the previous period\n"
                        "3. Identify what changed (new resources, usage spike, etc.)\n"
                        "4. Assess if this is a one-time event or ongoing trend\n"
                        "5. Recommend actions to address the spike\n\n"
                        "Provide root cause analysis and remediation steps."
                    ),
                }
            ]
        }

    else:
        raise ValueError(f"Unknown prompt: {name}")
