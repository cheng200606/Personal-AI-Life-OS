from personal_ai_life_os.config import Settings


def test_chat_completions_url_defaults_to_the_openai_host() -> None:
    config = Settings(_env_file=None)
    assert config.openai_chat_completions_url == "https://api.openai.com/v1/chat/completions"


def test_chat_completions_url_follows_a_compatible_base_url() -> None:
    config = Settings(_env_file=None, openai_base_url=" https://gateway.example.test/v1/ ")
    assert config.openai_chat_completions_url == "https://gateway.example.test/v1/chat/completions"
