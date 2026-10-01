"""BTA formatted text ("§" codes in BTA's own colour order: 0 white ... f black, plus
§<#rrggbb>) to 1.17 JSON text components, which the DataFixer later turns into 26.3 components."""

from __future__ import annotations

import re

# RGB of BTA's DyeColor, indexed by block colour meta (0 white ... 15 black)
DYE_RGB = (0xF0F0F0, 0xEB8844, 0xC354CD, 0x6689D3, 0xDECF2A, 0x41CD34, 0xD88198, 0x434343, 0xABABAB, 0x287697,
           0x7B2FBE, 0x253192, 0x51301A, 0x3B511A, 0xB3312C, 0x1E1B1B)

_STRIP = re.compile(r"§[0-9a-fk-pr+\-]|§<(.*?)>")
_HEX = re.compile(r"#?[0-9a-fA-F]{6}")


def strip_formatting(s: str) -> str:
    return _STRIP.sub("", s)


def escape_json(s: str) -> str:
    out = []
    for c in s:
        if c == '"':
            out.append('\\"')
        elif c == "\\":
            out.append("\\\\")
        elif c == "\n":
            out.append("\\n")
        elif c == "\r":
            out.append("\\r")
        elif c == "\t":
            out.append("\\t")
        elif ord(c) < 0x20:
            out.append("\\u%04x" % ord(c))
        else:
            out.append(c)
    return "".join(out)


def json_text(text: str, color=None) -> str:
    s = '{"text":"' + escape_json(text) + '"'
    if color is not None:
        s += ',"color":"' + color + '"'
    # custom item names in 1.17 are italic by default; BTA names are not
    return s + ',"italic":false}'


def json_plain(text: str) -> str:
    return '{"text":"' + escape_json(text) + '"}'


def _run(text, color, bold, italic, underline, strike, obf) -> str:
    s = '{"text":"' + escape_json(text) + '"'
    if color is not None:
        s += ',"color":"' + color + '"'
    if bold:
        s += ',"bold":true'
    if italic:
        s += ',"italic":true'
    if underline:
        s += ',"underlined":true'
    if strike:
        s += ',"strikethrough":true'
    if obf:
        s += ',"obfuscated":true'
    return s + "}"


def formatted_to_json(s: str) -> str:
    """A BTA string with § codes -> JSON text component (plain when there is no formatting)."""
    if not s:
        return '{"text":""}'
    if "§" not in s:
        return json_plain(s)
    parts = []
    color = None
    bold = italic = underline = strike = obf = False
    run = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "§" and i + 1 < n:
            code = s[i + 1].lower()
            new_color = color
            nb, ni, nu, ns, no = bold, italic, underline, strike, obf
            skip = 1
            if code == "<":
                end = s.find(">", i + 2)
                if end < 0:
                    run.append(c)
                    i += 1
                    continue
                arg = s[i + 2:end]
                if _HEX.fullmatch(arg):
                    new_color = "#" + arg.replace("#", "").upper()
                skip = end - i
            elif "0" <= code <= "9" or "a" <= code <= "f":
                new_color = "#%06X" % DYE_RGB[int(code, 16)]
            elif code == "k":
                no = True
            elif code == "l":
                nb = True
            elif code == "m":
                ns = True
            elif code == "n":
                nu = True
            elif code == "o":
                ni = True
            elif code in ("r", "-", "+"):
                new_color = None
                nb = ni = nu = ns = no = False
            if run:
                parts.append(_run("".join(run), color, bold, italic, underline, strike, obf))
                run = []
            color, bold, italic, underline, strike, obf = new_color, nb, ni, nu, ns, no
            i += skip + 1
        else:
            run.append(c)
            i += 1
    if run:
        parts.append(_run("".join(run), color, bold, italic, underline, strike, obf))
    if not parts:
        return '{"text":""}'
    return '{"text":"","extra":[' + ",".join(parts) + "]}"
