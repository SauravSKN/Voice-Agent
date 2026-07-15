from app.services.language_model import LanguageModelService


TEST_INPUTS = [
    "आप कौन हैं?",
    "भारत की राजधानी क्या है?",
    "मुझे एक छोटी प्रेरणादायक बात बताइए।",
    "मेरा नाम सौरव है।",
    "मेरा नाम क्या है?",
    "Mera order abhi tak deliver nahi hua.",
    "What can you do?",
]


def main() -> None:
    service = LanguageModelService()

    for user_input in TEST_INPUTS:
        result = service.generate(user_input)
        print(f"\nUser: {user_input}")
        print(f"Assistant: {result.response}")
        print(f"Generation time: {result.generation_time_ms} ms")


if __name__ == "__main__":
    main()
