#!/usr/bin/env python3
"""Anonymisierer für E-Mail-Exporte und Tabellen (CLI + Library)."""

import argparse
import codecs
import csv
import email
import glob
import html
import io
import mailbox
import re
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime
from email.header import decode_header, make_header
from email.utils import getaddresses
from pathlib import Path

from openpyxl import load_workbook


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

PARTIKEL = frozenset(
    "von van de du den der des di la le les zu zum zur da dos das am auf "
    "el al bin ben mc mac ten ter het".split()
)

STOP = frozenset({
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer", "eines", "einem", "einen",
    "und", "oder", "aber", "doch", "wenn", "weil", "dass", "als", "wie", "für", "mit", "von",
    "zu", "bei", "nach", "über", "unter", "vor", "zwischen", "durch", "ohne", "gegen", "bis",
    "seit", "ab", "an", "auf", "aus", "in", "um", "am", "im", "vom", "zum", "zur", "ins",
    "sehr", "viel", "mehr", "noch", "schon", "auch", "nur", "so", "da", "hier", "dort",
    "nicht", "kein", "keine", "keinen", "keinem", "keiner",
    "herr", "frau", "dr", "prof", "ing", "dipl", "mag", "mr", "mrs", "ms",
    "re", "aw", "fwd", "wg", "betr", "betreff", "subject", "antw",
    "the", "and", "or", "but", "for", "with", "from", "to", "at", "by", "of", "in", "on",
    "is", "are", "was", "were", "be", "been", "has", "have", "had", "do", "does", "did",
    "this", "that", "these", "those", "it", "its", "my", "your", "our", "their",
    "dear", "hello", "hi", "hey", "regards", "sincerely", "best",
    "nr", "tel", "fax", "mob", "www", "http", "https", "mailto",
    "info", "service", "kontakt", "support", "office",
})

FIRMENZUSATZ = frozenset({
    "gmbh", "ag", "kg", "ohg", "gbr", "ug", "se", "eg", "mbh", "kgaa",
    "e.v", "e.k", "e.g", "ev", "ek",
    "partg", "partgmbb",
    "co", "inc", "ltd", "llc", "corp", "plc", "sa", "sarl", "bv", "nv", "srl",
    "stiftung", "verein", "genossenschaft",
    "haftungsbeschränkt", "haftungsbeschraenkt",
})

WORT_RE = re.compile(r"[^\W\d_]+(?:[''\-][^\W\d_]+)*\.?", re.UNICODE)
TOKEN_RE = re.compile(r"\w+(?:[-']\w+)*|[^\w\s]", re.UNICODE)

KOPFZEILE = re.compile(r"^(?:Von|An|Cc|Bcc|From|To|Reply-To):[ \t]+(.*)", re.I)
BETREFFZEILE = re.compile(r"^(?:Betreff|Subject):[ \t]", re.I)

FIRMA_RE = re.compile(
    r"(\b[A-ZÄÖÜ][\w.\-]*(?:[ \t]+(?:[A-ZÄÖÜ&][\w.\-]*|und|u\.|am|im|an|von|vom|zum|zur))*?)\s+"
    r"(GmbH(?:\s*&\s*Co\.?\s*(?:KG(?:aA)?|OHG))?|AG|KG(?:aA)?|OHG|GbR|UG|SE|eG|"
    r"e\.?\s?[VKG]\.?|mbH|Inc\.?|Ltd\.?|LLC|Corp\.?|PLC|SA|S\.?[aà]\.?r\.?l\.?|"
    r"BV|NV|SRL|Partg(?:mbB)?|Stiftung|Verein|Genossenschaft)\b"
)

MAIL_IN_KLAMMERN = re.compile(r"<([\w.%+\-]+@[\w\-]+(?:\.[\w\-]+)*\.[A-Za-z]{2,})>")

NAMENSSPALTE = re.compile(
    r"(?i)\b(?:name|vorname|nachname|ansprechpartner|kontakt(?:person)?|"
    r"sachbearbeiter|bearbeiter|verfasser|autor|absender|empf[äa]nger|"
    r"mitarbeiter|kunde|kundenname|inhaber|gesch[äa]ftsf[üu]hrer)\b"
)

ROLLEN_RE = re.compile(
    r"(?i)\b(?:geschäftsführer(?:in(?:nen)?)?|geschaeftsfuehrer(?:in(?:nen)?)?|"
    r"vorstand(?:svorsitzende[rn]?)?|prokurist(?:in(?:nen)?)?|"
    r"inhaber(?:in(?:nen)?)?|gesellschafter(?:in(?:nen)?)?)"
    r"\s*:\s*(.+)"
)

FIRMENBEZEICHNUNG_RE = re.compile(
    r"(?i)\b(?:firma|unternehmen|auftraggeber|auftragnehmer|mandant)"
    r"\s*:\s*(.+)"
)

_POSITION_KERN = (
    r"(?:allein|einzel|gesamt|stellvertretende[rn]?)[\s-]?)?(?:"
    r"geschäftsführer(?:in(?:nen)?)?|geschaeftsfuehrer(?:in(?:nen)?)?|"
    r"vorstand(?:svorsitzende[rn]?)?|vorstandsmitglied(?:er)?|"
    r"prokurist(?:in(?:nen)?|en)?|"
    r"inhaber(?:in(?:nen)?)?|"
    r"gesellschafter(?:in(?:nen)?)?(?:[\s-]?geschäftsführer(?:in)?)?|"
    r"geschäftsleiter(?:in(?:nen)?)?|geschaeftsleiter(?:in(?:nen)?)?|"
    r"betriebsleiter(?:in(?:nen)?)?|"
    r"aufsichtsratsvorsitzende[rn]?|aufsichtsratsmitglied(?:er)?|"
    r"vertretungsberechtigte[rn]?(?:\s+geschäftsführer(?:in)?)?|"
    r"vertretungsberechtigte[rn]?|"
    r"liquidator(?:in(?:nen)?|en)?|"
    r"handelsbevollmächtigte[rn]?|"
    r"generalbevollmächtigte[rn]?|"
    r"niederlassungsleiter(?:in(?:nen)?)?|"
    r"kommanditist(?:in(?:nen)?|en)?|komplementär(?:in(?:nen)?|e)?|"
    r"einzelkaufmann|einzelkauffrau"
)

POSITION_RE = re.compile(
    r"(?i)\b(?:(?:" + _POSITION_KERN + r"))\b"
)

GERICHT_RE = re.compile(
    r"\b(?:[Rr]egistergericht|[Aa]mtsgericht)\s+"
    r"([A-ZÄÖÜ][a-zäöüß]+(?:[- ](?:[A-ZÄÖÜ][a-zäöüß]+|am|an|im|in|ob|bei|a\.|i\.)){0,3})"
)

STANDORT_RE = re.compile(
    r"\b(?:[Ss]itz|[Ff]irmensitz|[Gg]eschäftssitz|[Gg]eschaeftssitz|[Hh]auptsitz|"
    r"[Ss]tandort|[Nn]iederlassung|[Hh]auptniederlassung|"
    r"[Bb]etriebsstätte|[Bb]etriebsstaette|[Ff]iliale|[Zz]weigstelle)"
    r"(?:\s*:\s*|\s+(?:\w+\s+){0,3}(?:in|zu)\s+)(?:(?:der|des|am|im)\s+)*"
    r"([A-ZÄÖÜ][a-zäöüß]+(?:[- ](?:[A-ZÄÖÜ][a-zäöüß]+|am|an|im|in|ob|bei|a\.|i\.)){0,3})"
)

ORT_AUS_PLZ_RE = re.compile(
    r"\b(?:D-)?\d{5}[ \t]+"
    r"([A-ZÄÖÜ][a-zäöüß]+(?:[- ](?:[A-ZÄÖÜ][a-zäöüß]+|am|an|im|in|ob|bei|vor|a\.|i\.)){0,3})"
)

PRIO_BEGRIFF = 200
PRIO_AUTO = 55


# ---------------------------------------------------------------------------
# Validierungsfunktionen für Regex-Muster
# ---------------------------------------------------------------------------

def _url_ok(text, s, e):
    while e > s and text[e - 1] in ".,;:!?)\"'>]":
        e -= 1
    if e - s < 10:
        return None
    return (s, e)


def _iban_ok(text, s, e):
    iban = re.sub(r"\s", "", text[s:e])
    if len(iban) < 16 or len(iban) > 34:
        return None
    return (s, e)


def _steuer_ok(text, s, e):
    ziffern = re.sub(r"\D", "", text[s:e])
    if len(ziffern) != 11 or ziffern[0] == "0":
        return None
    if s > 0 and text[s - 1].isdigit():
        return None
    if e < len(text) and text[e].isdigit():
        return None
    return (s, e)


def _ip_ok(text, s, e):
    teile = text[s:e].split(".")
    try:
        if all(0 <= int(t) <= 255 and (t == "0" or not t.startswith("0")) for t in teile):
            return (s, e)
    except ValueError:
        pass
    return None


def _strasse_ok(text, s, e):
    if e - s < 10:
        return None
    return (s, e)


def _tel_ok(text, s, e):
    ziffern = re.sub(r"\D", "", text[s:e])
    if len(ziffern) < 7 or len(ziffern) > 15:
        return None
    return (s, e)


def _ort_ok(text, s, e):
    if e - s < 7:
        return None
    return (s, e)


def _firma_ok(text, s, e):
    offset = s
    teile = text[s:e].split()
    for wort in teile:
        if wort.rstrip(".").casefold() not in STOP:
            break
        offset = text.index(wort, offset) + len(wort)
        while offset < e and text[offset] in " \t":
            offset += 1
    else:
        return None
    if offset >= e:
        return None
    erstes = text[offset:e].split()[0].rstrip(".")
    if erstes.casefold() in STOP or len(erstes) < 2:
        return None
    return (offset, e)


_RECHTSFORM = (
    r"(?:GmbH(?:\s*&\s*Co\.?\s*(?:KG(?:aA)?|OHG))?|AG|KG(?:aA)?|OHG|GbR|UG|SE|eG|"
    r"e\.?\s?[VKG]\.?|mbH|Inc\.?|Ltd\.?|LLC|Corp\.?|PLC|SA|S\.?[aà]\.?r\.?l\.?|"
    r"BV|NV|SRL|Partg(?:mbB)?|Stiftung|Verein|Genossenschaft)"
)

FIRMA_MUSTER_RE = re.compile(
    r"\b[\w][\w.\-@]*(?:[ \t]+[\w.\-@&]+){0,5}[ \t]+" + _RECHTSFORM + r"\b"
)


MUSTER = [
    ("EXCHANGE_ID", re.compile(r"(?i)/o=[^;\r\n\"<>]*?/cn=[^;\s\"<>]+"), 100, 0, None),
    ("EMAIL", re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}"), 95, 0, None),
    ("URL", re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"'\[\]()]+"), 90, 0, _url_ok),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b"), 85, 0, _iban_ok),
    ("STEUER_ID", re.compile(r"\b\d{2} ?\d{3} ?\d{3} ?\d{3}\b"), 78, 0, _steuer_ok),
    ("UST_ID", re.compile(r"\b(?:DE ?\d{9}|ATU ?\d{8})\b"), 80, 0, None),
    ("HANDELSREGISTER", re.compile(r"(?i)\bHR[AB][ \t/-]?(?:(?:Nr\.?|Nummer)[ \t:.-]*)?[ \t/-]?\d{2,10}(?: ?[A-Z]{1,2}\b)?"), 80, 0, None),
    ("POSITION", POSITION_RE, 72, 0, None),
    ("FIRMA", FIRMA_MUSTER_RE, 50, 0, _firma_ok),
    ("NUMMER", re.compile(
        r"(?i)\b(?:(?:kunden|vertrags|rechnungs|auftrags|bestell|angebots|mitglieds|versicherungs|personal"
        r"|policen|vorgangs|lieferanten|debitoren|kreditoren|steuer|akten|kassen)[\s-]*"
        r"(?:nummer|nr\.?|no\.?|zeichen|id)|ticket|referenz|ref\.|az\.|kd\.?-?nr\.?)[\s.:#-]*"
        r"((?=[A-Za-z0-9./-]*\d)[A-Za-z0-9](?:[A-Za-z0-9./-]*[A-Za-z0-9])?)"), 75, 1, None),
    ("IP", re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d|\.\d)"), 70, 0, _ip_ok),
    ("ADRESSE", re.compile(
        r"\b[A-ZÄÖÜ][a-zäöüß]+(?:[- ][A-ZÄÖÜ][a-zäöüß]+){0,3}"
        r"(?:[- ]?(?i:straße|strasse|str\.|weg|gasse|platz|allee|chaussee|promenade)"
        r"|[- ](?i:ring|damm|ufer|markt|park|berg|feld|hof|garten|graben|steig|pfad|kamp|anger))"
        r"[ \t]*\d{1,4}[ \t]?[a-zA-Z]?(?:[ \t]?[-/][ \t]?\d{1,4}[a-zA-Z]?)?(?!\w)"), 65, 0, _strasse_ok),
    ("PLZ_ORT", re.compile(
        r"(?m)(?:^[ \t>]*|(?<=[,|·–—-])[ \t]?)"
        r"((?:D-)?\d{5}[ \t]+[A-ZÄÖÜ][a-zäöüß]+"
        r"(?:[- ](?:[A-ZÄÖÜ][a-zäöüß]+|am|an|im|in|ob|bei|vor|a\.|i\.)(?=[\s,.;]|$)){0,3})"), 65, 1, _ort_ok),
    ("TEL", re.compile(
        r"(?<![\w+/.])(?:(?:\+|00)[1-9]\d{0,2}[ ./-]?(?:\(0\)[ ./-]?)?|\(0\d{1,5}\)[ ./-]?|0)"
        r"\d{1,12}(?:[ ./-]{1,3}\d{1,12}){0,5}(?![\w/])"), 60, 0, _tel_ok),
    ("DOMAIN", re.compile(
        r"(?<![\w@.\-/])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
        r"(?:de|com|net|org|eu|at|ch|io|info|biz|co|uk|nl|fr|it|es|pl|be|lu|local|lan|intern|corp|cloud)"
        r"(?![\w-]|\.[a-z0-9])", re.I), 50, 0, None),
]


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
def _norm(wort):
    return wort.rstrip(".").casefold()


def _varianten(wort):
    v = {wort, wort[:1].upper() + wort[1:], wort[:1].upper() + wort[1:].lower(), wort.upper()}
    if len(wort) >= 6:
        v.add(wort.lower())
    return v


def _namensende(s):
    """Liefert die Folge großgeschriebener Wörter direkt vor einer <mail@adresse>."""
    s = s.rstrip(" \t\"'*")
    start = None
    for m in reversed(list(re.finditer(r"[^\W\d_]+(?:['’-][^\W\d_]+)*\.?|,|\S", s))):
        t = m.group()
        if t == "," or t[:1].isupper() or t.casefold() in PARTIKEL:
            start = m.start()
        else:
            break
    return s[start:] if start is not None else ""


def _normalisieren(label, wert):
    if label == "TEL":
        w = wert.replace("(0)", "")
        z = re.sub(r"\D", "", w)
        if w.lstrip().startswith("+49"):
            z = "0" + z[2:]
        elif z.startswith("0049"):
            z = "0" + z[4:]
        return z
    if label in ("IBAN", "UST_ID", "HANDELSREGISTER", "NUMMER"):
        return re.sub(r"\s", "", wert).upper()
    return " ".join(wert.split()).casefold()


def _stuecke(text, maxlen=20000):
    teile, akt, laenge = [], [], 0
    for zeile in text.splitlines(keepends=True):
        if akt and laenge + len(zeile) > maxlen:
            teile.append("".join(akt))
            akt, laenge = [], 0
        akt.append(zeile)
        laenge += len(zeile)
    if akt:
        teile.append("".join(akt))
    return teile



# Anonymisierer
# ---------------------------------------------------------------------------
class Anonymisierer:
    def __init__(self, ausnahmen=()):
        self.ausnahmen = {a.casefold() for a in ausnahmen}
        self._index = {False: {}, True: {}}   # ci -> {erstes Token: {Tokenfolge: (Label, Gruppe, Prio)}}
        self.teil_gruppe = {}
        self.platzhalter = {}
        self.zaehler = Counter()
        self.treffer = Counter()
        self.originale = defaultdict(set)

    # --- Begriffe registrieren -------------------------------------------
    def _term(self, text, label, gruppe, ci, prio):
        toks = TOKEN_RE.findall(text)
        if not toks:
            return
        key = tuple(t.casefold() for t in toks) if ci else tuple(toks)
        eintraege = self._index[ci].setdefault(key[0], {})
        alt = eintraege.get(key)
        if alt is None or prio > alt[2]:
            eintraege[key] = (label, gruppe, prio)

    def begriff(self, text, label="BEGRIFF"):
        text = " ".join(text.split())
        if not text or text.casefold() in self.ausnahmen:
            return
        gruppe = (label, text.casefold())
        if label == "PERSON":                       # gleiche Nummer wie der Name im Mail-Kopf
            self.name(text, streng=False)
            teile = [_norm(w) for w in WORT_RE.findall(text)]
            gruppe = next((self.teil_gruppe[t] for t in teile if t in self.teil_gruppe), gruppe)
        self._term(text, label, gruppe, ci=True, prio=PRIO_BEGRIFF)

    def name(self, roh, streng=True):
        """Registriert einen Personen- oder Firmennamen samt Namensteilen."""
        if not roh:
            return
        for innen in re.findall(r"\(([^()]*)\)", roh):
            self.name(innen, streng)
        roh = re.sub(r"\([^()]*\)|<[^<>]*>|\[[^\[\]]*\]", " ", roh)
        roh = " ".join(roh.split()).strip(" \"'*,;:")
        if not roh or len(roh) > 80 or re.search(r"[@/\\\d]", roh):
            return
        stuecke = [p.strip() for p in roh.split(",") if p.strip()]
        if len(stuecke) > 1 and any(len([w for w in p.split() if _norm(w) not in STOP]) > 1 for p in stuecke):
            for p in stuecke:                       # Liste mehrerer Namen
                self.name(p, streng)
            return
        treffer = list(WORT_RE.finditer(roh))
        while treffer and _norm(treffer[0].group()) in STOP:
            treffer.pop(0)
        while treffer and _norm(treffer[-1].group()) in STOP:
            treffer.pop()
        if not treffer or len(treffer) > 5:
            return
        woerter = [m.group() for m in treffer]
        voll = roh[treffer[0].start():treffer[-1].end()].rstrip(".")
        if voll.casefold() in self.ausnahmen:
            return
        label = "FIRMA" if any(_norm(w) in FIRMENZUSATZ for w in woerter) else "PERSON"
        kern = [t for w in woerter for t in w.rstrip(".").split("-")
                if len(t) >= 3 and _norm(t) not in STOP and _norm(t) not in FIRMENZUSATZ
                and t.casefold() not in self.ausnahmen and (t[:1].isupper() or not streng)]
        if not kern:
            return
        kern_set = frozenset(k.casefold() for k in kern)
        gruppe = (label, kern_set)
        for k in kern_set:                          # gleiche Person -> gleicher Platzhalter
            g = self.teil_gruppe.get(k)
            if g and g[0] == label and (kern_set <= g[1] or g[1] <= kern_set):
                gruppe = g
                break
        if not streng or all(w[:1].isupper() or _norm(w) in PARTIKEL for w in woerter):
            self._term(voll, label, gruppe, ci=True, prio=PRIO_AUTO)
            if label == "PERSON" and len(woerter) == 2:   # "Max Muster" <-> "Muster, Max"
                a, b = woerter
                formen = (f"{a} {b}", f"{b} {a}") if "," in voll else (f"{b}, {a}", f"{b} {a}")
                for form in formen:
                    self._term(form, label, gruppe, ci=True, prio=PRIO_AUTO)
        for k in kern:
            self.teil_gruppe.setdefault(k.casefold(), gruppe)
            for v in _varianten(k):
                self._term(v, label, gruppe, ci=False, prio=PRIO_AUTO)

    def firma(self, vorne, rechtsform):
        """'Muster GmbH' -> Vollform und 'Muster' bekommen denselben Platzhalter."""
        woerter = vorne.split()
        while woerter and (_norm(woerter[0]) in STOP or woerter[0] == "&"):
            woerter.pop(0)
        kern = " ".join(woerter)
        if not woerter or woerter[-1].isdigit() or len(kern) < 2 or kern.casefold() in self.ausnahmen:
            return
        gruppe = ("FIRMA", kern.casefold())
        self._term(f"{kern} {rechtsform}", "FIRMA", gruppe, ci=True, prio=PRIO_AUTO)
        if len(woerter) > 1:
            self._term(kern, "FIRMA", gruppe, ci=True, prio=PRIO_AUTO)
        elif len(kern) >= 3 and _norm(kern) not in STOP:
            for v in _varianten(kern):
                self._term(v, "FIRMA", gruppe, ci=False, prio=PRIO_AUTO)

    def begriff_auto(self, roh, label):
        treffer = list(WORT_RE.finditer(roh))
        while treffer and _norm(treffer[0].group()) in STOP:
            treffer.pop(0)
        while treffer and _norm(treffer[-1].group()) in STOP:
            treffer.pop()
        if not treffer or len(treffer) > 6:
            return
        voll = roh[treffer[0].start():treffer[-1].end()].rstrip(".")
        if len(voll) < 3 or not voll[:1].isupper() or voll.casefold() in self.ausnahmen:
            return
        gruppe = (label, voll.casefold())
        if len(treffer) == 1:
            for v in _varianten(voll):
                self._term(v, label, gruppe, ci=False, prio=PRIO_AUTO)
        else:
            self._term(voll, label, gruppe, ci=True, prio=PRIO_AUTO)

    # --- Namen sammeln ------------------------------------------------------
    def namen_aus_text(self, text):
        zeilen = text.splitlines()
        for i, zeile in enumerate(zeilen):
            m = KOPFZEILE.match(zeile)
            if m and any(BETREFFZEILE.match(z) for z in zeilen[max(0, i - 6):i + 7]):
                for eintrag in re.sub(r">\s*,", ">;", m.group(1)).split(";"):
                    self.name(eintrag, streng=False)
        for m in FIRMA_RE.finditer(text):
            self.firma(m.group(1), m.group(2))
        for m in MAIL_IN_KLAMMERN.finditer(text):
            anfang = text.rfind("\n", 0, m.start()) + 1
            davor = re.split(r"[<>\[\];:]", text[max(anfang, m.start() - 80):m.start()])[-1]
            self.name(_namensende(davor))
        for m in ROLLEN_RE.finditer(text):
            for teil in re.split(r'[,;/|]', m.group(1)):
                self.name(teil.strip(), streng=False)
        for m in POSITION_RE.finditer(text):
            rest = text[m.end():]
            kolon_m = re.match(r'\s*:\s*', rest)
            if kolon_m:
                zeile_rest = rest[kolon_m.end():].split('\n', 1)[0]
                for teil in re.split(r'[,;/|]', zeile_rest):
                    self.name(teil.strip(), streng=False)
                continue
            name_m = re.match(
                r'[ \t]+(?:(?:Dr|Prof|Dipl|Ing|Mag|Mr|Mrs|Ms)\.?[ \t]+)*'
                r'([A-ZÄÖÜ][a-zäöüß]+'
                r'(?:[ \t]+(?:[A-ZÄÖÜ][a-zäöüß]+'
                r'|(?:von|van|de|du|den|der|des|di|la|le|zu|zum|zur)(?=[ \t]+[A-ZÄÖÜ]))'
                r'){0,3})',
                rest,
            )
            if name_m:
                self.name(name_m.group(1).strip(), streng=False)
        for m in FIRMENBEZEICHNUNG_RE.finditer(text):
            self.name(m.group(1).strip(), streng=False)
        for m in GERICHT_RE.finditer(text):
            ort = m.group(1).strip()
            if len(ort) >= 3:
                self.begriff_auto(ort, "ORT")
        for m in STANDORT_RE.finditer(text):
            ort = m.group(1).strip()
            if len(ort) >= 3:
                self.begriff_auto(ort, "ORT")
        for m in ORT_AUS_PLZ_RE.finditer(text):
            ort = m.group(1).strip()
            if len(ort) >= 3:
                self.begriff_auto(ort, "ORT")

    def ner_sammeln(self, nlp, texte, labels):
        typen = {"ORG": "FIRMA", "LOC": "ORT", "GPE": "ORT"}
        tags_pruefen = nlp.has_pipe("tagger")
        stuecke = [s for t in texte for s in _stuecke(t)]
        for doc in nlp.pipe(stuecke, batch_size=16):
            for ent in doc.ents:
                txt = ent.text.strip()
                if ent.label_ not in labels or "\n" in txt or "@" in txt or not 3 <= len(txt) <= 60:
                    continue
                # nur Treffer mit mindestens einem Eigennamen (weniger Fehlalarme wie "Normal", "Monitoring")
                if tags_pruefen and not any(t.tag_ in ("NE", "NNE") or t.pos_ == "PROPN" for t in ent):
                    continue
                if ent.label_ in ("PER", "PERSON"):
                    self.name(txt)
                elif ent.label_ in typen:
                    self.begriff_auto(txt, typen[ent.label_])

    # --- Ersetzen -------------------------------------------------------------
    def _begriff_spans(self, text):
        toks = list(TOKEN_RE.finditer(text))
        folgen = {False: [m.group() for m in toks], True: [m.group().casefold() for m in toks]}
        spans, leer = [], {}
        for i in range(len(toks)):
            for ci, folge in folgen.items():
                for key, (label, gruppe, prio) in self._index[ci].get(folge[i], leer).items():
                    ende = i + len(key)
                    if ende <= len(toks) and tuple(folge[i:ende]) == key:
                        spans.append((prio, toks[i].start(), toks[ende - 1].end(), label, gruppe))
        return spans

    def _platzhalter(self, label, gruppe):
        ph = self.platzhalter.get(gruppe)
        if ph is None:
            self.zaehler[label] += 1
            ph = self.platzhalter[gruppe] = f"[{label}_{self.zaehler[label]}]"
        return ph

    def ersetzen(self, text):
        if not text or not text.strip():
            return text
        kandidaten = []
        for label, regex, prio, grp, pruefen in MUSTER:
            for m in regex.finditer(text):
                s, e = m.span(grp)
                if s < 0 or s >= e:
                    continue
                if pruefen:
                    r = pruefen(text, s, e)
                    if not r:
                        continue
                    s, e = r
                kandidaten.append((prio, s, e, label, (label, _normalisieren(label, text[s:e]))))
        kandidaten += self._begriff_spans(text)
        # Überschneidungen: höhere Priorität, dann längerer Treffer gewinnt
        kandidaten.sort(key=lambda k: (-k[0], k[1] - k[2], k[1]))
        belegt = bytearray(len(text))
        gewaehlt = []
        for prio, s, e, label, gruppe in kandidaten:
            if any(belegt[s:e]) or text[s:e].casefold() in self.ausnahmen:
                continue
            belegt[s:e] = b"\x01" * (e - s)
            gewaehlt.append((s, e, label, gruppe))
        gewaehlt.sort(key=lambda g: g[0])
        teile, pos, letzter = [], 0, None
        for s, e, label, gruppe in gewaehlt:
            ph = self._platzhalter(label, gruppe)
            self.originale[ph].add(text[s:e])
            luecke = text[pos:s]
            if ph == letzter and not luecke.strip() and "\n" not in luecke:
                pos = e                             # "Max Mustermann" -> ein Platzhalter
                continue
            teile += [luecke, ph]
            self.treffer[label] += 1
            pos, letzter = e, ph
        teile.append(text[pos:])
        return "".join(teile)


# ---------------------------------------------------------------------------
# Filter nach Kunde und Zeitraum
# ---------------------------------------------------------------------------
MONATE = {"jan": 1, "jän": 1, "feb": 2, "mär": 3, "mae": 3, "mrz": 3, "mar": 3, "apr": 4, "mai": 5, "may": 5,
          "jun": 6, "jul": 7, "aug": 8, "sep": 9, "okt": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12}
DATUMSFORMATE = [
    (re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"), "jmt"),                          # 2026-02-03
    (re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})"), "tmj"),                        # 03.02.2026
    (re.compile(r"(\d{1,2})\.?\s+([^\W\d_]{3,})\.?,?\s+(\d{4})"), "tMj"),           # 3. Februar 2026 / 3 Feb 2026
    (re.compile(r"([^\W\d_]{3,})\.?\s+(\d{1,2}),?\s+(\d{4})"), "Mtj"),              # February 3, 2026
]
TXT_START = re.compile(r"^(?:Von|From):(\t|[ \t]+)", re.I)
TXT_DATUM = re.compile(r"^(?:Gesendet|Sent|Datum|Date):[ \t]*(.+)$", re.I)
TRENNLINIE = re.compile(r"^\s*(?:-{3,}|_{5,}|>)")


def datum_erkennen(text):
    for regex, reihenfolge in DATUMSFORMATE:
        for m in regex.finditer(text or ""):
            teil = dict(zip(reihenfolge, m.groups()))
            monat = teil.get("m") or MONATE.get(teil.get("M", "")[:3].casefold())
            try:
                return date(int(teil["j"]), int(monat), int(teil["t"]))
            except (TypeError, ValueError):
                continue
    return None


def datum_argument(wert):
    d = datum_erkennen(wert)
    if d is None:
        raise argparse.ArgumentTypeError(f"Datum nicht erkannt: {wert} (Format 2026-01-31 oder 31.01.2026)")
    return d


class Filter:
    def __init__(self, kunden=(), ab=None, bis=None):
        self.kunden = [k.strip().casefold() for k in kunden if k.strip()]
        self.ab, self.bis = ab, bis
        self.aktiv = bool(self.kunden or ab or bis)

    def passt(self, suchtext, datum, stat, datum_pruefen=True):
        stat["gesamt"] += 1
        if self.kunden and not any(k in suchtext.casefold() for k in self.kunden):
            return False
        if datum_pruefen and (self.ab or self.bis):
            if datum is None:
                stat["ohne_datum"] += 1
                return False
            if (self.ab and datum < self.ab) or (self.bis and datum > self.bis):
                return False
        stat["passend"] += 1
        return True


def txt_mails(text):
    """Teilt einen Outlook-TXT-Export in einzelne Mails; zitierte Köpfe im Text bleiben Teil der Mail."""
    zeilen = text.splitlines(keepends=True)

    def ist_start(i, nur_tab):
        m = TXT_START.match(zeilen[i])
        if not m or not any(TXT_DATUM.match(z) for z in zeilen[i + 1:i + 4]):
            return False
        if nur_tab:                                  # Outlook "Speichern unter": Tab nach "Von:"
            return m.group(1) == "\t"
        davor = [z for z in zeilen[max(0, i - 3):i] if z.strip()]
        return not (davor and TRENNLINIE.match(davor[-1]))

    starts = ([i for i in range(len(zeilen)) if ist_start(i, True)]
              or [i for i in range(len(zeilen)) if ist_start(i, False)])
    if not starts:
        return []
    starts[0] = 0
    return ["".join(zeilen[a:b]) for a, b in zip(starts, starts[1:] + [len(zeilen)])]


# ---------------------------------------------------------------------------
# Dateien lesen
# ---------------------------------------------------------------------------
def _dekodiere(daten):
    if daten.startswith(codecs.BOM_UTF8):
        text = daten[3:].decode("utf-8", errors="replace")
    elif daten.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        text = daten.decode("utf-16", errors="replace")
    elif len(daten) > 1 and daten[1] == 0:
        text = daten.decode("utf-16-le", errors="replace")
    else:
        try:
            text = daten.decode("utf-8")
        except UnicodeDecodeError:
            text = daten.decode("cp1252", errors="replace")
    return unicodedata.normalize("NFC", text)


def lese_text(pfad):
    return _dekodiere(Path(pfad).read_bytes())


def _kopf(msg, feld):
    werte = []
    for w in msg.get_all(feld) or []:
        try:
            werte.append(str(make_header(decode_header(str(w)))))
        except Exception:
            werte.append(str(w))
    return ", ".join(werte)


def _html_zu_text(quelle):
    s = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", quelle)
    s = re.sub(r"(?i)<br\s*/?>|</(?:p|div|tr|li|h[1-6]|table)>", "\n", s)
    s = html.unescape(re.sub(r"(?s)<[^>]+>", "", s))
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", s).strip()


def _mail_als_text(nr, msg):
    namen = []
    try:
        roh = [str(w) for f in ("From", "To", "Cc", "Reply-To") for w in (msg.get_all(f) or [])]
        for name, _ in getaddresses(roh):
            try:
                name = str(make_header(decode_header(name)))
            except Exception:
                pass
            namen.append(name)
        plain, htmlteile, anhaenge = [], [], 0
        for teil in msg.walk():
            if teil.is_multipart():
                continue
            if "attachment" in (teil.get("Content-Disposition") or "").lower() or teil.get_filename():
                anhaenge += 1
                continue
            typ = teil.get_content_type()
            if typ not in ("text/plain", "text/html"):
                continue
            nutzlast = teil.get_payload(decode=True) or b""
            try:
                s = nutzlast.decode(teil.get_content_charset() or "utf-8", errors="replace")
            except LookupError:
                s = nutzlast.decode("utf-8", errors="replace")
            (plain if typ == "text/plain" else htmlteile).append(s)
        text = "\n".join(plain) if plain else "\n".join(_html_zu_text(h) for h in htmlteile)
        zeilen = [f"===== Nachricht {nr} ====="]
        for feld, de in (("Date", "Datum"), ("From", "Von"), ("To", "An"), ("Cc", "Cc"), ("Subject", "Betreff")):
            wert = _kopf(msg, feld)
            if wert:
                zeilen.append(f"{de}: {wert}")
        if anhaenge:
            zeilen.append(f"Anhänge: {anhaenge} (nicht exportiert)")
        return "\n".join(zeilen) + "\n\n" + text.strip() + "\n", namen
    except Exception as fehler:
        return f"===== Nachricht {nr} =====\n[konnte nicht gelesen werden: {type(fehler).__name__}]\n", namen


def laden(pfad, filt):
    endung = pfad.suffix.lower()
    stat = Counter()
    if endung == ".txt":
        text = lese_text(pfad)
        if filt.aktiv:
            mails = txt_mails(text)
            if not mails:
                print(f"Warnung: {pfad.name}: keine Mail-Köpfe erkannt – Filter nicht anwendbar, alles übernommen.")
            else:
                behalten = []
                for mail in mails:
                    datum = None
                    for z in mail.splitlines()[:8]:
                        m = TXT_DATUM.match(z)
                        if m:
                            datum = datum_erkennen(m.group(1))
                            break
                    if filt.passt(mail, datum, stat):
                        behalten.append(mail)
                text = "".join(behalten)
        return {"typ": "text", "text": text, "namen": [], "stat": stat, "einheit": "Mails"}
    if endung == ".csv":
        text = lese_text(pfad)
        kopfzeile = text.split("\n", 1)[0]
        trenner = max([",", ";", "\t"], key=kopfzeile.count)
        csv.field_size_limit(2**31 - 1)
        zeilen = list(csv.reader(io.StringIO(text, newline=""), delimiter=trenner))
        if filt.aktiv and zeilen:
            kopf = zeilen[0]
            adressen = [i for i, k in enumerate(kopf) if re.match(r"\s*(?:von|an|cc|bcc|from|to)\b", k, re.I)]
            datumsspalte = next((i for i, k in enumerate(kopf)
                                 if re.search(r"datum|date|gesendet|erhalten|received|sent", k, re.I)), None)
            if (filt.ab or filt.bis) and datumsspalte is None:
                print(f"Warnung: {pfad.name} hat keine Datumsspalte (Outlook-CSV enthält kein Datum) – "
                      f"Zeitraum bitte beim Export in Outlook eingrenzen.")
            behalten = [kopf]
            for zeile in zeilen[1:]:
                such = " ".join(zeile[i] for i in adressen if i < len(zeile)) if adressen else " ".join(zeile)
                datum = (datum_erkennen(zeile[datumsspalte])
                         if datumsspalte is not None and datumsspalte < len(zeile) else None)
                if filt.passt(such, datum, stat, datum_pruefen=datumsspalte is not None):
                    behalten.append(zeile)
            zeilen = behalten
        return {"typ": "csv", "zeilen": zeilen, "trenner": trenner, "stat": stat, "einheit": "Zeilen"}
    if endung in (".mbox", ".eml"):
        if endung == ".eml":
            with open(pfad, "rb") as f:
                nachrichten = [email.message_from_binary_file(f)]
        else:
            nachrichten = mailbox.mbox(str(pfad), create=False)
        teile, namen = [], []
        for msg in nachrichten:
            if filt.aktiv:
                such = " ".join(_kopf(msg, f) for f in ("From", "To", "Cc", "Reply-To"))
                datum = (datum_erkennen(_kopf(msg, "Date"))
                         or datum_erkennen(str(msg.get("Received", "")).rsplit(";", 1)[-1]))
                if not filt.passt(such, datum, stat):
                    continue
            text, n = _mail_als_text(len(teile) + 1, msg)
            teile.append(text)
            namen += n
        return {"typ": "text", "text": unicodedata.normalize("NFC", "\n".join(teile)), "namen": namen,
                "stat": stat, "einheit": "Mails"}
    if endung == ".xlsx":
        if filt.aktiv:
            print(f"Warnung: {pfad.name}: Filter (Kunde/Zeitraum) wird bei Excel nicht angewendet.")
        return {"typ": "xlsx", "wb": load_workbook(pfad), "namen": [], "stat": stat, "einheit": "Zellen"}
    raise ValueError(f"Format {pfad.suffix or '(ohne Endung)'} nicht unterstützt – erlaubt: .txt .csv .xlsx .mbox .eml")


def zeilen_lesen(pfad):
    if not pfad:
        return []
    return [z.strip() for z in lese_text(pfad).splitlines() if z.strip() and not z.lstrip().startswith("#")]


def ner_laden(modell):
    try:
        import spacy
    except ImportError:
        print("Hinweis: spaCy nicht installiert – Namen werden nur aus Mail-Köpfen und --begriffe erkannt.\n"
              "         Bessere Erkennung: pip install spacy  und  python -m spacy download de_core_news_lg")
        return None
    for name in dict.fromkeys([modell, "de_core_news_lg", "de_core_news_md", "de_core_news_sm"]):
        try:
            nlp = spacy.load(name)
        except OSError:
            continue
        if "ner" in nlp.pipe_names:
            nlp.select_pipes(enable=[p for p in ("tok2vec", "tagger", "ner") if p in nlp.pipe_names])
            nlp.max_length = 10_000_000
            print(f"Namenserkennung mit {name} läuft ...")
            return nlp
    print(f"Hinweis: Kein deutsches spaCy-Modell gefunden – installieren mit: python -m spacy download {modell}")
    return None


# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------
def laden_bytes(name, daten, filt=None):
    """Wie laden(), aber aus Bytes statt Dateipfad (für Web-Upload)."""
    if filt is None:
        filt = Filter()
    endung = Path(name).suffix.lower()
    stat = Counter()
    if endung == ".txt":
        text = _dekodiere(daten)
        if filt.aktiv:
            mails = txt_mails(text)
            if mails:
                behalten = []
                for mail in mails:
                    datum = None
                    for z in mail.splitlines()[:8]:
                        m = TXT_DATUM.match(z)
                        if m:
                            datum = datum_erkennen(m.group(1))
                            break
                    if filt.passt(mail, datum, stat):
                        behalten.append(mail)
                text = "".join(behalten)
        return {"typ": "text", "text": text, "namen": [], "stat": stat, "einheit": "Mails"}
    if endung == ".csv":
        text = _dekodiere(daten)
        kopfzeile = text.split("\n", 1)[0]
        trenner = max([",", ";", "\t"], key=kopfzeile.count)
        csv.field_size_limit(2**31 - 1)
        zeilen = list(csv.reader(io.StringIO(text, newline=""), delimiter=trenner))
        if filt.aktiv and zeilen:
            kopf = zeilen[0]
            adressen = [i for i, k in enumerate(kopf) if re.match(r"\s*(?:von|an|cc|bcc|from|to)\b", k, re.I)]
            datumsspalte = next((i for i, k in enumerate(kopf)
                                 if re.search(r"datum|date|gesendet|erhalten|received|sent", k, re.I)), None)
            behalten = [kopf]
            for zeile in zeilen[1:]:
                such = " ".join(zeile[i] for i in adressen if i < len(zeile)) if adressen else " ".join(zeile)
                datum = (datum_erkennen(zeile[datumsspalte])
                         if datumsspalte is not None and datumsspalte < len(zeile) else None)
                if filt.passt(such, datum, stat, datum_pruefen=datumsspalte is not None):
                    behalten.append(zeile)
            zeilen = behalten
        return {"typ": "csv", "zeilen": zeilen, "trenner": trenner, "stat": stat, "einheit": "Zeilen"}
    if endung in (".mbox", ".eml"):
        if endung == ".eml":
            nachrichten = [email.message_from_bytes(daten)]
        else:
            roh_teile = re.split(rb"^From .+\n", daten, flags=re.MULTILINE)
            nachrichten = [email.message_from_bytes(t) for t in roh_teile if t.strip()]
        teile, namen = [], []
        for msg in nachrichten:
            if filt.aktiv:
                such = " ".join(_kopf(msg, f) for f in ("From", "To", "Cc", "Reply-To"))
                datum = (datum_erkennen(_kopf(msg, "Date"))
                         or datum_erkennen(str(msg.get("Received", "")).rsplit(";", 1)[-1]))
                if not filt.passt(such, datum, stat):
                    continue
            text, n = _mail_als_text(len(teile) + 1, msg)
            teile.append(text)
            namen += n
        return {"typ": "text", "text": unicodedata.normalize("NFC", "\n".join(teile)), "namen": namen,
                "stat": stat, "einheit": "Mails"}
    if endung == ".xlsx":
        return {"typ": "xlsx", "wb": load_workbook(io.BytesIO(daten)), "namen": [], "stat": stat, "einheit": "Zellen"}
    raise ValueError(f"Format {endung or '(ohne Endung)'} nicht unterstützt – erlaubt: .txt .csv .xlsx .mbox .eml")


def anonymisiere_dateien(dateien, kein_ner=True, begriffe=()):
    """Anonymisiert Dateien komplett im Arbeitsspeicher.

    dateien: Liste von (dateiname, bytes)
    kein_ner: spaCy-NER abschalten (Standard: True für Web)
    begriffe: Liste von Begriffen die zusätzlich anonymisiert werden (Blacklist)

    Gibt zurück: (ergebnisse, statistik)
        ergebnisse: Liste von (dateiname, anonymisierte_bytes)
        statistik: dict mit treffer- und zaehler-Counts
    """
    filt = Filter()
    anon = Anonymisierer()
    for term in begriffe:
        term = term.strip()
        if term:
            anon.begriff(term, "BEGRIFF")
    dokumente = []
    for name, daten in dateien:
        dok = laden_bytes(name, daten, filt)
        dokumente.append((name, dok))

    freitexte = []
    for _, dok in dokumente:
        if dok["typ"] == "xlsx":
            for ws in dok["wb"].worksheets:
                zeilen = list(ws.iter_rows(values_only=True))
                kopf = [str(k or "") for k in (zeilen[0] if zeilen else ())]
                namensspalten = [i for i, k in enumerate(kopf) if NAMENSSPALTE.search(k)]
                for zeile in zeilen[1:]:
                    for i in namensspalten:
                        if i < len(zeile) and isinstance(zeile[i], str):
                            for n in zeile[i].split(";"):
                                anon.name(n, streng=False)
                    for zelle in zeile:
                        if isinstance(zelle, str) and zelle.strip() and not zelle.startswith("="):
                            anon.namen_aus_text(zelle)
                            if len(zelle) >= 20 and " " in zelle.strip():
                                freitexte.append(zelle)
        elif dok["typ"] == "csv":
            kopf, *daten_zeilen = dok["zeilen"] or [[]]
            namensspalten = [i for i, k in enumerate(kopf) if NAMENSSPALTE.search(k)]
            for zeile in daten_zeilen:
                for i in namensspalten:
                    if i < len(zeile):
                        for n in zeile[i].split(";"):
                            anon.name(n, streng=False)
                for zelle in zeile:
                    if zelle.strip():
                        anon.namen_aus_text(zelle)
                        if len(zelle) >= 20 and " " in zelle.strip():
                            freitexte.append(zelle)
        else:
            for n in dok.get("namen", []):
                anon.name(n, streng=False)
            anon.namen_aus_text(dok["text"])
            freitexte.append(dok["text"])

    if not kein_ner:
        nlp = ner_laden("de_core_news_lg")
        if nlp:
            anon.ner_sammeln(nlp, freitexte, {"PER", "ORG", "LOC"})

    ergebnisse = []
    for name, dok in dokumente:
        if dok["typ"] == "xlsx":
            for ws in dok["wb"].worksheets:
                for zeile in ws.iter_rows():
                    for zelle in zeile:
                        v = zelle.value
                        if isinstance(v, str) and not v.startswith("="):
                            zelle.value = anon.ersetzen(v)
                        if zelle.comment is not None:
                            zelle.comment.text = anon.ersetzen(zelle.comment.text)
                            zelle.comment.author = ""
            wb = dok["wb"]
            wb.properties.creator = None
            wb.properties.lastModifiedBy = None
            wb.properties.title = None
            buf = io.BytesIO()
            wb.save(buf)
            ergebnisse.append((name, buf.getvalue()))
        elif dok["typ"] == "csv":
            buf = io.StringIO()
            schreiber = csv.writer(buf, delimiter=dok["trenner"])
            for nr, zeile in enumerate(dok["zeilen"]):
                schreiber.writerow(zeile if nr == 0 else [anon.ersetzen(z) for z in zeile])
            ergebnisse.append((name, buf.getvalue().encode("utf-8-sig")))
        else:
            text = anon.ersetzen(dok["text"])
            endung = Path(name).suffix.lower()
            ergebnisse.append((name, text.encode("utf-8")))

    statistik = {"treffer": dict(anon.treffer), "zaehler": dict(anon.zaehler)}
    return ergebnisse, statistik


def pfades_basis(pfade):
    return pfade[0].parent if pfade else Path(".")


def dateiname_bereinigen(text):
    """Gleiche Platzhalter direkt hintereinander zusammenfassen ([PERSON_1]_[PERSON_1] -> [PERSON_1]),
    dann Klammern entfernen und Leerzeichen zu Unterstrich."""
    text = re.sub(r"(\[[A-Z_]+_\d+\])(?:[ _.-]+\1)+", r"\1", text)
    return re.sub(r"[\[\]]", "", text).replace(" ", "_")[:120]


def main():
    ap = argparse.ArgumentParser(description="E-Mail-Exporte lokal anonymisieren (.txt, .csv, .mbox, .eml).")
    ap.add_argument("dateien", nargs="+", help="Eingabedatei(en), Platzhalter wie *.eml erlaubt")
    ap.add_argument("-o", "--ausgabe", "--ausgabeordner", dest="ausgabe", type=Path,
                    help="Zielordner oder (bei einer Eingabe) Zieldatei; Standard: <name>_anonym neben der Eingabe")
    ap.add_argument("--begriffe", type=Path, help="eigene Begriffe je Zeile: 'Begriff | LABEL', '!Begriff' = Ausnahme")
    ap.add_argument("--ausnahmen", type=Path, help="zusätzliche Datei mit Begriffen, die nie ersetzt werden")
    ap.add_argument("--kein-ner", "--ohne-ner", dest="kein_ner", action="store_true",
                    help="spaCy-Namenserkennung abschalten")
    ap.add_argument("--ner-modell", "--modell", dest="ner_modell", default="de_core_news_lg",
                    help="spaCy-Modell (Standard: de_core_news_lg, sonst md/sm)")
    ap.add_argument("--ner-labels", default="PER,ORG,LOC",
                    help="NER-Typen, z. B. PER oder PER,ORG (Standard: PER,ORG,LOC)")
    ap.add_argument("--kunde", action="append", default=[], metavar="TEXT",
                    help="nur Mails mit TEXT in Von/An/Cc (Adresse, Domain oder Name), mehrfach möglich; "
                         "bei .txt wird die ganze Mail durchsucht")
    ap.add_argument("--jahr", type=int, help="nur Mails aus diesem Jahr, z. B. 2026")
    ap.add_argument("--ab", type=datum_argument, metavar="DATUM", help="nur Mails ab Datum (2026-01-31 oder 31.01.2026)")
    ap.add_argument("--bis", type=datum_argument, metavar="DATUM", help="nur Mails bis einschließlich Datum")
    ap.add_argument("--ordner", help="Name des Ausgabeordners (Standard: anonym_<Zeitstempel>)")
    ap.add_argument("--zuordnung", type=Path,
                    help="Liste Platzhalter/Original als CSV speichern (dann nur Pseudonymisierung!)")
    args = ap.parse_args()

    pfade = []
    for angabe in args.dateien:
        pfade += [Path(p) for p in sorted(glob.glob(angabe))] if any(c in angabe for c in "*?") else [Path(angabe)]
    if not pfade:
        sys.exit("Keine passenden Dateien gefunden.")

    ausnahmen, begriffe = zeilen_lesen(args.ausnahmen), []
    for zeile in zeilen_lesen(args.begriffe):
        (ausnahmen if zeile.startswith("!") else begriffe).append(zeile.lstrip("!").strip())
    anon = Anonymisierer(ausnahmen)
    for zeile in begriffe:
        teile = re.split(r"[|=]", zeile, maxsplit=1)
        label = re.sub(r"\W+", "_", teile[1].strip().upper()).strip("_") if len(teile) > 1 else ""
        anon.begriff(teile[0].strip(), label or "BEGRIFF")

    filt = Filter(args.kunde,
                  args.ab or (date(args.jahr, 1, 1) if args.jahr else None),
                  args.bis or (date(args.jahr, 12, 31) if args.jahr else None))
    dokumente = []
    for pfad in pfade:
        try:
            dok = laden(pfad, filt)
        except (OSError, ValueError, mailbox.Error) as fehler:
            sys.exit(f"Fehler bei {pfad}: {fehler}")
        st = dok["stat"]
        if st["gesamt"]:
            extra = f", {st['ohne_datum']} ohne erkennbares Datum übersprungen" if st["ohne_datum"] else ""
            print(f"{pfad.name}: {st['passend']} von {st['gesamt']} {dok['einheit']} passen zum Filter{extra}")
            if not st["passend"]:
                continue
        dokumente.append((pfad, dok))
    if not dokumente:
        sys.exit("Keine passenden Mails gefunden – nichts geschrieben.")

    # Durchlauf 1: Namen sammeln (damit sie in allen Dateien einheitlich ersetzt werden)
    freitexte = []
    for _, dok in dokumente:
        if dok["typ"] == "xlsx":
            for ws in dok["wb"].worksheets:
                zeilen = list(ws.iter_rows(values_only=True))
                kopf = [str(k or "") for k in (zeilen[0] if zeilen else ())]
                namensspalten = [i for i, k in enumerate(kopf) if NAMENSSPALTE.search(k)]
                for zeile in zeilen[1:]:
                    for i in namensspalten:
                        if i < len(zeile) and isinstance(zeile[i], str):
                            for n in zeile[i].split(";"):
                                anon.name(n, streng=False)
                    for zelle in zeile:
                        if isinstance(zelle, str) and zelle.strip() and not zelle.startswith("="):
                            anon.namen_aus_text(zelle)
                            if len(zelle) >= 20 and " " in zelle.strip():
                                freitexte.append(zelle)
        elif dok["typ"] == "csv":
            kopf, *daten = dok["zeilen"] or [[]]
            namensspalten = [i for i, k in enumerate(kopf) if NAMENSSPALTE.search(k)]
            for zeile in daten:
                for i in namensspalten:
                    if i < len(zeile):
                        for n in zeile[i].split(";"):
                            anon.name(n, streng=False)
                for zelle in zeile:
                    if zelle.strip():
                        anon.namen_aus_text(zelle)
                        if len(zelle) >= 20 and " " in zelle.strip():   # NER nur auf Fließtext
                            freitexte.append(zelle)
        else:
            for n in dok["namen"]:
                anon.name(n, streng=False)
            anon.namen_aus_text(dok["text"])
            freitexte.append(dok["text"])

    if not args.kein_ner:
        nlp = ner_laden(args.ner_modell)
        if nlp:
            labels = {x.strip().upper() for x in args.ner_labels.split(",") if x.strip()}
            anon.ner_sammeln(nlp, freitexte, labels)

    # Durchlauf 2: ersetzen und schreiben
    # Ein neuer Ordner pro Lauf, damit nie etwas überschrieben wird
    einzeldatei = bool(args.ausgabe and args.ausgabe.suffix and len(pfade) == 1)
    zielordner = None
    if not einzeldatei:
        basis = args.ausgabe or pfades_basis(pfade)
        zielordner = basis / (args.ordner or f"anonym_{datetime.now():%Y%m%d-%H%M%S}")
        if zielordner.exists() and any(zielordner.iterdir()):
            sys.exit(f"Abbruch: {zielordner} existiert und ist nicht leer.")
        zielordner.mkdir(parents=True, exist_ok=True)

    geschrieben = set()
    for pfad, dok in dokumente:
        endung = {"csv": ".csv", "xlsx": ".xlsx"}.get(dok["typ"], ".txt")
        if einzeldatei:
            ziel = args.ausgabe
        else:
            # Dateinamen durch dieselben Platzhalter ersetzen wie den Inhalt
            name = dateiname_bereinigen(anon.ersetzen(pfad.stem)) or "datei"
            ziel = zielordner / f"{name}{endung}"
            n = 2
            while ziel in geschrieben:
                ziel = zielordner / f"{name}_{n}{endung}"
                n += 1
        if ziel.resolve() == pfad.resolve():
            sys.exit(f"Abbruch: Ausgabe würde die Eingabedatei {pfad} überschreiben.")
        ziel.parent.mkdir(parents=True, exist_ok=True)
        geschrieben.add(ziel)
        if dok["typ"] == "xlsx":
            formeln = 0
            for ws in dok["wb"].worksheets:
                for zeile in ws.iter_rows():
                    for zelle in zeile:
                        v = zelle.value
                        if isinstance(v, str):
                            if v.startswith("="):
                                formeln += 1          # Formeln bleiben unverändert
                            else:
                                zelle.value = anon.ersetzen(v)
                        if zelle.comment is not None:
                            zelle.comment.text = anon.ersetzen(zelle.comment.text)
                            zelle.comment.author = ""
            wb = dok["wb"]
            wb.properties.creator = None
            wb.properties.lastModifiedBy = None
            wb.properties.title = None
            wb.save(ziel)
            if formeln:
                print(f"  ! {pfad.name}: {formeln} Formel(n) unverändert – Text darin wird NICHT geprüft.")
        elif dok["typ"] == "csv":
            with open(ziel, "w", encoding="utf-8-sig", newline="") as f:
                schreiber = csv.writer(f, delimiter=dok["trenner"])
                for nr, zeile in enumerate(dok["zeilen"]):
                    schreiber.writerow(zeile if nr == 0 else [anon.ersetzen(z) for z in zeile])
        else:
            with open(ziel, "w", encoding="utf-8", newline="") as f:
                f.write(anon.ersetzen(dok["text"]))
        print(f"Geschrieben: {ziel}")
    if zielordner:
        print(f"\nAusgabeordner: {zielordner}")

    if args.zuordnung:
        def sortierung(ph):
            m = re.match(r"\[(.+)_(\d+)\]$", ph)
            return (m.group(1), int(m.group(2))) if m else (ph, 0)
        with open(args.zuordnung, "w", encoding="utf-8-sig", newline="") as f:
            schreiber = csv.writer(f, delimiter=";")
            schreiber.writerow(["Platzhalter", "Original"])
            for ph in sorted(anon.originale, key=sortierung):
                for original in sorted(anon.originale[ph]):
                    schreiber.writerow([ph, original])
        print(f"Zuordnungsliste: {args.zuordnung} – enthält Klardaten, sicher aufbewahren oder löschen!")

    print("\nErsetzt (Anzahl / verschiedene Werte):")
    for label in sorted(anon.treffer):
        print(f"  {label:<16}{anon.treffer[label]:>6}  / {anon.zaehler[label]}")
    print("\nBitte das Ergebnis stichprobenartig prüfen – automatische Erkennung ist nie vollständig.")


if __name__ == "__main__":
    main()
