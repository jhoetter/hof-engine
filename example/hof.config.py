from hof import Config

config = Config(
    app_name="lead-enrichment",
    database_url="${DATABASE_URL}",
    redis_url="${REDIS_URL}",
    llm_provider="openai",
    llm_model="gpt-4o",
    llm_api_key="${OPENAI_API_KEY}",
    admin_username="admin",
    admin_password="${HOF_ADMIN_PASSWORD}",
    debug=True,
)
