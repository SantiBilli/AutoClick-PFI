"""Validate explicit catalog examples and documented move behavior."""
import re
from app.conversation import normalized_words

_ITEM = r'''(?:"([^"\n]+)"|'([^'\n]+)'|\*\*([^*\n]+)\*\*|`([^`\n]+)`)'''
_PREFIX = re.compile(r'\bbloque\s+|\bbloques\s*\(?\s*(?:como|tales\s+como|por\s+ejemplo)\s+', re.I)
_SEPARATOR = re.compile(r'\s*(?:,\s*(?:y\s+|o\s+)?|(?:y|o)\s+)', re.I)


def validate_catalog_examples(message, capabilities, literal_values, error):
    prose = message
    for value in literal_values:
        if isinstance(value, str) and value:
            for delimiter in ('"', "'", '`', '**'):
                prose = prose.replace(delimiter + value + delimiter, '[dato literal]')
    allowed = {normalized_words(action.title) for action in capabilities.actions}
    allowed.update(normalized_words(action.id) for action in capabilities.actions)
    for prefix in _PREFIX.finditer(prose):
        preceding = normalized_words(re.split(r'[.!?;\n]', prose[:prefix.start()])[-1])
        if re.search(r'\bno\s+(?:existe|hay|tiene|ofrece|cuenta con)\b', preceding):
            continue
        position = prefix.end()
        while item := re.match(_ITEM, prose[position:]):
            title = next(group for group in item.groups() if group is not None)
            if normalized_words(title) not in allowed:
                raise error('answer names an unknown action in the current catalog', repair_details=[
                    f'El nombre {title!r} no figura como bloque en el catálogo actual. Corrige el ejemplo usando exclusivamente títulos verificados; una tarea o analogía no equivale a un bloque disponible.',
                    'Títulos verificados: ' + ', '.join(action.title for action in capabilities.actions),
                ])
            position += item.end()
            separator = _SEPARATOR.match(prose, position)
            if not separator:
                break
            position = separator.end()
    # Moving removes the source location; it does not create/leave an empty
    # folder there. Only reject this narrow affirmative contradiction, not a
    # discussion of existing files, negation or literal bot data.
    moves = [a for a in capabilities.actions if a.id == 'folder.move']
    for sentence in re.split(r'[.!?;\n]', prose):
        plain = normalized_words(sentence)
        if not any(normalized_words(a.title) in plain for a in moves):
            continue
        claim = re.search(r'\b(?:deja|dejandola|dejando|queda)\b.{0,65}\bvacia\b.{0,35}\borigen\b', plain)
        if claim and not re.search(r'\bno\s+(?:la\s+)?$', plain[max(0, claim.start()-15):claim.start()]):
            raise error('answer contradicts move semantics', repair_details=[
                'Mover carpeta traslada la carpeta y su contenido al destino. Tras un movimiento exitoso no queda la carpeta original vacía en la ruta de origen. Explica esa diferencia sin afirmar que se ejecutó nada.',
            ])
