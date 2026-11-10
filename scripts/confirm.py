"""Is the user's message a plain yes or no to the question just asked? Decided by code, never by a model, so text in a
mail or web page cannot approve anything. Idea and word lists adapted from askq's src/confirm.js (MIT,
github.com/quircedelafuente/askq).

A yes is short (max 5 words), starts with an affirmation ("yes", "ok book it", "sí", "vale") or is a lone verb
("book it"), and has no word that hedges ("no", "wait", "but"). "Book the gym at 4" is NOT a yes: it is a new request.
"""
import re

YES = re.compile(r"^(yes|yeah|yep|yup|ya|sure|ok|okay|confirm|confirmed|correct|right|exactly|absolutely|definitely|go|"
                 r"s[ií]|vale|dale|adelante|claro|confirmo|perfecto|venga|exacto|ja|jo|genau|klar|passt)$", re.I)
YES_VERB = re.compile(r"^(book|do|proceed|reserve|add|delete|go|hazlo|res[eé]rvalo|buch|mach)$", re.I)
NO = re.compile(r"^(no|not|nope|nah|don'?t|dont|wait|stop|cancel|change|but|instead|espera|cambia|pero|nein|warte|nicht)$", re.I)
FILLER = {"it", "that", "please", "pls", "thanks", "thank", "you", "do", "go", "ahead", "lo", "es", "bitte", "das", "for", "me"}


def words(text):
    return [w for w in re.sub(r"[^\w' ]+", " ", str(text).lower()).split() if w]


def is_yes(text):
    w = words(text)
    if not w or len(w) > 5 or any(NO.match(x) for x in w):
        return False
    if YES.match(w[0]):
        return True
    return bool(YES_VERB.match(w[0])) and all(x in FILLER for x in w[1:])


def is_no(text):
    w = words(text)
    return bool(w) and len(w) <= 4 and bool(NO.match(w[0]))
