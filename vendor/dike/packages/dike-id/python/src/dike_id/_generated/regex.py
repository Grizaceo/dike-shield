# GENERATED FILE — DO NOT EDIT (packages/dike-id/gen/generate.py)
# spec-version: 2.0.0
# generator-version: 1.0.0
# sha256-of-source: 4fe6683c046f9f5e21b4a39aedd1c44963a51170d57fe762e12628fd7609258e
import re

SPEC_VERSION = '2.0.0'
GRAMMAR_SHA256 = '4fe6683c046f9f5e21b4a39aedd1c44963a51170d57fe762e12628fd7609258e'
MAX_LENGTH = 256
PATTERN = '^(?:cl\\.v2\\.norma\\.(?P<norm_slug>[a-z][0-9a-z]*(?:_[0-9a-z]+)*)(?::ver:(?P<norm_ver>[0-9]{8}))?(?::(?P<norm_unit>art:(?:unico|final|(?:000[1-9]|00[1-9][0-9]|0[1-9][0-9]{2}|[1-9][0-9]{3})(?:(?:_(?:bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies|undecies|duodecies|terdecies|quaterdecies|quindecies|[a-z]{2}|[a-z]|enie|[1-9][0-9]{0,2})){1,4})?)(?::(?:trans|final))?(?::x:u[2-7a-z]{10})?(?::inc:(?:0[1-9]|[1-9][0-9]|[1-9][0-9]{2}|[1-9][0-9]{3})(?::x:u[2-7a-z]{10})?)?(?::num:(?:0[1-9]|[1-9][0-9]|[1-9][0-9]{2}|[1-9][0-9]{3})(?:_(?:bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies|undecies|duodecies|terdecies|quaterdecies|quindecies))?(?::x:u[2-7a-z]{10})?)?(?::lit:(?:[a-z]|enie)(?:_(?:bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies|undecies|duodecies|terdecies|quaterdecies|quindecies))?(?::x:u[2-7a-z]{10})?)?|(?:lib|tit|cap|par|sec|div):(?:prelim|unico|final|trans|(?:000[1-9]|00[1-9][0-9]|0[1-9][0-9]{2}|[1-9][0-9]{3})(?:(?:_(?:bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies|undecies|duodecies|terdecies|quaterdecies|quindecies|[a-z]{2}|[a-z]|enie|[1-9][0-9]{0,2})){1,4})?|[a-z]|enie)(?::x:u[2-7a-z]{10})?(?::(?:lib|tit|cap|par|sec|div):(?:prelim|unico|final|trans|(?:000[1-9]|00[1-9][0-9]|0[1-9][0-9]{2}|[1-9][0-9]{3})(?:(?:_(?:bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies|undecies|duodecies|terdecies|quaterdecies|quindecies|[a-z]{2}|[a-z]|enie|[1-9][0-9]{0,2})){1,4})?|[a-z]|enie)(?::x:u[2-7a-z]{10})?)*|unn:(?:pre|prom|head|other):u[2-7a-z]{10}|unres:u[2-7a-z]{10}))?|cl\\.v2\\.sentencia\\.(?P<court>[a-z][0-9a-z]*(?:_[0-9a-z]+)*)\\.(?P<jud_year>[0-9]{4})\\.(?P<jud_key>[a-z][0-9a-z]*_[1-9][0-9]{0,8})(?::x:u[2-7a-z]{10})?(?::(?P<jud_par>par:(?:0[1-9]|[1-9][0-9]|[1-9][0-9]{2}|[1-9][0-9]{3})(?::x:u[2-7a-z]{10})?))?)$'
CAPTURES = ['norm_slug', 'norm_ver', 'norm_unit', 'court', 'jud_year', 'jud_key', 'jud_par']
_RX = re.compile(PATTERN)


def full_match(s):
    """Consumo total: fullmatch, nunca solo ^…$ (Python acepta un \n final con $)."""
    if not isinstance(s, str) or '\r' in s or '\n' in s or len(s) > MAX_LENGTH:
        return None
    return _RX.fullmatch(s)
