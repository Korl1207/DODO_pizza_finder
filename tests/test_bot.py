import unittest

from dodo_parser.bot import _extract_bot_mention_query, _extract_check_argument, _parse_command


class BotCommandTests(unittest.TestCase):
    def test_parse_command_supports_bot_mentions(self) -> None:
        command, argument = _parse_command("/check_pizza@dodo_test_bot \u041f\u0438\u0446\u0446\u0430")

        self.assertEqual(command, "/check_pizza")
        self.assertEqual(argument, "\u041f\u0438\u0446\u0446\u0430")

    def test_extract_check_argument_only_for_supported_commands(self) -> None:
        self.assertEqual(
            _extract_check_argument("/check_pizza \u041f\u0438\u0446\u0446\u0430 \u042d\u043d\u0447\u0430\u043d\u0442\u0438\u043a\u0441"),
            "\u041f\u0438\u0446\u0446\u0430 \u042d\u043d\u0447\u0430\u043d\u0442\u0438\u043a\u0441",
        )
        self.assertEqual(_extract_check_argument("/check"), "")

    def test_extract_check_argument_ignores_plain_text(self) -> None:
        self.assertIsNone(_extract_check_argument("\u041f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u0441\u0435\u0439\u0447\u0430\u0441"))
        self.assertIsNone(_extract_check_argument("\u043f\u0440\u0438\u0432\u0435\u0442"))
        self.assertIsNone(_extract_check_argument("/start"))

    def test_extract_bot_mention_query_returns_remaining_text(self) -> None:
        self.assertEqual(
            _extract_bot_mention_query("@dodo_test_bot где заказать", ["dodo_test_bot"]),
            "\u0433\u0434\u0435 \u0437\u0430\u043a\u0430\u0437\u0430\u0442\u044c",
        )

    def test_extract_bot_mention_query_ignores_other_mentions(self) -> None:
        self.assertIsNone(_extract_bot_mention_query("@another_bot где заказать", ["dodo_test_bot"]))

    def test_extract_bot_mention_query_accepts_any_known_username(self) -> None:
        self.assertEqual(
            _extract_bot_mention_query("@real_bot где заказать", ["wrong_bot", "real_bot"]),
            "\u0433\u0434\u0435 \u0437\u0430\u043a\u0430\u0437\u0430\u0442\u044c",
        )


if __name__ == "__main__":
    unittest.main()
