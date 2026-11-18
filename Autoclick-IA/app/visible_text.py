"""Present catalog actions by their user-facing names in chat output."""
import re


def bot_parameter_literals(*bots) -> tuple[str, ...]:
    """Only existing parameter data, never metadata or model-authored answers."""
    found = set()

    def visit(value):
        if isinstance(value, str) and value:
            found.add(value)
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for bot in bots:
        if isinstance(bot, dict):
            for node in bot.get('flow', {}).get('nodes', []):
                visit(node.get('params', {}))
    return tuple(sorted(found))


def humanize_action_names(content: str, capabilities, literal_values=()) -> str:
    titles = {action.id: action.title for action in capabilities.actions}
    if not titles:
        return content
    alternatives = '|'.join(re.escape(action_id) for action_id in sorted(titles, key=len, reverse=True))
    literals = sorted({value for value in literal_values
                       if isinstance(value, str) and value and any(identity in value for identity in titles)},
                      key=lambda value: (-len(value), value))
    protected = '(?P<literal>`?(?:' + '|'.join(re.escape(value) for value in literals) + ')`?)|' if literals else ''
    pattern = re.compile(protected + r'(?<![A-Za-z0-9_./])`?(?P<action>' + alternatives + r')`?(?![A-Za-z0-9_/]|\.[A-Za-z0-9_])')
    return pattern.sub(lambda match: match.group(0) if match.groupdict().get('literal') is not None
                       else titles[match.group('action')], content)
