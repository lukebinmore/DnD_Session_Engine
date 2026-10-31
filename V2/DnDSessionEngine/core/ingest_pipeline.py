from DnDSessionEngine.core.theme import con


def run_ingest_pipeline(data):
    campaign_data = data.get("campaign_data")
    gemini_client = data.get("gemini_client")
    llm_model = data.get("llm_model")
    con.rule("Session Ingest", style="rule.header")
