import unicodedata
import re
from typing import Literal

MAX_POLICY_CODE_POINTS = 64_000
EditorIntent = Literal["informational", "mutation", "ambiguous"]

_EDIT_EN = frozenset(
    """
    add apply browse change click configure connect create delete download enter
    execute extract make modify move navigate open order press put read remove
    rename reorder replace restore revert save search set type undo update visit write
    """.split()
)
_EDIT_ES = frozenset(
    """
    abre abri abrir abran abras abres actualiza actualizar actualice actualicen actualices
    agrega agregar agregas agregue agreguen agregues anada anadan anadas anade
    anades anadi anadir aplica aplicar aplique apliquen apliques borra borrar
    borre borren borres busca buscar buscas busque busquen cambia cambiar
    cambie cambien cambies clica clickea clickear configura configurar configure
    configuren configures conecta conectar conecte conecten conectes crea crear armar inventar
    cree creen crees descarga descargar descargue descarguen descarregues ejecuta
    ejecutar ejecute ejecuten ejecutes elimina eliminar elimine eliminen elimines
    entra entrar entras entre entren entres escribe escribir escriba escriban escribas
    establece establecer establezca establezcan
    establezcas extrae extraer extraiga extraigan extraigas guarda guardar guarde
    guarden guardes hace hacer haga hagan hagas haz ingresa ingresar ingrese ingresen
    ingreses lee leer lea lean leas modifica modificar modifique modifiquen modifiques
    move mover mueva muevan muevas mueve navega navegar navegue naveguen navegues
    ordena ordenar ordene ordenen ordenes pon pone poner ponga pongan pongas
    presiona presionar presione presionen presiones quita quitar quite quiten
    quites reemplaza reemplazar reemplace reemplacen reemplaces renombra
    renombrar renombre renombren renombres reordena reordenar reordene reordenen
    reordenes tipea tipear tipeee tipeen tipeees visita visitar visite visiten visites
    permiti permite permitir permitas permita permitan habilita habilitar habilite
    habiliten activa activar active activen desactiva desactivar desactive desactiven
    sobrescribi sobrescribe sobrescribir sobrescriba sobrescriban autoriza autorizar usa usar use usen uses completa completar complete completen propon propone proponer
    prepara preparar prepare preparen prepares copia copiar copie copien copies
    volver vuelve volve deshacer deshace deshaga deshagan deshagas
    revertir reverti revierte revierta reviertan reviertas
    restaurar restaura restaure restauren restaures
    """.split()
)
_EDIT_WORDS = _EDIT_EN | _EDIT_ES
_SPANISH_EDIT_INFINITIVES = frozenset(word for word in _EDIT_ES if word.endswith(('ar', 'er', 'ir')))
_SPANISH_POLITE_FORMS = frozenset({'haces', 'pones', 'mueves'}) | frozenset(
    infinitive[:-2] + ending
    for infinitive in _SPANISH_EDIT_INFINITIVES
    for ending in (('as',) if infinitive.endswith('ar') else ('es', 'is') if infinitive.endswith('ir') else ('es',))
)
_CREATIVE_AUTHORIZATIONS = frozenset({"dale"})
_SPANISH_ENCLITICS = ("las", "les", "los", "nos", "la", "le", "lo", "me", "se", "te")
_INFORMATIONAL_SOCIAL_WORDS = frozenset(
    "buenas gracias hello hola saludo saludos thanks".split()
)
_INFO_WORDS = frozenset(
    """
    como describe describi descripcion describir example explain explanation explica
    explicame explicar frase how informacion information meaning palabra phrase
    significado significa term termino what why word diferencia diferencias comparacion difference comparison cuanto cuanta cuantos cuantas
    """.split()
)
_WEAK_CONNECTORS = frozenset({"and", "y"})
_STRONG_CONNECTORS = frozenset(
    {"ademas", "also", "but", "despues", "luego", "pero", "tambien", "then"}
)
_EXPLANATORY_LOCAL_WORDS = frozenset(
    "es informal mean meaning means palabra significa significan termino term word".split()
)
_EXPLANATORY_LIST_WORDS = frozenset(
    "palabra palabras term terms termino terminos word words".split()
)
_MEANING_PREDICATES = frozenset("mean means significa significan".split())
_REQUEST_MARKERS = frozenset({"favor", "please"})
_DESCRIPTIVE_SUBJECTS = frozenset(
    "app aplicacion autoclick block blocks bloque bloques bot editor flow flujo service servicio system sistema".split()
)
_DESIRE_WORDS = frozenset("deseo need necesito quiero want".split())
_DESIRE_INFO_WORDS = frozenset(
    "conocer entender explanation explicacion informacion information know learn saber understand".split()
)
_INFORMATION_QUESTION_HEADS = frozenset(
    """
    al are cual cuales cuanto cuanta cuantos cuantas did do does donde es esta estan had has have how is por que
    quien quienes was were what when where which who why como cuando
    """.split()
)
_MODAL_QUESTION_HEADS = frozenset("can could may might should will would".split())
_COMPLETION_QUESTION_HEADS = _INFORMATION_QUESTION_HEADS | frozenset(
    "can could may might should will would podria podrian puede pueden".split()
)

_COMPLETED_EN = frozenset(
    """
    added applied changed complete completed configured connected created deleted
    done executed finished made modified moved ordered put ready removed renamed
    reordered replaced saved set updated
    """.split()
)
_COMPLETED_ES = frozenset(
    f"{stem}{ending}"
    for stem in "agregad aplicad actualizad ajustad borrad cambiad completad configurad conectad corregid cread construid ejecutad eliminad establecid generad guardad hech list modificad movid quitad realizad reemplazad renombrad reordenad terminad".split()
    for ending in ("o", "a", "os", "as")
) | frozenset("anadido anadida anadidos anadidas".split())
_ACTIVE_ES_RAW = frozenset(
    """
    agregué añadí apliqué actualicé borré cambié completé configuré conecté creé
    ejecuté eliminé establecí guardé hice modifiqué moví quité realicé reemplacé
    renombré reordené terminé ajusté corregí generé construí
    """.split()
)
_ACTIVE_ES_PLAIN = frozenset(
    """
    agregue anadi aplique actualice borre cambie complete configure conecte cree
    ejecute elimine estableci guarde hice modifique movi quite realice reemplace
    renombre reordene termine ajuste corregi genere construi
    """.split()
)
_ACTIVE_PLURAL_ES = frozenset(
    """
    agregamos anadimos aplicamos actualizamos borramos cambiamos completamos
    configuramos conectamos creamos ejecutamos eliminamos establecimos guardamos
    hicimos modificamos movimos quitamos realizamos reemplazamos renombramos
    reordenamos terminamos
    """.split()
)
_REFLEXIVE_PAST_ES = frozenset(
    """
    agrego anadio aplico actualizo borro cambio completo configuro conecto creo
    ejecuto elimino establecio guardo hizo modifico movio quito realizo reemplazo
    renombro reordeno termino
    """.split()
)
_INFINITIVE_ES = frozenset(
    """
    agregar anadir aplicar actualizar borrar cambiar completar configurar
    conectar crear ejecutar eliminar establecer guardar hacer modificar mover
    quitar realizar reemplazar renombrar reordenar terminar
    """.split()
)
_HYPOTHETICALS = frozenset("if si unless".split())
_GENERIC_TEMPORALS = frozenset("cuando when".split())
_MODALS = frozenset(
    "can could debe deben may might must podria podrian puede pueden should will would".split()
)
_NEGATIONS = frozenset(
    "cannot cant haven never no not nunca sin todavia".split()
)
_NEGATION_CONTRACTION_STEMS = frozenset(
    "aren can couldn didn doesn don hadn hasn isn mustn shouldn wasn weren won wouldn".split()
)
_ADVERBS = frozenset(
    "already correctamente exitosamente finally fully just now recien successfully ya".split()
)
_REDUCED_SUBJECTS = frozenset(
    """
    accion acciones action actions automation automations automatizacion
    automatizaciones block blocks bloque bloques bot bots cambio cambios change
    changes flow flows flujo flujos proposal proposals propuesta propuestas
    status update updates actualizacion actualizaciones
    """.split()
)
_EXPLANATION_LIMITERS = frozenset("only solo solamente".split())
_EXPLANATION_TEMPORALS = frozenset(
    "after antes before cuando despues tras when".split()
)
_STATUS_AUXILIARIES = frozenset(
    """
    am are been esta estan fue fueron ha had han has have he hemos is queda
    quedan quedo quedaron s sido was were
    """.split()
)
_QUOTE_END = {'"': '"', "'": "'", "`": "`", "«": "»", "“": "”", "‘": "’"}
_QUESTION_PREFIXES = frozenset("claro favor ok okay please por sure".split())
_TAG_QUESTION_WORDS = frozenset(
    "cierto correct correcto right verdad yes".split()
)
_TAG_QUESTION_PRONOUNS = frozenset("he i it she they we you".split())
_TAG_QUESTION_AUXILIARIES = frozenset(
    "am are can could did didn do does don had has have is isn may might should was wasn were weren will won would wouldn".split()
)


def _plain(word: str) -> str:
    decomposed = unicodedata.normalize("NFKD", word.casefold())
    return "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )


def _spanish_imperative(word: str) -> bool:
    for infinitive in _EDIT_ES:
        if not infinitive.endswith("r"):
            continue
        imperative = infinitive[:-1]
        if word == imperative:
            return True
        if not word.startswith(imperative):
            continue
        remainder = word[len(imperative) :]
        for _ in range(2):
            enclitic = next(
                (item for item in _SPANISH_ENCLITICS if remainder.startswith(item)),
                None,
            )
            if enclitic is None:
                break
            remainder = remainder[len(enclitic) :]
            if not remainder:
                return True
    return False


def _mutation_verb(word: str) -> bool:
    return (
        word in _EDIT_WORDS
        or word in _CREATIVE_AUTHORIZATIONS
        or _spanish_imperative(word)
    )


def _spanish_voseo_present(raw_word: str) -> bool:
    endings = {"ás": "ar", "és": "er", "ís": "ir"}
    return any(
        raw_word.endswith(ending)
        and _plain(f"{raw_word[:-2]}{infinitive_ending}") in _EDIT_ES
        for ending, infinitive_ending in endings.items()
    )


def _single_typo(word: str, expected: str) -> bool:
    """One insertion, deletion, substitution or adjacent transposition."""
    if abs(len(word) - len(expected)) > 1:
        return False
    if len(word) == len(expected):
        differences = [index for index, pair in enumerate(zip(word, expected)) if pair[0] != pair[1]]
        if len(differences) == 1:
            return True
        return (len(differences) == 2
                and differences[1] == differences[0] + 1
                and word[differences[0]] == expected[differences[1]]
                and word[differences[1]] == expected[differences[0]])
    shorter, longer = (word, expected) if len(word) < len(expected) else (expected, word)
    index = next((index for index, pair in enumerate(zip(shorter, longer)) if pair[0] != pair[1]), len(shorter))
    return shorter[index:] == longer[index + 1:]


def _spanish_polite_edit(words: tuple[str, ...], index: int, transitions: tuple[int, ...]) -> bool:
    """Recognize addressed edits, including one typo in a nontrivial verb.

    Keep this local to an addressed request; globally treating present-tense
    verbs as commands would turn descriptions and hypotheticals into edits.
    Only intent recognition is tolerant: original messages and parameter values
    are never rewritten. Negation and explanatory scope still apply as usual.
    """
    address = index - 1
    modal = address >= 0 and words[address] in {'podes', 'puedes', 'podrias', 'pueden', 'podrian'}
    if modal:
        address -= 1
    if address < 0 or words[address] not in {'me', 'nos'}:
        return False
    start, _ = _clause_bounds(words, index, transitions)
    if any(word in _HYPOTHETICALS | _GENERIC_TEMPORALS for word in words[start:index]):
        return False
    word = words[index]
    # A valid informational verb wins over a nearby edit spelling:
    # "describis" is one deletion away from "escribis".
    if word in _INFO_WORDS or word.removesuffix('s') in _INFO_WORDS:
        return False
    candidates = _SPANISH_EDIT_INFINITIVES if modal else _SPANISH_POLITE_FORMS
    if word in candidates:
        return True
    return len(word) >= 6 and any(len(candidate) >= 6 and _single_typo(word, candidate) for candidate in candidates)


def _parameter_transfer_edit(words: tuple[str, ...], index: int, transitions: tuple[int, ...]) -> bool:
    """'Pasar la espera a 10' edits a value; 'pasame la lista' asks for information.

    Keep the overloaded verb out of the general command vocabulary. The caller
    applies the same negation, quotation and explanatory checks as other edits.
    """
    if words[index] not in {'pasar', 'pasa', 'pasame', 'pasala', 'pasalo', 'pasas', 'pase', 'pasen', 'pases'}:
        return False
    _, end = _clause_bounds(words, index, transitions)
    target = words[index + 1:end]
    parameters = {'espera', 'demora', 'pausa', 'duracion', 'milisegundos', 'segundos',
                  'limite', 'inicio', 'fin', 'paso', 'intervalo', 'rango'}
    numbers = {'un', 'una', 'uno', 'dos', 'tres', 'cuatro', 'cinco', 'seis', 'siete',
               'ocho', 'nueve', 'diez', 'once', 'doce', 'quince', 'veinte', 'treinta', 'cien'}
    return bool(parameters.intersection(target)) and any(
        word == 'a' and (value.isdecimal() or value in numbers)
        for word, value in zip(target, target[1:])
    )


def _is_negation(word: str) -> bool:
    return word in _NEGATIONS or word.endswith(("n't", "n’t"))


def _contains_negation(words: tuple[str, ...], start: int, end: int) -> bool:
    return any(
        _is_negation(word)
        or (
            word in _NEGATION_CONTRACTION_STEMS
            and words[index + 1 : index + 2] == ("t",)
        )
        for index, word in enumerate(words[start:end], start=start)
    )


def _predicate_is_negated(
    words: tuple[str, ...], index: int, transitions: tuple[int, ...]
) -> bool:
    start, _ = _clause_bounds(words, index, transitions)
    return any(
        (_is_negation(word) or _contains_negation(words, negation, negation + 1))
        and words[negation + 1 : negation + 2] not in (("only",), ("solo",))
        for negation, word in enumerate(words[start:index], start=start)
    )


def _segments(
    content: str, *, ignore_quotes: bool
) -> list[tuple[tuple[str, ...], tuple[int, ...], tuple[int, ...], int | None, bool]]:
    segments: list[
        tuple[tuple[str, ...], tuple[int, ...], tuple[int, ...], int | None, bool]
    ] = []
    words: list[str] = []
    commas: list[int] = []
    transitions: list[int] = []
    word: list[str] = []
    quote_end: str | None = None
    question_open: int | None = None
    question_close = False

    def finish_word() -> None:
        if word:
            words.append(unicodedata.normalize("NFC", "".join(word).casefold()))
            word.clear()

    def finish_segment() -> None:
        nonlocal question_close, question_open
        finish_word()
        if words:
            segments.append(
                (
                    tuple(words),
                    tuple(commas),
                    tuple(transitions),
                    question_open,
                    question_close,
                )
            )
            words.clear()
            commas.clear()
            transitions.clear()
        question_open = None
        question_close = False

    for index, character in enumerate(content):
        if quote_end is not None:
            if character == quote_end:
                quote_end = None
            continue
        if ignore_quotes and character in _QUOTE_END:
            within_word = (
                character in {"'", "’"}
                and index > 0
                and index + 1 < len(content)
                and content[index - 1].isalnum()
                and content[index + 1].isalnum()
            )
            if not within_word:
                finish_word()
                quote_end = _QUOTE_END[character]
                continue
        if character.isalnum():
            word.append(character)
            continue
        finish_word()
        if character == "¿" and question_open is None:
            question_open = len(words)
        elif character == "?":
            question_close = True
        elif character == ",":
            commas.append(len(words))
            transitions.append(len(words))
        elif character in {":", "-", "/"}:
            transitions.append(len(words))
        if character in ".!?;\n\r":
            finish_segment()
    finish_segment()
    return segments


def _information_marker(
    raw_words: tuple[str, ...], words: tuple[str, ...], index: int
) -> bool:
    following = words[index : index + 3]
    return (
        words[index] in _INFO_WORDS
        or raw_words[index] in {"qué", "cuál"}
        or following[:2] in (("for", "example"), ("por", "ejemplo"))
        or following[:2] in (("que", "hace"), ("what", "does"))
        or following[:3] == ("para", "que", "sirve")
    )


def _descriptive_edit(
    words: tuple[str, ...], index: int, transitions: tuple[int, ...]
) -> bool:
    start, _ = _clause_bounds(words, index, transitions)
    prefix = words[max(start, index - 4) : index]
    for subject_index, word in enumerate(prefix):
        if word == "you" and any(
            following in _MODALS for following in prefix[subject_index + 1 :]
        ):
            return True
        if word in {"i", "we"} and any(
            preceding in _MODALS for preceding in prefix[:subject_index]
        ):
            return True
    if any(word in {"puedo", "podemos"} for word in prefix):
        return True
    # An adverb such as "tambien" can separate a block subject from its
    # predicate without turning that predicate into an instruction. Keep
    # explicit later clauses and requests ("pero", "por favor") independent.
    subject = words[1] if words[:1] and words[0] in {'el', 'la', 'los', 'las', 'un', 'una', 'ese', 'esa', 'this', 'the'} and len(words) > 1 else words[0] if words else None
    if (subject in _DESCRIPTIVE_SUBJECTS
            and words[index] in _EDIT_WORDS
            and not any(word in _REQUEST_MARKERS for word in words[:index])
            and not any(word in _STRONG_CONNECTORS - {'tambien', 'also'} for word in words[:index])):
        return True
    return any(word in _DESCRIPTIVE_SUBJECTS for word in prefix) and not any(
        word in _REQUEST_MARKERS for word in prefix
    )


def _question_head(words: tuple[str, ...]) -> str | None:
    for word in words:
        if word not in _QUESTION_PREFIXES:
            return word
    return None


def _informational_question(
    words: tuple[str, ...], question_open: int | None, question_close: bool
) -> bool:
    if (question_open is None and not question_close) or not words:
        return False
    head = _question_head(words)
    if head in _INFORMATION_QUESTION_HEADS:
        return True
    if head in _DESCRIPTIVE_SUBJECTS:
        return True
    # An infinitive at the head names an operation ("¿Copiar archivo borra
    # el original?"). Imperatives in a later segment still take precedence.
    if head and head.endswith(('ar', 'er', 'ir')):
        return True
    if head in {'el', 'la', 'los', 'las'} and any(word in {'es', 'son', 'sirve', 'sirven'} for word in words):
        return True
    if head == 'me' and words[1:2] in {('sirve',), ('serviria',)}:
        return True
    if any(words[i:i + 2] in {('se', 'puede'), ('se', 'pueden')} for i in range(len(words) - 1)):
        return True
    if head in {'en', 'con', 'de', 'a', 'sobre'}:
        index = words.index(head)
        if words[index + 1:index + 2] and words[index + 1] in {'que', 'cual', 'cuales', 'donde'}:
            return True
    if head not in _MODAL_QUESTION_HEADS:
        return False
    head_index = words.index(head)
    return words[head_index + 1 : head_index + 2] != ("you",)


def _weak_connector_starts_clause(
    words: tuple[str, ...], index: int, transitions: tuple[int, ...]
) -> bool:
    if index in transitions or index == 0 or not _mutation_verb(words[index - 1]):
        return True
    scope_start = max(
        [0]
        + [boundary for boundary in transitions if boundary < index]
        + [
            boundary + 1
            for boundary, word in enumerate(words[:index])
            if word in _STRONG_CONNECTORS
        ]
    )
    return not _contains_negation(words, scope_start, index)


def _clause_bounds(
    words: tuple[str, ...], index: int, transitions: tuple[int, ...]
) -> tuple[int, int]:
    boundaries = set(transitions)
    for connector, word in enumerate(words):
        if word in _STRONG_CONNECTORS or (
            word in _WEAK_CONNECTORS
            and _weak_connector_starts_clause(words, connector, transitions)
        ):
            boundaries.update((connector, connector + 1))
    start = max((boundary for boundary in boundaries if boundary <= index), default=0)
    end = min(
        (boundary for boundary in boundaries if boundary > index),
        default=len(words),
    )
    return start, end


def _is_bare_explanatory_term(
    words: tuple[str, ...], index: int, start: int, end: int
) -> bool:
    local = tuple(
        word
        for word in words[start:end]
        if word not in _WEAK_CONNECTORS and word not in _STRONG_CONNECTORS
    )
    return len(local) == 1 and local[0] == words[index]


def _metalinguistic_terms(
    raw_words: tuple[str, ...],
    words: tuple[str, ...],
    transitions: tuple[int, ...],
) -> frozenset[int]:
    terms: set[int] = set()

    def is_term(index: int) -> bool:
        return _mutation_verb(words[index]) or _spanish_voseo_present(
            raw_words[index]
        )

    def add_term_list(start: int, end: int) -> None:
        indexes = [index for index in range(start, end) if is_term(index)]
        if not indexes:
            return
        if all(
            is_term(index) or words[index] in _WEAK_CONNECTORS
            for index in range(start, end)
        ):
            terms.update(indexes)

    strong_boundaries = [
        index for index, word in enumerate(words) if word in _STRONG_CONNECTORS
    ]
    for frame in range(len(words)):
        if words[frame] not in _EXPLANATORY_LIST_WORDS | _MEANING_PREDICATES:
            continue

        hard_boundaries = strong_boundaries + [
            index
            for index, word in enumerate(words)
            if word in _WEAK_CONNECTORS
            and index in transitions
            and not any(
                is_term(candidate) for candidate in range(frame + 1, index)
            )
        ]

        hard_start = max(
            (boundary + 1 for boundary in strong_boundaries if boundary < frame),
            default=0,
        )
        hard_end = min(
            (boundary for boundary in hard_boundaries if boundary > frame),
            default=len(words),
        )

        # Prefix frames cover lists such as "significa guardar y cambiar" and
        # "these words: save, add and change".
        add_term_list(frame + 1, hard_end)

        if words[frame] not in _MEANING_PREDICATES:
            continue
        markers = [
            marker
            for marker in range(hard_start, frame)
            if _information_marker(raw_words, words, marker)
        ]
        if markers:
            # Suffix predicates cover "what save and change mean".
            add_term_list(markers[-1] + 1, frame)

    return frozenset(terms)


def _predicate_is_explanatory(
    raw_words: tuple[str, ...],
    words: tuple[str, ...],
    index: int,
    transitions: tuple[int, ...],
    question_open: int | None,
    question_close: bool,
    metalinguistic_terms: frozenset[int],
) -> bool:
    start, end = _clause_bounds(words, index, transitions)
    # Questions about what the user must configure name actions; they do not
    # order the assistant to do them. A later imperative still starts an edit.
    if (question_open is not None or question_close) and words[index].endswith('r'):
        prefix = words[start:index]
        if 'debo' in prefix or any(prefix[i:i + 2] == ('tengo', 'que') for i in range(len(prefix) - 1)):
            return True
        # A passive capability question scopes coordinated infinitives too,
        # such as "la propuesta se puede revisar y cambiar".
        if any(words[i:i + 2] in {('se', 'puede'), ('se', 'pueden')} for i in range(index - 1)):
            return True
        head = _question_head(words)
        if (head and head.endswith(('ar', 'er', 'ir'))
                and not any(word in _STRONG_CONNECTORS for word in words[:index])):
            return True
        if head in _DESCRIPTIVE_SUBJECTS and not any(word in _STRONG_CONNECTORS for word in words[:index]):
            return True
    # Infinitives in comparisons name operations; they do not request execution.
    # A later imperative or a strong connector still starts a mutation clause.
    comparison_frames = [i for i, word in enumerate(words[:index]) if word in {'entre', 'between'}]
    if comparison_frames and words[index].endswith('r'):
        frame = comparison_frames[-1]
        if any(word in {'diferencia', 'diferencias', 'comparacion', 'difference', 'comparison'} for word in words[:frame]) and not any(word in _STRONG_CONNECTORS for word in words[frame:index]):
            return True
    if any(
        _information_marker(raw_words, words, marker)
        for marker in range(start, index + 1)
    ):
        return True
    if start == 0 and _informational_question(
        words, question_open, question_close
    ):
        return True
    if (
        words[:2] in {("for", "example"), ("por", "ejemplo")}
        and start <= (transitions[0] if transitions else 0)
    ):
        return True

    # In "what X and Y mean", the closing explanatory predicate scopes both
    # coordinated terms even though the conjunction creates a clause candidate.
    if any(word in _EXPLANATORY_LOCAL_WORDS for word in words[index + 1 : end]):
        return True
    return index in metalinguistic_terms and _is_bare_explanatory_term(
        words, index, start, end
    )


def _segment_intent(
    raw_words: tuple[str, ...],
    transitions: tuple[int, ...],
    question_open: int | None,
    question_close: bool,
) -> EditorIntent:
    words = tuple(_plain(word) for word in raw_words)
    informational = _informational_question(words, question_open, question_close)
    informational |= any(
        _information_marker(raw_words, words, index) for index in range(len(words))
    )
    metalinguistic_terms = _metalinguistic_terms(raw_words, words, transitions)
    interrogative = question_open is not None or question_close
    informational |= interrogative and ('debo' in words or any(
        words[i:i + 2] == ('tengo', 'que') for i in range(len(words) - 1)))
    negated_mutation = False

    for index, word in enumerate(words):
        if raw_words[index] in _ACTIVE_ES_RAW:
            continue
        if not (
            _mutation_verb(word)
            or (interrogative and _spanish_voseo_present(raw_words[index]))
            or _spanish_polite_edit(words, index, transitions)
            or _parameter_transfer_edit(words, index, transitions)
        ):
            continue
        if _descriptive_edit(words, index, transitions):
            continue
        if word in {"cree", "creo"} and words[index + 1 : index + 2] == ("que",):
            continue
        if _predicate_is_negated(words, index, transitions):
            negated_mutation = True
            continue
        if not _predicate_is_explanatory(
            raw_words,
            words,
            index,
            transitions,
            question_open,
            question_close,
            metalinguistic_terms,
        ):
            return "mutation"

    desire_indexes = [
        index for index, word in enumerate(words) if word in _DESIRE_WORDS
    ]
    desire = any(
        not _predicate_is_negated(words, index, transitions)
        for index in desire_indexes
    )
    negated_desire = bool(desire_indexes) and not desire
    desire_info = any(word in _DESIRE_INFO_WORDS for word in words)
    if desire and not desire_info and not informational:
        return "mutation"
    # An explicit question can begin with any subject ("una pausa", "el
    # editor", "puedo"). Mutation predicates above still take precedence,
    # including polite requests such as "¿podés cambiar la espera?".
    informational |= interrogative or negated_mutation or negated_desire
    return "informational" if informational else "ambiguous"


def explicitly_preserves_bot(content: str) -> bool:
    """Explicit constraints on the bot, not restrictions on extra steps."""
    normalized = _plain(content[:MAX_POLICY_CODE_POINTS])
    # Do not interpret a quoted example as the user's instruction.
    normalized = re.sub(r'"[^"\n]*"|`[^`\n]*`|«[^»\n]*»', '', normalized)
    # "Sin cambiar el bot, agregá una espera" still contains an explicit
    # affirmative request in a later clause.
    for clause in re.finditer(r'[,;:.]\s*(?:(?:pero|luego|despues|y)\s+)?([a-z]+)', normalized):
        if _mutation_verb(clause.group(1)):
            return False
    return bool(re.search(
        r'\b(?:sin\s+(?:cambios|cambiarlo|modificarlo|cambiar\s+(?:nada|el\s+bot)|modificar\s+(?:nada|el\s+bot))'
        r'|no\s+(?:hagas\s+(?:mas\s+)?cambios|(?:cambies|modifiques)\s+nada(?!\s+mas\b))'
        r'|no\s+(?:lo|la)\s+(?:cambies|modifiques|edites)\b'
        r'|no\s+(?:lo\s+)?(?:armes|crees|generes|construyas)(?:\s+el\s+bot)?\s*(?:todavia|aun)?\b)',
        normalized,
    ))


def is_execution_status_question(content: str) -> bool:
    # Questions about whether a prepared bot has already acted, or whether it
    # acts automatically, must not open a flow-edit contract. A following
    # explicit imperative still takes precedence.
    status_question = _plain(content)
    after_question = status_question.rsplit('?', 1)[-1]
    following_command = re.search(
        r'\b(?:hace|hacelo|escribi|escribe|presiona|pulsa|clickea|ejecuta|ejecutalo|'
        r'guarda|descarga|copia|move|mueve|crea|agrega|cambia|modifica)\b',
        after_question,
    )
    asks_about_running = (
        re.search(r'\bya\b|\bse\s+\w+\s+solo\b', status_question)
        or re.search(r'\b(?:tengo|tendre)\s+que\s+(?:ejecut\w*|corr\w*|iniciar|probar|copiar|guardar|aplicar)\b', status_question)
    )
    return bool(
        '?' in content
        and asks_about_running
        and re.search(r'\b(?:bot|clic|click|tecla|ejecut\w*|corr\w*|copi\w*|toc\w*|guard\w*|aplic\w*|presion\w*|escrib\w*|descarg\w*|movio|moviste)\b', status_question)
        and not following_command
        and not re.search(r'\b(?:cambia|cambiar|agrega|agregar|modifica|modificar|borra|borrar|crea|crear|armame|creame|haceme)\b', status_question)
    )


def is_pending_status_question(content: str) -> bool:
    """Recognize questions about missing inputs without swallowing edit requests."""
    plain = _plain(content)
    return bool(
        '?' in content
        and re.search(
            r'\b(?:qu[eé]\s+(?:me\s+)?falta|qu[eé]\s+(?:datos?\s+)?qued[ao]n?\s+pendientes?'
            r'|quedan?\s+(?:(?:algun|alguna|algunos|algunas)\s+)?(?:datos?|parametros?)?\s*pendientes?'
            r'|quedan?\s+(?:(?:algun|alguna|algunos|algunas)\s+)?(?:datos?|parametros?)\s+(?:obligatorios?\s+)?por\s+completar'
            r'|qu[eé]\s+(?:datos?\s+)?(?:debo|tengo\s+que)\s+completar'
            r'|(?:est[aá]|qued[oó])\s+(?:ya\s+)?listo\s+para\s+(?:ejecutar|probar))\b',
            plain,
        )
        and not re.search(r'\b(?:cambia|cambiar|agrega|agregar|modifica|modificar|borra|borrar|crea|crear|armame|creame|haceme)\b', plain)
    )


def classify_editor_intent(content: str) -> EditorIntent:
    # An explicit answer-only sentence takes precedence over verbs in the
    # described hypothetical bot. Quoted text is data, not an intent override.
    for words, _, _, _, _ in _segments(content[:MAX_POLICY_CODE_POINTS], ignore_quotes=True):
        segment = ' '.join(_plain(word) for word in words)
        if (re.search(r'\b(?:preguntame|consultame|pedime)\b.{0,120}\bantes de\s+(?:crear|armar|hacer|modificar|editar|borrar)\b', segment)
                and not re.search(r'\b(?:no|nunca|sin)\b.{0,40}\b(?:preguntame|consultame|pedime)\b', segment)):
            return 'informational'
    if any(re.fullmatch(r'(?:solo|solamente) (?:responde|respondeme|contesta|contestame|explica|explicame|describi|describe)(?: (?:el|este) (?:proyecto|funcionamiento|alcance)(?: actual)?)?',
                       ' '.join(_plain(word) for word in words))
           for words, _, _, _, _ in _segments(content[:MAX_POLICY_CODE_POINTS], ignore_quotes=True)):
        return 'informational'
    if is_execution_status_question(content) or is_pending_status_question(content):
        return 'informational'
    if explicitly_preserves_bot(content):
        return "informational"
    if '?' not in content and re.match(r'^\s*mejor\s+(?:\d+|un[ao]?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\b', _plain(content)):
        return 'mutation'
    normalized = unicodedata.normalize("NFC", content)
    bounded = normalized[:MAX_POLICY_CODE_POINTS]
    segments = _segments(bounded, ignore_quotes=True)
    intents = [
        _segment_intent(raw_words, transitions, question_open, question_close)
        for raw_words, _, transitions, question_open, question_close in segments
    ]
    if "mutation" in intents:
        return "mutation"
    # A question may be followed by descriptive context ("Yo no indiqué uno").
    # Ambiguous declarative context does not turn that question into an edit;
    # an explicit mutation in any segment still takes precedence above.
    if intents and (all(intent == 'informational' for intent in intents)
            or intents[0] == 'informational' and (segments[0][3] is not None or segments[0][4])):
        return "informational"
    if segments and all(
        all(_plain(word) in _INFORMATIONAL_SOCIAL_WORDS for word in raw_words)
        for raw_words, _, _, _, _ in segments
    ):
        return "informational"
    return "ambiguous"


def latest_turn_requests_mutation(content: str) -> bool:
    return classify_editor_intent(content) == "mutation"


def ambiguous_initial_wait_edit(request) -> bool:
    """A first-turn singular wait has no referent if several waits exist.

    Follow-ups retain model interpretation of conversation references. This
    narrow check never guesses a target or rewrites an operation.
    """
    context = request.editor_context
    if context is None or len(request.messages) != 1:
        return False
    bot = context.working_bot if context.working_bot is not None else context.bot
    waits = [node['id'] for node in bot.get('flow', {}).get('nodes', []) if node.get('type') == 'execution.wait']
    if len(waits) < 2 or context.selected_block_id in waits:
        return False
    message = _plain(request.messages[-1].content).strip(' .!¿?')
    return re.fullmatch(
        r'(?:por favor[, ]+)?(?:cambia|cambiame|modifica|ajusta|pone|pon)\s+(?:(?:solo|solamente)\s+)?la espera\s+a\s+\d+(?:[.,]\d+)?\s*(?:segundos?|milisegundos?|ms|s)',
        message,
    ) is not None


def _conditional_prefix(
    raw_words: tuple[str, ...], words: tuple[str, ...], commas: tuple[int, ...]
) -> tuple[int, ...]:
    prefix: list[int] = []
    condition = 0
    comma_indexes = set(commas)
    for index, (raw_word, word) in enumerate(
        zip(raw_words, words, strict=True)
    ):
        if index in comma_indexes:
            condition = 0
        prefix.append(condition)
        if word in _HYPOTHETICALS and not (word == "si" and raw_word != "si"):
            condition = 1
        elif not condition and word in _GENERIC_TEMPORALS:
            condition = 2
    return tuple(prefix)


def _hypothetical(
    words: tuple[str, ...],
    conditional: tuple[int, ...],
    start: int,
    end: int,
    *,
    generic_temporal: bool,
) -> bool:
    condition = conditional[start]
    return condition == 1 or (generic_temporal and condition == 2) or any(
        word in _MODALS or word in _NEGATIONS
        for word in words[max(0, start - 8) : end]
    )


def _has_explanatory_suffix(words: tuple[str, ...], claim_index: int) -> bool:
    if words[claim_index] in {'configurado', 'configurada', 'configurados', 'configuradas'}:
        purpose = words[claim_index + 1:claim_index + 26]
        if purpose[:1] == ('para',) and 'cuando' in purpose and any(
            word in {'ejecute', 'ejecutes', 'ejecuten', 'corra', 'corras'}
            for word in purpose[purpose.index('cuando') + 1:]
        ):
            return True
    window = words[max(0, claim_index - 3) : claim_index + 9]
    for index, word in enumerate(window):
        if word in _EXPLANATION_LIMITERS and any(
            candidate in _EXPLANATION_TEMPORALS for candidate in window[index + 1 :]
        ):
            return True
    return False


def _next_claim_word(words: tuple[str, ...], index: int) -> int:
    while index < len(words) and words[index] in _ADVERBS:
        index += 1
    return index


def _english_claim(words: tuple[str, ...], conditional: tuple[int, ...]) -> bool:
    bridges = frozenset(
        "already all am are d did finally fully had have just m now re successfully ve".split()
    )
    question_auxiliaries = frozenset(
        "am are did do does had has have is was were".split()
    )
    for index, word in enumerate(words):
        if word in {"i", "we"} and not (
            index and words[index - 1] in question_auxiliaries
        ):
            candidate = index + 1
            while candidate < len(words) and words[candidate] in bridges:
                candidate += 1
            if candidate < len(words):
                completed = words[candidate] in _COMPLETED_EN
                did_edit = "did" in words[index:candidate] and words[candidate] in _EDIT_EN
                if (completed or did_edit) and not _hypothetical(
                    words,
                    conditional,
                    index,
                    candidate + 1,
                    generic_temporal=False,
                ):
                    return True

        if word not in _COMPLETED_EN:
            continue
        auxiliary = index - 1
        while auxiliary >= 0 and words[auxiliary] in _ADVERBS:
            auxiliary -= 1
        if auxiliary < 0:
            continue
        if words[auxiliary] == "been":
            perfect = auxiliary - 1
            while perfect >= 0 and words[perfect] in _ADVERBS:
                perfect -= 1
            if perfect < 0 or words[perfect] not in {"had", "has", "have", "s"}:
                continue
            start = perfect
        elif words[auxiliary] in {"am", "are", "is", "s", "was", "were"}:
            start = auxiliary
        else:
            continue
        if not _hypothetical(
            words, conditional, start, index + 1, generic_temporal=True
        ) and not _has_explanatory_suffix(words, index):
            return True
    return False


def _spanish_claim(
    raw_words: tuple[str, ...],
    words: tuple[str, ...],
    conditional: tuple[int, ...],
) -> bool:
    for index, raw_word in enumerate(raw_words):
        word = words[index]
        recent_unaccented = word in _ACTIVE_ES_PLAIN and any(
            marker in _ADVERBS for marker in words[max(0, index - 2) : index]
        )
        if (
            raw_word in _ACTIVE_ES_RAW
            or recent_unaccented
            or word in _ACTIVE_PLURAL_ES
        ) and not _hypothetical(
            words,
            conditional,
            index,
            index + 1,
            generic_temporal=False,
        ):
            return True
        if (
            word == "se"
            and words[index + 1 : index + 2]
            and words[index + 1] in _REFLEXIVE_PAST_ES
            and not _hypothetical(
                words,
                conditional,
                index,
                index + 2,
                generic_temporal=False,
            )
        ):
            return True
        if word in {"acabo", "acabamos"} and words[index + 1 : index + 2] == (
            "de",
        ):
            candidate = index + 2
            if (
                candidate < len(words)
                and words[candidate] in _INFINITIVE_ES
                and not _hypothetical(
                    words,
                    conditional,
                    index,
                    candidate + 1,
                    generic_temporal=False,
                )
            ):
                return True

    for index, word in enumerate(words):
        if word in {"ha", "han", "has", "he", "hemos"}:
            offset = 2 if words[index + 1 : index + 2] == ("sido",) else 1
            candidate = _next_claim_word(words, index + offset)
        elif word in {
            "esta",
            "estan",
            "fue",
            "fueron",
            "queda",
            "quedan",
            "quedo",
            "quedaron",
        }:
            candidate = _next_claim_word(words, index + 1)
        else:
            continue
        if (
            candidate < len(words)
            and words[candidate] in _COMPLETED_ES
            and not _hypothetical(
                words,
                conditional,
                index,
                candidate + 1,
                generic_temporal=word in {
                    "esta",
                    "estan",
                    "fue",
                    "fueron",
                    "ha",
                    "han",
                    "queda",
                    "quedan",
                    "quedo",
                    "quedaron",
                },
            )
            and not _has_explanatory_suffix(words, candidate)
        ):
            return True
    return False


def _bare_claim(words: tuple[str, ...], conditional: tuple[int, ...]) -> bool:
    prefixes = frozenset("all already claro now ok okay sure todo ya".split())
    status = _COMPLETED_EN | _COMPLETED_ES
    prefix_allowed = True
    for index, word in enumerate(words):
        if word in status and prefix_allowed:
            # Availability/location is not a claim that an editor action ran.
            # Other segments still undergo all completion checks.
            if word in {"listo", "lista", "ready"} and (
                words[index + 1:index + 3] in {("por", "aca"), ("por", "aqui"), ("para", "ayudarte"), ("para", "ayudar")}
                or words[index + 1:index + 2] == ("here",)
            ):
                continue
            return not _hypothetical(
                words, conditional, index, index + 1, generic_temporal=True
            )
        prefix_allowed &= word in prefixes
    return False


def _reduced_claim(words: tuple[str, ...], conditional: tuple[int, ...]) -> bool:
    for index, word in enumerate(words):
        if word not in _COMPLETED_EN and word not in _COMPLETED_ES:
            continue
        if (word == 'complete' and words[max(0, index - 1):index] == ('que',)
                and words[index + 1:index + 2] and words[index + 1] in {'un', 'una', 'el', 'la', 'los', 'las'}):
            continue  # Spanish subjunctive "un bot que complete un formulario".
        # Spanish "lista" also means a list of steps. A determiner makes
        # that a noun, rather than an assertion that the bot is ready.
        if word == 'lista' and index and words[index - 1] in {'la', 'una', 'esa', 'esta', 'su', 'tu', 'mi', 'nuestra'}:
            continue
        if word == 'lista':
            following = index + 1
            while following < len(words) and words[following] in {'solo', 'unicamente', 'solamente'}:
                following += 1
            if words[following:following + 1] and words[following] in {'los', 'las', 'unos', 'unas', 'archivos', 'documentos', 'carpetas', 'elementos', 'registros', 'resultados'}:
                continue  # Present-tense "listar", not a readiness adjective.
        if word in {'listo', 'lista', 'listos', 'listas', 'ready'} and any(
            words[start:start + 2] in {('para', 'tener'), ('to', 'have')}
            for start in range(max(0, index - 5), index)
        ):
            continue
        auxiliary = index - 1
        while auxiliary >= 0 and words[auxiliary] in _ADVERBS:
            auxiliary -= 1
        if auxiliary >= 0 and words[auxiliary] in _STATUS_AUXILIARIES:
            continue
        if not any(
            subject in _REDUCED_SUBJECTS for subject in words[max(0, index - 4) : index]
        ):
            continue
        if _has_explanatory_suffix(words, index):
            continue
        # "El bot escribe Pedido listo" describes a literal, not completion.
        # This exemption is local to a reduced status phrase; explicit past
        # claims and claims in subsequent clauses still undergo all checks.
        if any(verb in {'escribe', 'escribira', 'muestra', 'contiene', 'dice', 'guarda', 'conserva', 'writes', 'displays', 'contains', 'saves'}
               for verb in words[max(0, index - 4):index]):
            continue
        if not _hypothetical(
            words, conditional, index, index + 1, generic_temporal=True
        ):
            return True
    return False


def _is_interrogative(
    words: tuple[str, ...],
    commas: tuple[int, ...],
    question_open: int | None,
    question_close: bool,
) -> bool:
    if (question_open is None and not question_close) or not words:
        return False
    if question_open is not None and all(
        word in _QUESTION_PREFIXES for word in words[:question_open]
    ):
        return True
    if question_open is not None:
        return False
    if _question_head(words) in _COMPLETION_QUESTION_HEADS:
        return True
    if commas:
        return False
    if words[-1] in _TAG_QUESTION_WORDS:
        return False
    if words[-1] in _TAG_QUESTION_PRONOUNS and any(
        word in _TAG_QUESTION_AUXILIARIES for word in words[-4:-1]
    ):
        return False
    return question_close


def contains_editor_completion_claim(content: str) -> bool:
    normalized = unicodedata.normalize("NFC", content)
    bounded = normalized[:MAX_POLICY_CODE_POINTS]
    if len(normalized) > len(bounded):
        return True
    for raw_words, commas, _, question_open, question_close in _segments(
        bounded, ignore_quotes=False
    ):
        words = tuple(_plain(word) for word in raw_words)
        if _is_interrogative(words, commas, question_open, question_close):
            continue
        conditional = _conditional_prefix(raw_words, words, commas)
        if (
            _english_claim(words, conditional)
            or _spanish_claim(raw_words, words, conditional)
            or _bare_claim(words, conditional)
            or _reduced_claim(words, conditional)
        ):
            return True
    return False
