import unittest

from dodo_parser.__main__ import parse_args


class MainArgsTests(unittest.TestCase):
    def test_parse_args_uses_optional_pizza_override(self) -> None:
        args = parse_args(["--config", "config.json", "--pizza-name", "Пепперони"])

        self.assertEqual(args.config, "config.json")
        self.assertEqual(args.pizza_name, "Пепперони")

    def test_parse_args_keeps_pizza_override_empty_by_default(self) -> None:
        args = parse_args(["--config", "config.json"])

        self.assertIsNone(args.pizza_name)


if __name__ == "__main__":
    unittest.main()
