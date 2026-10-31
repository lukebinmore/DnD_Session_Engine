from DnDSessionEngine.core.theme import con


def run_assistant_pipeline(data):
    campaign_data = data.get("campaign_data")
    llm_model = data.get("llm_model")
    con.clear()
    con.rule("AI Campaign Assistant", style="rule.header")
