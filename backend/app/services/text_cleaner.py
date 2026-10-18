"""
Global Text Cleaning: apply the user-configured rules from the
`text_cleaning_rules` table (managed on the Text Cleaning page) to a string.

For downloaded books this runs at download-save time; for translated books
the same rules are applied only at DOCX render time (see the
app/services/docx_exporter.py module docstring).
"""
import re
from app.database import get_database


class TextCleaner:
    """Applies user-configurable text cleaning rules from the database.

    Rules are re-read from the DB on every `clean()` call, so edits made on
    the settings page take effect immediately without a restart.
    """

    def __init__(self):
        """Grab the shared NovelDatabase singleton (no DB query happens yet)."""
        self.db = get_database()

    def clean(self, text: str) -> str:
        """Run every enabled rule over `text`, in `sort_order`.

        Args:
            text: input text; None or "" is allowed.

        Returns:
            The cleaned text ("" for empty input). Order matters: each rule
            sees the output of the previous one.

        Side effects: one SELECT on text_cleaning_rules per call.
        """
        if not text:
            return ""
        rules = self.db.get_text_cleaning_rules(enabled_only=True)
        for rule in rules:
            text = self._apply_rule(text, rule)
        return text

    # @staticmethod: the method needs no `self`, it is just a function that
    # lives inside the class for organisation. Callable as self._apply_rule(...).
    @staticmethod
    def _apply_rule(text: str, rule: dict) -> str:
        """Apply one rule to `text`.

        Args:
            text: input text.
            rule: a text_cleaning_rules row as a dict. Keys used:
                match_type ('regex' | 'simple'), rule_type ('remove' | 'replace'),
                find_text, replace_text, id (only for the error message).

        Returns:
            The transformed text. If the rule fails (e.g. an invalid regex
            typed by the user) the error is printed and `text` is returned
            unchanged, so one bad rule never breaks a download.
        """
        try:
            if rule['match_type'] == 'regex':
                # re.sub(pattern, replacement, text): replacement may use
                # back-references like \1 for captured groups.
                if rule['rule_type'] == 'remove':
                    text = re.sub(rule['find_text'], '', text)
                else:
                    text = re.sub(rule['find_text'], rule['replace_text'], text)
            else:
                # 'simple' = plain substring match, no regex meaning.
                if rule['rule_type'] == 'remove':
                    text = text.replace(rule['find_text'], '')
                else:
                    text = text.replace(rule['find_text'], rule['replace_text'])
        except Exception as e:
            # rule.get('id', '?') returns '?' if the key is missing instead of raising.
            print(f"⚠️ Text cleaning rule #{rule.get('id', '?')} failed: {e}")
        return text
