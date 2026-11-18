"""Ground introductory tutorials in prerequisites from the current catalog."""
import re

from app.agent import ProposalValidationError
from app.conversation import normalized_words
from app.editor_safety import classify_editor_intent


def tutorial_topic(request) -> str | None:
    if request.editor_context is not None:
        return None
    text = normalized_words(request.messages[-1].content)
    learning_request = (
        classify_editor_intent(request.messages[-1].content) == 'informational'
        and re.search(r'\bcomo (?:puedo |se |podemos )?automatiz(?:ar|o)\b', text)
    )
    if learning_request and re.search(r'\b(?:clics?|clicks?)\b', text) and re.search(r'\bteclado\b', text):
        return 'mouseKeyboard'
    prefix = r'(?:me explicas |explicame )?como (?:puedo |se |podemos )?automatizar '
    suffix = r'(?: con autoclick)?'
    if re.fullmatch(r'(?:y )?como se (?:usan|utilizan) (?:los )?(?:bloques )?(?:de|en) (?:excel|exel)(?: solo explicame)?', text):
        return 'excel'
    if re.fullmatch(prefix + r'(?:tareas? (?:en|de|con) )?excel' + suffix, text):
        return 'excel'
    if re.fullmatch(prefix + r'(?:clics?|clicks?)(?: del mouse)? y (?:el )?teclado' + suffix, text):
        return 'mouseKeyboard'
    return None


def tutorial_instructions(request) -> str | None:
    topic = tutorial_topic(request)
    if topic is None:
        return None
    common = (
        '[GUIA_INICIAL]\nEl usuario pide aprender: responde con kind=answer y una guia '
        'de 3 a 5 pasos numerados, con un ejemplo breve y una pregunta sobre su tarea. '
        'No generes un bot ni afirmes haber ejecutado o guardado algo. Usa los nombres '
        'visibles y los requisitos del catalogo. No respondas solo con categorias.\n'
    )
    if topic == 'excel':
        detail = (
            'Explica Abrir libro: elegir un archivo real y una variable de salida para '
            'su referencia. Esa misma variable se usa en el campo Libro de Leer celda '
            'y Escribir celda; tambien se indica la hoja y celda. Da un ejemplo de '
            'lectura o escritura con una hoja y celda concretas (por ejemplo Hoja1 y A1). '
            'Leer celda requiere una variable de salida para el valor leido. '
            'Escribir celda solo pide Libro, Hoja, Celda y Valor: no tiene variable de salida. '
            'Si explicas escritura incluye Guardar libro. '
            'Muestra los datos de ejemplo como ejemplos, no como rutas reales del usuario.'
        )
    else:
        detail = (
            'Explica Click y sus coordenadas X/Y, Escribir texto y su texto, y Presionar '
            'tecla para una tecla o combinacion. Da un ejemplo de secuencia, indicando '
            'que la ventana destino debe estar enfocada y las coordenadas deben '
            'configurarse para el equipo. Una espera fija puede servir como pausa, '
            'pero no garantiza que una ventana o pagina ya haya cargado. '
            'El teclado no usa coordenadas: Escribir texto recibe el texto y Presionar '
            'tecla recibe la tecla. Las coordenadas X/Y corresponden al mouse. '
            'Si todavia no sabe esas coordenadas, puede dejarlas pendientes para '
            'configurarlas en el editor. No sugieras coordenadas temporales ni '
            'dejarlas en blanco para reemplazar un destino desconocido: un clic '
            'sin coordenadas usa la posicion actual. El asistente puede preparar '
            'un borrador que señale esos datos por completar; se revisan en el editor '
            'antes de ejecutar. Como alternativa, Detectar elemento busca '
            'texto visible y sus alias de coordenadas se usan solo en Click.'
        )
    return common + detail + '\n[/GUIA_INICIAL]'


def tutorial_catalog(request) -> list[dict]:
    """Only the documented actions needed by a self-contained introduction."""
    ids = ({'excel.open', 'excel.readCell', 'excel.writeCell', 'excel.save'}
           if tutorial_topic(request) == 'excel'
           else {'mouse.click', 'keyboard.write', 'keyboard.press', 'window.focus', 'execution.wait', 'vision.detectElement'})
    return [action.model_dump(mode='json', by_alias=True) for action in request.capabilities.actions if action.id in ids]


def validate_tutorial_answer(message: str, request) -> None:
    topic = tutorial_topic(request)
    if topic is None:
        return
    text = normalized_words(message)
    actions = {action.id: action for action in request.capabilities.actions}

    def mentions(action_id):
        action = actions.get(action_id)
        if action is None:
            return False
        return (re.search(r'\b' + re.escape(normalized_words(action.title)) + r'\b', text) is not None
                or action_id in message)

    missing = []
    if topic == 'excel':
        if 'excel.open' in actions and not mentions('excel.open'):
            missing.append('abrir primero el archivo con Abrir libro')
        if not (mentions('excel.readCell') or mentions('excel.writeCell')):
            missing.append('explicar Leer celda o Escribir celda')
        if not re.search(r'\b(?:variable|referencia)\b', text):
            missing.append('reutilizar la variable de referencia en el campo Libro')
        if not re.search(r'\bhoja\b', text):
            missing.append('indicar la hoja del libro, por ejemplo Hoja1')
        if not re.search(r'\b[a-z]{1,3}[1-9][0-9]*\b', text):
            missing.append('mostrar una celda concreta de ejemplo, como A1')
        if mentions('excel.writeCell') and 'excel.save' in actions and not mentions('excel.save'):
            missing.append('usar Guardar libro para conservar la escritura')
        write_output = re.search(r'\bescribir celda\b(?:(?!abrir libro|leer celda|guardar libro).){0,250}\bvariable de salida\b', text)
        if write_output and not re.search(r'\b(?:no|sin)\b', write_output.group()):
            missing.append('corregir Escribir celda: sus campos son Libro, Hoja, Celda y Valor; no tiene variable de salida')
    else:
        for action_id in ('mouse.click', 'keyboard.write', 'keyboard.press'):
            if action_id in actions and not mentions(action_id):
                missing.append('explicar ' + actions[action_id].title)
        if not re.search(r'\bcoordenadas\b', text) and not {'x', 'y'} <= set(text.split()):
            missing.append('configurar las coordenadas X/Y del clic para el equipo')
        if not re.search(r'\benfoc[a-z]*\b', text):
            missing.append('enfocar la ventana destino antes de escribir o presionar teclas')
    if missing:
        raise ProposalValidationError('introductory tutorial omits documented prerequisites', repair_details=[
            'Responde con una guia breve y concreta, sin crear un bot. Falta: ' + '; '.join(missing) + '.',
        ])
